"""
Worker — background data collector. Requests auth from the Authenticator (never reads secrets
itself); fetches strap (live + history) + Oura; computes analytics; writes data/ (helio.db + the
JSON snapshots). The dashboard and the GraphQL gateway read those files.

Run:  python3 worker.py   (strap free: phone Bluetooth off, NOT unpaired)
"""
import asyncio
import time

import helio
helio.DEBUG = False
from helio import (EP_HEARTRATE, HR_REALTIME_SET, HR_MODE_CONTINUE,
                   FT_ACTIVITY, FT_RESTING_HR, FT_MAX_HR, FT_SPO2_NORMAL, FT_STRESS_AUTO, FT_PAI)
import oura
import analyze
from authenticator import Authenticator
from store import Store

RESYNC_EVERY = 30 * 60        # re-sync history every 30 min
auth = Authenticator()


async def refresh_oura():
    """Pull Oura (token from the authenticator) in a worker thread so BLE isn't blocked."""
    token = auth.oura_token()
    if not token:
        return

    def _do():
        out = oura.fetch_all(token)
        oura._write(out)
        return out
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, _do)
        if out is not None:
            print(f"  oura: {len(out.get('nights', []))} nights refreshed")
    except Exception as e:
        print(f"  oura refresh failed: {e}")


async def refresh_insights():
    """Recompute analytics (pandas) in a worker thread so BLE isn't blocked."""
    try:
        out = await asyncio.get_event_loop().run_in_executor(None, analyze.refresh)
        if out is not None:
            print(f"  insights: {out['n_nights']} nights, recovery {out['recovery'].get('today')}, "
                  f"{len(out['insights'])} findings")
    except Exception as e:
        print(f"  insights refresh failed: {e}")


async def sync_history(c, store):
    """One pass over all historical data types. Each isolated so one failure can't kill the rest."""
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


async def run_once(store):
    c = await auth.strap_session()           # authenticator loads the key + runs ECDH
    if c is None:
        raise RuntimeError("auth failed")
    c.on_hr = store.add_hr
    c.on_steps = store.set_steps
    store.connected = True
    store.set_battery(await c.read_battery())

    print("Syncing history...")
    await sync_history(c, store)
    await refresh_oura()
    await refresh_insights()

    print("Starting realtime HR + steps...")
    await c.start_realtime_hr()
    await c.start_realtime_steps()
    print("Streaming -> data/live.json   (Ctrl-C to stop)")

    last_resync = time.time()
    try:
        while True:
            await asyncio.sleep(11)
            await c._send(EP_HEARTRATE, bytes([HR_REALTIME_SET, HR_MODE_CONTINUE]), encrypt=c.hr_encrypt)
            await c.steps_keepalive_tick()
            store.set_battery(await c.read_battery())
            if time.time() - last_resync > RESYNC_EVERY:
                await sync_history(c, store)
                await refresh_oura()
                await refresh_insights()
                last_resync = time.time()
    finally:
        await c.close()


async def main():
    store = Store()
    store.write_live()
    store.write_history()
    await refresh_oura()      # populate Oura + insights immediately, independent of the BLE link
    await refresh_insights()
    while True:
        try:
            await run_once(store)
        except Exception as e:
            print(f"[worker] {e} — reconnecting in 5s")
        store.connected = False
        store.write_live()
        await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped.")
