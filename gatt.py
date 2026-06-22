#!/usr/bin/env python3
"""Connect to a BLE device and dump ALL its GATT services & characteristics.

This is the map of the band: every service (group) and characteristic (endpoint),
with its properties (read/write/notify) and any standard info we can read without
authentication (model, firmware, battery, etc).

Usage:
    python3 gatt.py <ADDRESS-or-NAME>
    python3 gatt.py "Amazfit Bip"
    python3 gatt.py 1A2B3C4D-....         # macOS CoreBluetooth UUID from scan.py

IMPORTANT: a band usually allows only ONE active BLE connection. If your phone's
Zepp app is connected, the Mac may fail to connect. Temporarily turn off Bluetooth
on the phone (or close Zepp) while you run this.
"""
import sys
import asyncio
from bleak import BleakClient, BleakScanner

# Standard GATT characteristics worth auto-reading (Device Information + Battery)
READABLE = {
    "00002a00-0000-1000-8000-00805f9b34fb": "Device Name",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Rev",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Rev",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Rev",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer",
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
}


async def resolve(target: str):
    print(f"Looking for '{target}' (15s)...")
    t = target.lower()

    def match(d, adv):
        return (t == d.address.lower()
                or t in (adv.local_name or "").lower()
                or t in (d.name or "").lower())

    dev = await BleakScanner.find_device_by_filter(match, timeout=15.0)
    if dev is None:
        print("  (not found in scan; trying to connect to the raw string anyway)")
        return target
    print(f"  found: {dev.name or '(no name)'} @ {dev.address}")
    return dev


async def main(target: str):
    dev = await resolve(target)
    async with BleakClient(dev) as client:
        print(f"\nConnected: {client.address}\n")
        for service in client.services:
            print(f"[Service] {service.uuid}  ({service.description})")
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                print(f"   [Char] {ch.uuid}  ({props})  {ch.description}")
                label = READABLE.get(ch.uuid.lower())
                if label and "read" in ch.properties:
                    try:
                        val = await client.read_gatt_char(ch)
                        text = val.decode(errors="replace")
                        print(f"        -> {label}: {text!r}   (hex {val.hex()})")
                    except Exception as e:
                        print(f"        -> {label}: read failed ({e})")
                for d in ch.descriptors:
                    print(f"      [Descr] {d.uuid}")
        print("\nDone. Save this output -- it's the band's map. "
              "Next we tackle the auth handshake.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
