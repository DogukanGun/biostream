# Phase 1 — Validate with Gadgetbridge (Amazfit Helio Strap)

Goal: confirm the auth key works and get real control of the strap, using the proven
open-source driver, BEFORE we build our own client. This is our known-good baseline.

## 0. Get the auth key (on your own terminal — keeps password private)
```bash
huami-token --method amazfit --email YOUR_ZEPP_EMAIL --password 'YOUR_PASSWORD' --bt_keys
```
Record the Helio Strap's line:
- MAC: ____________________
- AUTH KEY (0x...): ____________________

## 1. Free the band from the Zepp app
A band holds ONE BLE connection. Before pairing Gadgetbridge:
- Close the Zepp app (or turn off its background sync), OR unpair the strap from Zepp.
- Keep Zepp installed — you needed it for the key, and can re-pair later.

## 2. Install Gadgetbridge (Android)
- Best source: **F-Droid** (search "Gadgetbridge") — the full, unrestricted build.
  (The Play Store "Gadgetbridge" is a limited fork — prefer F-Droid.)
- Or download the APK from https://gadgetbridge.org / Codeberg releases.

## 3. Add the strap with the auth key
1. Open Gadgetbridge → "+" to add a device → let it scan.
2. Pick the Amazfit Helio Strap.
3. When prompted, paste the **auth key** including the leading `0x`.
   (Make sure it's a real `0` + lowercase `x`.)
4. It should pair and show battery/status.

## 4. Drive it — confirm control works
Try the screenless-band control surface:
- **Find device** → should buzz the vibration motor  ← the "hello world" of control
- Set an **alarm** → confirm it triggers
- Open **device settings** → change something, confirm it sticks
- **Fetch activity** → pulls HR / sleep / HRV data

If "Find device" makes it vibrate, the key + protocol are proven. ✅
Then we move to Phase 2: replicate this in our own Python/bleak client.

## Notes
- If pairing fails: ensure Zepp isn't holding the connection, and that the key matches
  the strap's MAC (huami-token may list several devices).
- Gadgetbridge's source is our Phase-2 cheat sheet — it's the exact Zepp OS protocol
  we'll mirror.
