"""
Amazfit Helio Strap — direct BLE client (Huami-2021 / Zepp OS).

Connect -> subscribe to the chunked-2021 channel -> ECDH-B163 auth handshake ->
make the strap vibrate (find-device). This is our own from-scratch reimplementation;
Gadgetbridge was only the reference.

Run:  python3 helio.py
The strap must be FREE (not connected to the phone's Zepp app or Gadgetbridge).
"""
import asyncio
import os
import re
import struct
import sys
from datetime import datetime, timedelta

from bleak import BleakClient, BleakScanner

from ecdh_b163 import ecdh_generate_public, ecdh_generate_shared
from chunked import Chunked2021, aes_ecb_encrypt
from fetch import (FetchSession, parse_activity, parse_hr_6byte, parse_spo2_normal,
                   parse_stress_auto, parse_stress_manual, parse_pai)

WRITE_UUID = "00000016-0000-3512-2118-0009af100700"   # phone -> band
READ_UUID  = "00000017-0000-3512-2118-0009af100700"   # band -> phone (notify) + acks

EP_AUTH = 0x0082
EP_FIND_DEVICE = 0x001a
FIND_START, FIND_STOP = 0x03, 0x06
EP_HEARTRATE = 0x001d
EP_BATTERY = 0x0029
EP_STEPS = 0x0016
STEPS_CMD_REPLY = 0x04
STEPS_CMD_ENABLE_REALTIME = 0x05
STEPS_CMD_ENABLE_REALTIME_ACK = 0x06
STEPS_CMD_REALTIME_NOTIFICATION = 0x07
HR_REALTIME_SET = 0x04
HR_MODE_STOP, HR_MODE_START, HR_MODE_CONTINUE = 0x00, 0x01, 0x02
HR_REALTIME_ACK = 0x05
HR_MEAS_UUID = "00002a37-0000-1000-8000-00805f9b34fb"   # standard Heart Rate Measurement
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"   # standard Battery Level
RESPONSE, SUCCESS, AUTH_FAIL = 0x10, 0x01, 0x25

# historical activity fetch (legacy plaintext transport, separate from chunked)
FETCH_CTRL_UUID = "00000004-0000-3512-2118-0009af100700"   # control: write-no-resp + notify
FETCH_DATA_UUID = "00000005-0000-3512-2118-0009af100700"   # data stream: notify
FT_ACTIVITY = 0x01
FT_PAI = 0x0d
FT_STRESS_MANUAL = 0x12
FT_STRESS_AUTO = 0x13
FT_SPO2_NORMAL = 0x25
FT_RESTING_HR = 0x3a
FT_MAX_HR = 0x3d

DEBUG = True


def log_tx(b):
    if DEBUG:
        print(f"      tx 0016: {b.hex()}")


def log_rx(b):
    if DEBUG:
        print(f"      rx 0017: {b.hex()}")


