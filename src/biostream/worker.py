"""
Worker — background data collector. Requests auth from the Authenticator; fetches the strap
(live + history) + Oura; computes analytics; writes to Config.data_dir (helio.db + JSON snapshots).
Cancellable: `run_worker(config)` can be run standalone or as a FastAPI lifespan task.
"""
import asyncio
import time

from . import helio
helio.DEBUG = False
from .helio import (EP_HEARTRATE, HR_REALTIME_SET, HR_MODE_CONTINUE,
                    FT_ACTIVITY, FT_RESTING_HR, FT_MAX_HR, FT_SPO2_NORMAL, FT_STRESS_AUTO, FT_PAI)
from . import oura
from . import analyze
from .authenticator import Authenticator
from .store import Store


async def refresh_oura(config):
    token = config.oura_token
    if not token:
        return

    def _do():
        out = oura.fetch_all(token, base=config.oura_api_url, days=config.oura_days)
        oura.write(out, config.oura_json)
        return out
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, _do)
        if out is not None:
            print(f"  oura: {len(out.get('nights', []))} nights refreshed")
    except Exception as e:
        print(f"  oura refresh failed: {e}")


async def refresh_insights(config):
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, analyze.refresh, config)
        if out is not None:
            print(f"  insights: {out['n_nights']} nights, recovery {out['recovery'].get('today')}, "
                  f"{len(out['insights'])} findings")
    except Exception as e:
        print(f"  insights refresh failed: {e}")


async def sync_history(c, store):
    jobs = [
        ("activity",   lambda s: c.fetch_activity(s),            store.add_activity),
        ("resting_hr", lambda s: c.fetch_resting_hr(s),          store.add_resting_hr),
        ("max_hr",     lambda s: c.fetch_max_hr(s),              store.add_max_hr),
        ("spo2",       lambda s: c.fetch_spo2(s),                store.add_spo2),
        ("stress",     lambda s: c.fetch_stress(s, auto=True),   store.add_stress),
        ("pai",        lambda s: c.fetch_pai(s),                 store.add_pai),
    ]
    type_codes = {"activity": FT_ACTIVITY, "resting_hr": FT_RESTING_HR, "max_hr": FT_MAX_HR,
                  "spo2": FT_SPO2_NORMAL, "stress": FT_STRESS_AUTO, "pai": FT_PAI}
    for name, fetch, add in jobs:
        try:
            since = store.since_for(type_codes[name])
            rows = await fetch(since)
            add(rows)
            print(f"  sync {name:<10} +{len(rows)} rows (since {since:%Y-%m-%d %H:%M})")
        except Exception as e:
            print(f"  sync {name:<10} FAILED: {e}")
    store.write_history()


async def _run_once(config, auth, store):
    c = await auth.strap_session()
    if c is None:
        raise RuntimeError("strap auth failed / not found")
    c.on_hr = store.add_hr
    c.on_steps = store.set_steps
    store.connected = True
    store.set_battery(await c.read_battery())

    print("Syncing history...")
    await sync_history(c, store)
    await refresh_oura(config)
    await refresh_insights(config)

    print("Starting realtime HR + steps...")
    await c.start_realtime_hr()
    await c.start_realtime_steps()
    print("Streaming (Ctrl-C to stop)")

    last_resync = time.time()
    try:
        while True:
            await asyncio.sleep(11)
            await c._send(EP_HEARTRATE, bytes([HR_REALTIME_SET, HR_MODE_CONTINUE]), encrypt=c.hr_encrypt)
            await c.steps_keepalive_tick()
            store.set_battery(await c.read_battery())
            if time.time() - last_resync > config.resync_interval:
                await sync_history(c, store)
                await refresh_oura(config)
                await refresh_insights(config)
                last_resync = time.time()
    finally:
        await c.close()


async def run_worker(config):
    """Background collect loop with reconnect. Cancellable (clean BLE + Store teardown)."""
    auth = Authenticator(config)
    store = Store(config)
    store.write_live()
    store.write_history()
    await refresh_oura(config)
    await refresh_insights(config)
    try:
        while True:
            try:
                await _run_once(config, auth, store)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[worker] {e} — reconnecting in 5s")
            store.connected = False
            store.write_live()
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass
    finally:
        store.close()


def main():
    from .config import Config
    try:
        asyncio.run(run_worker(Config.from_env()))
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
