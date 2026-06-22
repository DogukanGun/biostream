"""
Find + connect to the Oura Ring 4 and dump its GATT (with attribute handles, to map the
ringverse handles 0x0015 write / 0x0012 notify to real characteristic UUIDs).

The ring uses a ROTATING private address, so we re-scan and connect immediately each round
(a stale address = instant timeout). Best odds: ring ON ITS CHARGER, charger right against the
Mac, iPhone Bluetooth fully OFF. Charging tends to put it in a connectable (setup) advert mode.
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner


async def dump(client):
    print(f"\n*** CONNECTED: {client.address}  (MTU ~{getattr(client, 'mtu_size', '?')}) ***\n")
    for svc in client.services:
        print(f"[Service] {svc.uuid}")
        for ch in svc.characteristics:
            props = ",".join(ch.properties)
            flag = ""
            if ch.handle == 0x0015:
                flag = "   <-- WRITE 0x0015"
            elif ch.handle == 0x0012:
                flag = "   <-- NOTIFY 0x0012"
            print(f"   [Char] handle=0x{ch.handle:04x}  {ch.uuid}  ({props}){flag}")
            for d in ch.descriptors:
                print(f"      [Descr] handle=0x{d.handle:04x}  {d.uuid}")
    print("\nGATT dump complete.")


async def main():
    for rnd in range(14):
        dev = await BleakScanner.find_device_by_filter(
            lambda d, adv: "oura" in (adv.local_name or d.name or "").lower(),
            timeout=10.0,
        )
        if not dev:
            print(f"  [{rnd:02d}] ring not advertising this round")
            continue
        print(f"  [{rnd:02d}] found {dev.address} — connecting immediately...")
        try:
            async with BleakClient(dev, timeout=10.0) as client:
                await dump(client)
                return
        except Exception as e:
            print(f"  [{rnd:02d}] connect failed ({type(e).__name__})")
    sys.exit("\nNever caught a connectable window. Try: ring on charger AGAINST the Mac, iPhone "
             "Bluetooth fully off; or take it off + put back on right before running.")


if __name__ == "__main__":
    asyncio.run(main())