def load_auth_key(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret-keys.local.txt")
    with open(path) as f:
        m = re.search(r"AUTH_KEY\s*=\s*0x([0-9A-Fa-f]{32})", f.read())
    if not m:
        sys.exit("AUTH_KEY (0x + 32 hex) not found in " + path)
    return bytes.fromhex(m.group(1))


class HelioClient:
    def __init__(self, auth_key):
        self.auth_key = auth_key
        self.codec = Chunked2021(mtu=23)
        self.priv = None
        self.client = None
        self.queue = asyncio.Queue()
        self.auth_ok = asyncio.Event()
        self.auth_fail = asyncio.Event()
        # live-data state
        self.latest_hr = None
        self.hr_encrypt = False
        self.on_hr = None              # optional callback(bpm)
        self.on_steps = None           # optional callback(steps)
        self.latest_steps = None
        self.steps_encrypt = False
        self._app_seen = {}            # endpoint -> asyncio.Event (for ack/encryption autodetect)
        self._ble_lock = asyncio.Lock()  # serialize fetch vs realtime writes (used in collector)

    def _on_notify(self, _sender, data):
        data = bytes(data)
        log_rx(data)
        self.queue.put_nowait(data)

    async def _processor(self):
        while True:
            data = await self.queue.get()
            try:
                needs_ack, handle, count, message = self.codec.decode(data)
            except Exception as e:
                print(f"  [decode error] {e}: {data.hex()}")
                continue
            # Gadgetbridge order: handle the payload first, then ack.
            if message is not None:
                await self._handle(*message)
            if needs_ack:
                ack = bytes([0x04, 0x00, handle & 0xFF, 0x01, count & 0xFF])
                log_tx_ack(ack)
                await self.client.write_gatt_char(READ_UUID, ack, response=False)

    async def _send(self, endpoint, payload, encrypt=False):
        for chunk in self.codec.encode(endpoint, payload, encrypt):
            log_tx(chunk)
            await self.client.write_gatt_char(WRITE_UUID, chunk, response=False)

    async def _handle(self, type_, payload):
        if type_ != EP_AUTH:
            await self._handle_app(type_, payload)
            return
        if len(payload) >= 67 and payload[0] == RESPONSE and payload[1] == 0x04 and payload[2] == SUCCESS:
            remote_random = payload[3:19]
            remote_pub = payload[19:67]
            print(f"  <- step2: band random + public key ({len(payload)}B)")
            shared = ecdh_generate_shared(self.priv, remote_pub)
            if shared is None:
                print("  !! ECDH failed (remote pubkey not on curve)")
                self.auth_fail.set()
                return
            self.codec.encrypted_seq = struct.unpack("<I", shared[0:4])[0]
            session_key = bytes((shared[8 + i] ^ self.auth_key[i]) & 0xFF for i in range(16))
            self.codec.session_key = session_key
            e1 = aes_ecb_encrypt(remote_random, self.auth_key)     # proven via preshared key
            e2 = aes_ecb_encrypt(remote_random, session_key)       # proven via derived key
            print("  -> step3: sending encrypted-random proof")
            await self._send(EP_AUTH, bytes([0x05]) + e1 + e2, encrypt=False)
        elif payload[:3] == bytes([RESPONSE, 0x05, SUCCESS]):
            print("  <- step4: AUTH SUCCESS")
            self.auth_ok.set()
        elif payload[:3] == bytes([RESPONSE, 0x05, AUTH_FAIL]):
            print("  <- step4: AUTH FAILED (0x25) — wrong key?")
            self.auth_fail.set()
        else:
            print(f"  <- auth endpoint, unexpected: {payload.hex()}")

    async def connect_and_auth(self):
        print("Scanning for the Helio Strap (15s)...")
        dev = await BleakScanner.find_device_by_filter(
            lambda d, adv: "helio" in (adv.local_name or d.name or "").lower(),
            timeout=15.0,
        )
        if dev is None:
            sys.exit("Strap not found. Make sure it is NOT connected to your phone "
                     "(turn off phone Bluetooth / disconnect Zepp & Gadgetbridge).")
        print(f"Connecting to {dev.name} @ {dev.address} ...")
        self.client = BleakClient(dev)
        await self.client.connect()
        print(f"Connected. (ATT MTU ~{getattr(self.client, 'mtu_size', '?')})")
        await self.client.start_notify(READ_UUID, self._on_notify)
        asyncio.create_task(self._processor())

        self.priv = os.urandom(24)
        pub = ecdh_generate_public(self.priv)
        if pub is None:
            sys.exit("ECDH keypair generation failed (rerun)")
        print("  -> step1: sending our ECDH public key")
        await self._send(EP_AUTH, bytes([0x04, 0x02, 0x00, 0x02]) + pub, encrypt=False)

        ok = asyncio.create_task(self.auth_ok.wait())
        no = asyncio.create_task(self.auth_fail.wait())
        done, pending = await asyncio.wait({ok, no}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        return self.auth_ok.is_set()

    async def vibrate(self, seconds=5):
        print(f"  -> find-device START (buzz {seconds}s)")
        await self._send(EP_FIND_DEVICE, bytes([FIND_START]), encrypt=False)
        await asyncio.sleep(seconds)
        print("  -> find-device STOP")
        await self._send(EP_FIND_DEVICE, bytes([FIND_STOP]), encrypt=False)

    # ---- live data -----------------------------------------------------------
    async def _handle_app(self, type_, payload):
        ev = self._app_seen.get(type_)
        if ev is not None:
            ev.set()
        if type_ == EP_HEARTRATE and payload and payload[0] == HR_REALTIME_ACK:
            status = payload[1] if len(payload) > 1 else "?"
            print(f"  <- HR realtime ACK (status={status})")
        elif type_ == EP_BATTERY and payload and payload[0] == 0x04:
            print(f"  <- battery reply: {payload.hex()}")
        elif type_ == EP_STEPS and payload and payload[0] == STEPS_CMD_ENABLE_REALTIME_ACK:
            print(f"  <- steps realtime ACK (status={payload[1] if len(payload) > 1 else '?'})")
        elif type_ == EP_STEPS and payload and payload[0] in (STEPS_CMD_REALTIME_NOTIFICATION, STEPS_CMD_REPLY):
            steps = self._parse_steps(payload)
            if steps is not None:
                self.latest_steps = steps
                if self.on_steps:
                    self.on_steps(steps)
        else:
            print(f"  <- msg 0x{type_:04x}: {payload.hex()}")

    @staticmethod
    def _parse_steps(payload):
        # 0x07 realtime notification: steps = uint16 LE at payload[2:4]
        # 0x04 polled reply:          steps = uint16 LE at payload[3:5]
        if payload[0] == STEPS_CMD_REALTIME_NOTIFICATION and len(payload) >= 4:
            return int.from_bytes(payload[2:4], "little")
        if payload[0] == STEPS_CMD_REPLY and len(payload) >= 5:
            return int.from_bytes(payload[3:5], "little")
        return None

    def _on_hr_notify(self, _sender, data):
        data = bytes(data)
        if len(data) >= 2 and data[0] == 0x00:
            bpm = data[1]
            self.latest_hr = bpm
            print(f"  ❤️  {bpm} bpm")
            if self.on_hr:
                self.on_hr(bpm)
        elif DEBUG:
            print(f"      2a37 raw: {data.hex()}")

    async def read_battery(self):
        val = await self.client.read_gatt_char(BATTERY_UUID)
        return val[0] if val else None

    async def start_realtime_hr(self):
        """Subscribe to 2a37 and start the realtime stream, auto-detecting encryption."""
        await self.client.start_notify(HR_MEAS_UUID, self._on_hr_notify)
        for enc in (False, True):
            ev = asyncio.Event()
            self._app_seen[EP_HEARTRATE] = ev
            print(f"  -> HR START to 0x1d ({'encrypted' if enc else 'plaintext'})")
            await self._send(EP_HEARTRATE, bytes([HR_REALTIME_SET, HR_MODE_START]), encrypt=enc)
            try:
                await asyncio.wait_for(ev.wait(), timeout=4.0)
                self.hr_encrypt = enc
                print(f"  HR stream started (encrypt={enc})")
                return True
            except asyncio.TimeoutError:
                print(f"  no ACK ({'encrypted' if enc else 'plaintext'}); trying other mode...")
        return False

    async def hr_keepalive(self, seconds=60, interval=11):
        elapsed = 0
        while elapsed < seconds:
            await asyncio.sleep(min(interval, seconds - elapsed))
            elapsed += interval
            await self._send(EP_HEARTRATE, bytes([HR_REALTIME_SET, HR_MODE_CONTINUE]),
                             encrypt=self.hr_encrypt)

    async def stop_realtime_hr(self):
        await self._send(EP_HEARTRATE, bytes([HR_REALTIME_SET, HR_MODE_STOP]), encrypt=self.hr_encrypt)

    async def start_realtime_steps(self):
        """Enable realtime step streaming over the chunked channel (endpoint 0x16).
        Values arrive as [0x07, ...] in _handle_app -> on_steps. Auto-detects encryption."""
        for enc in (False, True):
            ev = asyncio.Event()
            self._app_seen[EP_STEPS] = ev
            print(f"  -> steps ENABLE to 0x16 ({'encrypted' if enc else 'plaintext'})")
            await self._send(EP_STEPS, bytes([STEPS_CMD_ENABLE_REALTIME, 0x01]), encrypt=enc)
            try:
                await asyncio.wait_for(ev.wait(), timeout=4.0)
                self.steps_encrypt = enc
                print(f"  steps stream enabled (encrypt={enc})")
                return True
            except asyncio.TimeoutError:
                print(f"  no steps ACK ({'encrypted' if enc else 'plaintext'}); trying other mode...")
        return False

    async def steps_keepalive_tick(self):
        # re-assert the realtime subscription (cheap; keeps push notifications flowing)
        await self._send(EP_STEPS, bytes([STEPS_CMD_ENABLE_REALTIME, 0x01]), encrypt=self.steps_encrypt)

    async def stop_realtime_steps(self):
        await self._send(EP_STEPS, bytes([STEPS_CMD_ENABLE_REALTIME, 0x00]), encrypt=self.steps_encrypt)

    # ---- historical activity fetch (plaintext transport over 0x0004 / 0x0005) ----
    async def _fetch_once(self, data_type, since, keep=True):
        """One fetch round. Returns (start_dt, buffer, expected_len, valid)."""
        async with self._ble_lock:
            sess = FetchSession(self.client, FETCH_CTRL_UUID, FETCH_DATA_UUID)
            await self.client.start_notify(FETCH_CTRL_UUID, sess.on_ctrl)
            await self.client.start_notify(FETCH_DATA_UUID, sess.on_data)
            try:
                start_dt, buf = await sess.fetch(data_type, since, keep=keep)
            finally:
                for u in (FETCH_CTRL_UUID, FETCH_DATA_UUID):
                    try:
                        await self.client.stop_notify(u)
                    except Exception:
                        pass
            return start_dt, buf, sess.expected_len, sess.valid

    async def _fetch_history(self, data_type, since, parser, max_rounds=10, keep=True):
        """Multi-round fetch since `since` (band returns data in chunks); returns all rows."""
        all_rows = []
        cur = since
        for _ in range(max_rounds):
            start_dt, buf, _e, _v = await self._fetch_once(data_type, cur, keep)
            if not buf:
                break
            rows = parser(start_dt, buf)
            if not rows:
                break
            all_rows.extend(rows)
            nxt = datetime.fromtimestamp(rows[-1]["ts"] / 1000) + timedelta(minutes=1)
            if nxt <= cur:   # no forward progress -> stop
                break
            cur = nxt
        return all_rows

    async def fetch_activity(self, since, keep=True):
        return await self._fetch_history(FT_ACTIVITY, since, parse_activity, keep=keep)

    async def fetch_resting_hr(self, since, keep=True):
        return await self._fetch_history(FT_RESTING_HR, since, parse_hr_6byte, keep=keep)

    async def fetch_max_hr(self, since, keep=True):
        return await self._fetch_history(FT_MAX_HR, since, parse_hr_6byte, keep=keep)

    async def fetch_spo2(self, since, keep=True):
        return await self._fetch_history(FT_SPO2_NORMAL, since, parse_spo2_normal, keep=keep)

    async def fetch_stress(self, since, keep=True, auto=True):
        parser = parse_stress_auto if auto else parse_stress_manual
        dt = FT_STRESS_AUTO if auto else FT_STRESS_MANUAL
        return await self._fetch_history(dt, since, parser, keep=keep)

    async def fetch_pai(self, since, keep=True):
        return await self._fetch_history(FT_PAI, since, parse_pai, keep=keep)

    async def close(self):
        try:
            if self.client:
                await self.client.disconnect()
        except Exception:
            pass


def log_tx_ack(b):
    if DEBUG:
        print(f"      tx 0017 (ack): {b.hex()}")


async def main():
    auth_key = load_auth_key()
    print(f"Loaded auth key: {len(auth_key)} bytes\n")
    c = HelioClient(auth_key)
    try:
        ok = await c.connect_and_auth()
        if ok:
            print("\n*** AUTHENTICATED — full ECDH+AES stack works on real hardware! ***\n")
            await c.vibrate(5)
            print("\nIf the strap buzzed, Milestone 2 is COMPLETE. "
                  "Next: read live data (HR/battery) over this same channel.")
        else:
            print("\nAuth did not complete (see log). If you saw step2 but not step4, "
                  "the crypto is close — check the auth key. If nothing came back, the strap "
                  "may need the post-auth init handshake before it talks.")
    finally:
        await asyncio.sleep(0.5)
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
