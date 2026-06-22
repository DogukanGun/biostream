# Huami-2021 / Zepp OS BLE protocol — wire spec (for Amazfit Helio Strap)

Source: Gadgetbridge master (clone at /tmp/gb-huami). For reimplementation in Python/bleak.
This is the BLE-direct path. Auth is required before ANY data/command.

## GATT
- Service `0000fee0-0000-3512-2118-0009af100700`
- WRITE char `00000016-...` (phone→band) — send chunks here (write-without-response)
- READ  char `00000017-...` (band→phone) — subscribe notify; ACKs are written here too
- Only 0017 is subscribed for notifications.

## Chunked-2021 framing (Zepp OS = extended-flags, always)
First chunk (11-byte header): `03 | flags | 00 | handle | count | len(uint32 LE) | type(uint16 LE) | payload`
Continuation: `03 | flags | 00 | handle | count | payload`
flags: 0x01=first, 0x02=last, 0x04=needs-ack, 0x08=encrypted. Single chunk = 0x07 (|0x08 if enc).
`handle` increments per message (1 byte, wraps). MAX_CHUNKLENGTH = MTU-3-header.
Incoming: data[0]==0x03 chunk, 0x04==ACK frame. ACK = write `04 00 handle 01 count` to 0017.

## Auth handshake (endpoint 0x0082, UNENCRYPTED) — ECDH B-163 + AES-128-ECB
1. →band: `04 02 00 02` + publicEC[48]      (privateEC = 24 random bytes; publicEC via B-163)
2. band→: `10 04 01` + remoteRandom[16] + remotePublicEC[48]
   - sharedEC = ECDH_B163(privateEC, remotePublicEC)  (24 bytes)
   - seq seed = sharedEC[0:4] as uint32 LE
   - sessionKey[i] = sharedEC[8+i] XOR authKey[i], i=0..15
3. →band: `05` + AES_ECB(remoteRandom, authKey)[16] + AES_ECB(remoteRandom, sessionKey)[16]
4. band→: `10 05 01` = success ; `10 05 25` = auth FAILED (wrong key)

authKey for this device = 0x5B03721A736873857B3F1A1A22A08997 (see secret-keys.local.txt)

## Encryption of post-auth messages (AES-128-ECB, per-message key)
- Per endpoint, encrypted iff band's service-list marks it (mIsEncrypted). Auth always plaintext.
- messageKey[i] = sessionKey[i] XOR handle   (handle = the chunk header handle byte)
- plaintext buffer = payload | seq(uint32 LE) | CRC32(payload|seq)(uint32 LE) | zero-pad to x16
- AES-ECB encrypt with messageKey; header `len` = original plaintext length.

## Find-device / vibrate (endpoint 0x001a)
- payload `03` = start buzzing, `06` = stop. (band→ sends 04=ack, 07=stopped-from-band)

## HARD DEPENDENCY
ECDH on curve **B-163 (sect163k1, binary field)**. Standard Python EC libs are incompatible.
Must port /tmp/gb-huami/.../util/ECDH_B163.java: priv 24B, pub 48B, shared 24B; sessionKey
uses shared[8:24], seq seed uses shared[0:4].

## Activity/health DATA fetch over BLE = SEPARATE, more complex protocol
Reading HR/sleep/HRV/SpO2/stress history is a distinct file-based sync (ZeppOsServices /
activity fetch), not yet specced here. This is why a cloud-API or Gadgetbridge-export
data source may be far faster for a "show all my data" dashboard.
