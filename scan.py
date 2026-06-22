#!/usr/bin/env python3
"""Scan for nearby BLE devices and flag likely fitness bands (Amazfit / Mi Band / Huawei).

Usage:
    python3 scan.py            # 12s scan
    python3 scan.py 20         # custom scan duration (seconds)

Tip: tap your band's screen right before/while scanning so it advertises.
On macOS, the "address" column is a CoreBluetooth UUID, NOT the Bluetooth MAC
(Apple hides MACs). That's fine for connecting locally; we'll get the real MAC
from the phone side when we need it for the auth key.
"""
import sys
import asyncio
from bleak import BleakScanner

# Bluetooth SIG company identifier(s) used by Huami (Amazfit / Mi Band)
KNOWN_VENDORS = {
    0x0157: "Anhui Huami (Amazfit/Mi Band)",
}
NAME_HINTS = ("amazfit", "mi band", "mi smart band", "xiaomi", "huami", "zepp",
              "gts", "gtr", "bip", "band", "huawei")


async def main(duration: float):
    print(f"Scanning for {duration:.0f}s... tap your band so it advertises.\n")
    found = await BleakScanner.discover(timeout=duration, return_adv=True)

    rows = []
    for addr, (dev, adv) in found.items():
        name = adv.local_name or dev.name or ""
        mfd = adv.manufacturer_data
        vendors = ", ".join(KNOWN_VENDORS.get(k, hex(k)) for k in mfd) or "-"
        likely = (0x0157 in mfd) or any(h in name.lower() for h in NAME_HINTS)
        rows.append((adv.rssi, addr, name, vendors, likely))

    rows.sort(key=lambda r: r[0], reverse=True)  # strongest signal first
    print(f"{'RSSI':>5}  {'ADDRESS (macOS UUID)':38}  {'NAME':22}  VENDOR")
    print("-" * 100)
    for rssi, addr, name, vendors, likely in rows:
        flag = "   <-- likely band" if likely else ""
        print(f"{rssi:>5}  {addr:38}  {(name or '(no name)'):22}  {vendors}{flag}")
    print(f"\n{len(rows)} devices seen. Note the ADDRESS or NAME of your band, then run:")
    print("    python3 gatt.py <ADDRESS-or-NAME>")


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    asyncio.run(main(dur))
