"""Phase 2/3 test: one full history sync of all data types, then print DB counts."""
import asyncio

import helio
helio.DEBUG = False
from helio import HelioClient, load_auth_key
from collector import Store, sync_history


async def main():
    store = Store()
    c = HelioClient(load_auth_key())
    c.on_hr = store.add_hr
    c.on_steps = store.set_steps
    if not await c.connect_and_auth():
        print("auth failed")
        return
    store.connected = True
    store.set_battery(await c.read_battery())
    print("\n=== history sync ===")
    await sync_history(c, store)
    print("\n=== DB row counts ===")
    for t in ("hr", "activity", "resting_hr", "max_hr", "spo2", "stress", "pai"):
        n = store.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<11}: {n}")
    # peek a few activity samples with HR
    print("\n=== sample activity rows (with HR) ===")
    for r in store.db.execute(
            "SELECT ts, steps, hr, sleep, deep_sleep, rem_sleep FROM activity "
            "WHERE hr>0 AND hr<255 ORDER BY ts DESC LIMIT 8").fetchall():
        from datetime import datetime
        print(f"  {datetime.fromtimestamp(r[0]/1000):%m-%d %H:%M}  steps+{r[1]:>3} hr={r[2]:>3} "
              f"sleep={r[3]}/{r[4]}/{r[5]}")
    await asyncio.sleep(0.3)
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
