"""
Amazfit Helio Strap — live data over our authenticated BLE channel.

Auth -> read battery -> start realtime heart rate -> stream HR for ~60s.
Wear the strap snugly. Strap must be free (phone Bluetooth off, NOT unpaired).

Run:  python3 helio_live.py
"""
import asyncio

import helio
helio.DEBUG = False  # quiet the chunk-level tx/rx spam; keep the readable output

from helio import HelioClient, load_auth_key


async def main():
    c = HelioClient(load_auth_key())
    try:
        ok = await c.connect_and_auth()
        if not ok:
            print("Auth failed — is the key fresh and the strap free?")
            return

        print("\n=== AUTHENTICATED — pulling live data ===\n")

        batt = await c.read_battery()
        print(f"🔋 Battery: {batt}%")

        print("\nStarting realtime heart rate (first reading can take 5–15s)...")
        if await c.start_realtime_hr():
            print("Streaming for ~60s:\n")
            await c.hr_keepalive(seconds=60)
            await c.stop_realtime_hr()
            print(f"\nDone. Last HR: {c.latest_hr} bpm")
        else:
            print("HR stream didn't start on either encryption mode — "
                  "the band may need the post-auth init handshake first.")
    finally:
        await asyncio.sleep(0.5)
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
