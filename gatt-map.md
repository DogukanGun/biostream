# Amazfit Helio Strap — annotated GATT map

Captured 2026-06-21. Firmware 3.7.0.1, HW 0.132.24.2. Protocol: **Huami-2021 / Zepp OS**.
macOS CoreBluetooth handle: connect by name "Amazfit Helio Strap" (MAC hidden by Apple).

## The channel that matters: service 0xfee0
Huami chars use the vendor UUID base `0000XXXX-0000-3512-2118-0009af100700`.

| Short | Props | Meaning |
|-------|-------|---------|
| `0016` | write-no-resp, notify | **Chunked-2021 WRITE** — host → device (auth + commands) |
| `0017` | write-no-resp, notify | **Chunked-2021 READ** — device → host (subscribe for replies) |
| `2a2b` | r/w/notify | Current Time (standard) |
| `0001` | write, notify | Legacy Huami main char (device events/config) |
| `0002/0004/0005/0006/0025` | notify/write | Legacy data/activity/config channels |

**Auth + all control happens over 0016/0017 as chunked, encrypted frames** (Huami-2021
`InitOperation2021` handshake derives a session key from our 16-byte AUTH_KEY).

## Other services
- `180a` Device Information — SN 24458532006996, HW 0.132.24.2, **SW/firmware 3.7.0.1**, "Amazfit".
- `1530` (`1531` control, `1532` data) — **DFU / firmware update. DO NOT WRITE HERE** (brick risk).
- `180d` Heart Rate — `2a37` HR Measurement (notify), `2a38` Body Sensor Location.
- `0xfee1` — `fedd`/`fede` (bleak's standard-UUID guesses are bogus; device-specific, ignore for now).
- `180f` Battery — `2a19` Battery Level, read 0x20 = 32%.

## Build plan (Phase 2)
1. Connect by name, subscribe notify on 0016 + 0017.
2. Implement Huami-2021 chunked encoder/decoder.
3. Implement InitOperation2021 auth handshake (session key from AUTH_KEY).
4. Send first command: find-device / vibrate.
