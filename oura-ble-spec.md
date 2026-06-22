# Oura Ring 4 — BLE protocol (for live data, RE project)

Source: https://github.com/ringverse/protocol (oura/). Confirmed for Ring 4 only.
Goal: authenticate over BLE and stream live heart rate, like the Amazfit strap.

## Transport
- Write Request handle `0x0015`; Notification handle `0x0012`; channel `0x0004`. Little-endian.
- Frame: `[tag(1)][payload_len(1)][payload...]`. Responses arrive as notifications, same format.
- (We'll map these handles to actual GATT char UUIDs via a gatt.py dump of the ring.)

## Command tags (subset)
- 0x06 Set Realtime Measurements / 0x07 response  <-- LIVE DATA (payload UNDOCUMENTED -> must sniff)
- 0x08/09 firmware ver · 0x0C/0D battery · 0x10/11 get events · 0x12/13 sync time · 0x18/19 product info
- 0x24 Set Auth Key (provision) · 0x2F extended (0x2B get nonce, 0x2D authenticate)

## Auth handshake (THE gate)
1. `0x24 Set Auth Key` — phone provisions a 16-byte key to the ring at onboarding. `24 10 <16 bytes>`.
   resp `0x25` status. (Done once during onboarding; the key then lives in the app's storage.)
2. `2F 01 2B` Get Auth Nonce -> ring replies `0x2C` + 15-byte nonce.
3. `2F 11 2D <16 bytes>` Authenticate, where the 16 bytes = AES-128-ECB(nonce, key) PKCS5-padded
   (Node: createCipheriv("aes-128-ecb", key, "") autoPadding). resp `0x2E`:
   0x00=success, 0x01=auth error, 0x02=in factory reset, 0x03=not original onboarded device.

## The auth KEY — where it lives
- iOS: SQLite `…/AppDomain-com.ouraring.oura/<USER_ID>/assa.sqlite`,
       `SELECT id, auth_key FROM ringconfiguration;`  (16-byte key)
- Android: **"TODO: Investigate"** in the repo. We must find it ourselves. Candidates:
  - /data/data/com.ouraring.oura/databases/assa.sqlite (same "assa" db?) -> needs ROOT, or
  - decompile the APK (jadx) to find the storage path / mechanism, or
  - sniff onboarding BLE (HCI snoop): the `0x24 Set Auth Key` command carries the key in PLAINTEXT
    -> capture it during a factory-reset + re-onboard (destructive-ish; Oura cloud keeps history).

## Live data (0x06) — undocumented
Payload for Set Realtime Measurements is not in the repo. Plan: sniff the Oura app's
"Live Heart Rate / Workout HR" feature via Android HCI snoop log -> capture the 0x06 request
and the HR notification format on handle 0x0012 -> reimplement.

## Plan (mirrors the strap) — USER IS ON iOS + Mac
1. [ ] GATT-dump the ring (scan.py/gatt.py) -> map handles 0x0015/0x0012 to char UUIDs. SAFE first step.
2. [ ] Get the auth key (iOS, documented + non-destructive): make a LOCAL iPhone backup on the Mac
       (Finder backup, or `brew install libimobiledevice` -> `idevicebackup2 backup`), then extract
       `assa.sqlite` from the AppDomain-com.ouraring.oura domain (Manifest.db maps domain+path ->
       hashed file) and `SELECT id, auth_key FROM ringconfiguration`. -> build extract_oura_key.py.
       Caveat: only works if assa.sqlite isn't excluded-from-backup; if so, fall back to a sniff.
3. [ ] Implement auth in bleak: get-nonce (2F 01 2B) -> AES-128-ECB(nonce,key) PKCS5 -> authenticate (2F xx 2D).
4. [ ] Sniff "Live HR" to learn the 0x06 payload + HR notification format.
       iOS sniffing = Apple **PacketLogger** (install the Bluetooth logging profile on the iPhone,
       capture HCI on the Mac via PacketLogger.app from Xcode "Additional Tools"). NOT Android snoop.
5. [ ] Stream live HR -> dashboard (a second live source next to the strap).

## Tools: scan.py, gatt.py, bleak, AES helpers (chunked.py); iOS: libimobiledevice + Apple PacketLogger.
