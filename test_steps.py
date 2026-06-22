"""Quick Phase-0 test: realtime HR + realtime steps."""
import asyncio

import helio
helio.DEBUG = False
from helio import HelioClient, load_auth_key


async def main():
    c = HelioClient(load_auth_key())
    if not await c.connect_and_auth():
        print("auth failed")
        return
    c.on_steps = lambda s: print(f"  👣 steps today: {s}")
    c.on_hr = lambda b: print(f"  ❤️  {b} bpm")
    print("\n=== realtime HR + steps (walk around to move steps) ===\n")
    await c.start_realtime_hr()
    ok = await c.start_realtime_steps()
    print(f"steps enabled: {ok}\n")
    for _ in range(3):
        await asyncio.sleep(10)
        await c.steps_keepalive_tick()
    await c.stop_realtime_steps()
    await c.stop_realtime_hr()
    print(f"\nlatest steps={c.latest_steps}  latest hr={c.latest_hr}")
    await asyncio.sleep(0.3)
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
