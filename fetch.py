"""
Huami / Zepp OS historical activity-fetch transport (PLAINTEXT) + parsers.

Separate from the encrypted Chunked2021 channel: uses GATT chars
  0x0004 (control: write-no-resp + notify)  and  0x0005 (data: notify).
Faithful to Gadgetbridge AbstractFetchOperation.java. No AES, no session key.

One fetch round per data type:
  -> 0x0004: [0x01, dataType] + time_bytes(since)            (START_DATE)
  <- 0x0004: [0x10,0x01,0x01, len(u32 LE), startDate(8)]     (expected bytes + first ts)
  -> 0x0004: [0x02]                                          (FETCH_DATA; subscribe 0x0005)
  <- 0x0005: [counter, ...bytes] * N                         (plaintext data, counter from 0)
  <- 0x0004: [0x10,0x02,0x01] (+ crc32 LE)                   (transfer complete)
  -> 0x0004: [0x03, 0x09]  (keep on band)                    (ACK)
  <- 0x0004: [0x10,0x03, ...]                                (op done)
"""
import asyncio
import struct
from datetime import datetime, timedelta, timezone

# control commands / responses
CMD_START_DATE = 0x01
CMD_FETCH_DATA = 0x02
CMD_ACK = 0x03
RESPONSE = 0x10
SUCCESS = 0x01
ACK_KEEP = 0x09     # keep data on band (re-fetchable, Zepp app keeps its data)
ACK_DROP = 0x01     # drop from band


class FetchError(Exception):
    pass


# ---- time bytes (ZeppOS MINUTES precision: 8 bytes) ------------------------
def time_bytes(dt):
    """Naive-local or aware datetime -> 8 bytes:
    yearLE(2), month(1-based), day, hour, minute, second=0, tz(quarter-hours signed)."""
    aware = dt.astimezone() if dt.tzinfo is None else dt
    tzqh = int(round(aware.utcoffset().total_seconds() / 900)) & 0xFF
    y = aware.year
    return bytes([y & 0xFF, (y >> 8) & 0xFF, aware.month, aware.day,
                  aware.hour, aware.minute, 0, tzqh])


def parse_time_bytes(b):
    """8-byte start date -> aware datetime (in the band's reported tz)."""
    year = b[0] | (b[1] << 8)
    month, day, hour, minute = b[2], b[3], b[4], b[5]
    second = b[6] if len(b) > 6 else 0
    tzqh = b[7] if len(b) > 7 else 0
    if tzqh >= 128:
        tzqh -= 256
    tz = timezone(timedelta(minutes=15 * tzqh))
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


def _ms(dt):
    return int(dt.timestamp() * 1000)


# ---- transport over chars 0x0004 / 0x0005 ----------------------------------
class FetchSession:
    def __init__(self, client, ctrl_uuid, data_uuid):
        self.client = client
        self.ctrl_uuid = ctrl_uuid
        self.data_uuid = data_uuid
        self.buffer = bytearray()
        self.last_counter = -1
        self.valid = True
        self.expected_len = 0
        self.start_dt = None
        self._meta = None
        self._meta_ev = asyncio.Event()

    # 0x0004 notify: metadata responses
    def on_ctrl(self, _sender, data):
        self._meta = bytes(data)
        self._meta_ev.set()

    # 0x0005 notify: counter-prefixed plaintext data
    def on_data(self, _sender, data):
        data = bytes(data)
        if not data:
            return
        counter = data[0]
        if ((self.last_counter + 1) & 0xFF) == counter:
            self.last_counter = counter
            self.buffer += data[1:]
        else:
            self.valid = False

    async def _wait_meta(self, timeout=30):
        await asyncio.wait_for(self._meta_ev.wait(), timeout)
        return self._meta

    async def fetch(self, data_type, since, keep=True):
        """One round. Returns (start_dt, buffer_bytes). buffer is b'' if no data."""
        self.buffer = bytearray()
        self.last_counter = -1
        self.valid = True

        # START_DATE
        self._meta_ev.clear()
        await self.client.write_gatt_char(
            self.ctrl_uuid, bytes([CMD_START_DATE, data_type]) + time_bytes(since), response=False)
        meta = await self._wait_meta()
        if not (len(meta) >= 3 and meta[0] == RESPONSE and meta[1] == CMD_START_DATE):
            raise FetchError(f"start-date bad response: {meta.hex()}")
        if meta[2] != SUCCESS:
            return (None, b"")          # e.g. 0x05 = no data for this type/range
        self.expected_len = struct.unpack_from("<I", meta, 3)[0]
        if self.expected_len == 0:
            await self._ack(keep)
            return (None, b"")          # caught up; nothing more
        self.start_dt = parse_time_bytes(meta[7:15])

        # FETCH_DATA (data streams in on on_data concurrently)
        self._meta_ev.clear()
        await self.client.write_gatt_char(self.ctrl_uuid, bytes([CMD_FETCH_DATA]), response=False)
        meta = await self._wait_meta(timeout=60)
        if not (len(meta) >= 3 and meta[0] == RESPONSE and meta[1] == CMD_FETCH_DATA and meta[2] == SUCCESS):
            raise FetchError(f"fetch-data bad response: {meta.hex()}")
        buf = bytes(self.buffer)

        await self._ack(keep)
        return (self.start_dt, buf)

    async def _ack(self, keep):
        self._meta_ev.clear()
        await self.client.write_gatt_char(
            self.ctrl_uuid, bytes([CMD_ACK, ACK_KEEP if keep else ACK_DROP]), response=False)
        try:
            await self._wait_meta(timeout=10)  # [0x10,0x03,...] = op done
        except asyncio.TimeoutError:
            pass


