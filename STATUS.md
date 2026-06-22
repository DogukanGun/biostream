# Project status — Amazfit Helio Strap reverse engineering

Goal: pure-BLE RE of the strap (no cloud, own every byte) -> Next.js dashboard of all data.

## Milestones
- [x] M0  Mac toolkit: bleak, scan.py, gatt.py, huami-token
- [x] M1  GATT mapped; Huami-2021 / Zepp OS confirmed; command channel = chars 0016/0017
- [x] M1b ECDH-B163 ported (ecdh_b163.py) + VERIFIED vs independent impl (verify_ecdh.py)
- [x] M1c Chunked-2021 codec ported (chunked.py) + round-trip verified incl. encryption
- [x] M2  *** LIVE AUTH HANDSHAKE SUCCEEDS *** against the strap (got 10 05 01)
- [x] M2b find-device / vibrate sent (channel proven)
- [x] M3  live data: battery (81%) + REALTIME HEART RATE streaming (endpoint 0x1d -> 2a37)
- [x] M4  HISTORICAL FETCH (plaintext transport over chars 0x0004/0x0005): activity (min HR/steps/
      sleep bytes), resting/max HR, SpO2, stress, PAI -> SQLite (fetch.py + helio.fetch_*). ACK=0x09 keep.
- [x] M5  Next.js dashboard LIVE at localhost:3000: live (HR/steps/battery) + history charts
      (steps/day, stress, activity HR, resting-HR/SpO2). collector.py -> live.json + history.json -> /api/*

## What's collected
- Realtime: heart rate (0x1d/2a37), steps (0x16 chunked), battery (2a19).
- Historical (fetch.py, since 14d default, incremental via sync_state): ACTIVITY 0x01 (per-minute
  steps/HR/sleep), RESTING_HR 0x3a, MAX_HR 0x3d, SPO2 0x25, STRESS_AUTO 0x13, PAI 0x0d.
- Types with no data yet (resting/max HR, SpO2) return 0x05 "no data" -> handled as empty; fill in
  as the band records them (wear overnight for sleep + resting HR).
- NOTE: activity `sleep` byte (idx5) is NOT a sleep flag (reads 7 while awake); sleep derived from
  deep_sleep/rem_sleep (idx6/7) only. Far-past `since` (100d) is rejected by the band -> use <=14d.
- Tests: test_steps.py, test_fetch.py, test_sync.py (all pass against hardware).

## Run the dashboard (two terminals)
- Terminal 1:  cd ~/amazfit-re && python3 collector.py        # BLE -> data/live.json + helio.db
- Terminal 2:  cd ~/amazfit-re/dashboard && npm run dev        # http://localhost:3000
- Keep phone Bluetooth OFF so the strap stays free for the Mac.
- [ ] M4  activity/history fetch (file-sync protocol) — later

## Live data (M3) how-to
- collector.py: long-running; auth -> realtime HR + battery -> writes data/live.json + helio.db
- HR endpoint 0x1d is PLAINTEXT on this device; values arrive on standard char 2a37 as [0x00,bpm]
- Battery via standard char 2a19. Keepalive: resend [0x04,0x02] to 0x1d every ~11s.

## How to run
1. Free the strap: phone Bluetooth OFF (never unpair — it kills the auth key).
2. `python3 helio.py`  -> connects by name, auths, buzzes.

## Key facts
- Connect by NAME "Amazfit Helio Strap" (macOS hides the MAC).
- Auth key in secret-keys.local.txt. Re-pairing changes the key AND the MAC.
- Firmware 3.7.0.1 (HW 0.132.24.2).
- Post-auth command encryption is per-endpoint (band's service-list / mIsEncrypted).
  find-device currently sent UNENCRYPTED; if no buzz, resend encrypted (we have the session key).

## Files
- ecdh_b163.py     B-163 ECDH (faithful port of Gadgetbridge ECDH_B163.java)
- chunked.py       Huami-2021 chunked encoder/decoder + AES-ECB helpers
- helio.py         the client: connect -> auth -> vibrate
- verify_ecdh.py   independent ECDH cross-check (decisive correctness test)
- huami2021-protocol-spec.md   wire spec; gatt-map.md annotated GATT
- Reference source: /tmp/gb-huami (Gadgetbridge clone)