# ---- parsers (start_dt = aware datetime of first sample) -------------------
def parse_activity(start_dt, buf):
    """8 bytes/sample, 1 sample/minute: kind,intensity,steps,hr,unk1,sleep,deep,rem."""
    rows = []
    for i in range(len(buf) // 8):
        o = i * 8
        ts = _ms(start_dt + timedelta(minutes=i))
        rows.append({
            "ts": ts, "kind": buf[o], "intensity": buf[o + 1], "steps": buf[o + 2],
            "hr": buf[o + 3], "sleep": buf[o + 5], "deep_sleep": buf[o + 6], "rem_sleep": buf[o + 7],
        })
    return rows


def parse_hr_6byte(start_dt, buf):
    """RESTING_HR / MAX_HR: ts=u32 LE (s), utcOffsetQuarterHours=int8, hr=u8."""
    rows = []
    for i in range(len(buf) // 6):
        o = i * 6
        ts_s = struct.unpack_from("<I", buf, o)[0]
        rows.append({"ts": ts_s * 1000, "utc_offset": _signed8(buf[o + 4]), "hr": buf[o + 5]})
    return rows


def parse_spo2_normal(start_dt, buf):
    """1 version byte (==2) then 65-byte records: ts=u32 LE (s), spo2raw=int8 (<0 -> auto)."""
    rows = []
    if not buf:
        return rows
    body = buf[1:]  # skip version byte
    for i in range(len(body) // 65):
        o = i * 65
        ts_s = struct.unpack_from("<I", body, o)[0]
        raw = _signed8(body[o + 4])
        auto = raw < 0
        spo2 = raw + 128 if auto else raw
        rows.append({"ts": ts_s * 1000, "spo2": spo2, "auto": int(auto)})
    return rows


def parse_stress_auto(start_dt, buf):
    """1 byte/minute: value 0..100, 0xFF = no sample."""
    rows = []
    for i, v in enumerate(buf):
        if v == 0xFF:
            continue
        ts = _ms(start_dt + timedelta(minutes=i))
        rows.append({"ts": ts, "stress": v, "auto": 1})
    return rows


def parse_stress_manual(start_dt, buf):
    """5 bytes/sample: ts=u32 LE (s), stress=u8."""
    rows = []
    for i in range(len(buf) // 5):
        o = i * 5
        ts_s = struct.unpack_from("<I", buf, o)[0]
        rows.append({"ts": ts_s * 1000, "stress": buf[o + 4], "auto": 0})
    return rows


def parse_pai(start_dt, buf):
    """88-byte records: type(==5), ts=u32 LE, utcOffset=int8, 31 unk, 3 float, 3 int16, 2 float, 39 unk."""
    rows = []
    rec = 88
    for i in range(len(buf) // rec):
        o = i * rec
        if buf[o] != 5:
            continue
        ts_s = struct.unpack_from("<I", buf, o + 1)[0]
        pai_low, pai_mod, pai_high = struct.unpack_from("<fff", buf, o + 37)
        pai_today, pai_total = struct.unpack_from("<ff", buf, o + 55)
        rows.append({"ts": ts_s * 1000, "pai_low": pai_low, "pai_moderate": pai_mod,
                     "pai_high": pai_high, "pai_today": pai_today, "pai_total": pai_total})
    return rows


def _signed8(b):
    return b - 256 if b >= 128 else b


if __name__ == "__main__":
    # offline round-trip of the time bytes (minute precision)
    now = datetime.now().replace(second=0, microsecond=0)
    b = time_bytes(now)
    back = parse_time_bytes(b)
    assert (back.year, back.month, back.day, back.hour, back.minute) == \
           (now.year, now.month, now.day, now.hour, now.minute), (now, back, b.hex())
    print(f"time_bytes round-trip OK: {now} -> {b.hex()} -> {back}")
    # activity parser smoke test
    sd = parse_time_bytes(b)
    rows = parse_activity(sd, bytes([0, 50, 12, 72, 0, 0, 0, 0,
                                     0, 60, 0, 75, 0, 1, 1, 0]))
    print(f"parse_activity smoke: {rows}")
