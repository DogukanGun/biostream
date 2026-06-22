"""
Huami-2021 / Zepp OS chunked transport codec — faithful Python port of Gadgetbridge's
Huami2021ChunkedEncoder.java + Huami2021ChunkedDecoder.java.

Pure byte logic (no BLE here). The client writes encode() chunks to char 0016 and feeds
notifications from char 0017 into decode().

Always uses the Zepp OS "extended flags" form (force2021Protocol = true).
AES-128-ECB with a per-message key = sessionKey XOR handle.
"""
import struct
import zlib

# AES-128-ECB (no padding) — prefer `cryptography`, fall back to pycryptodome.
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def aes_ecb_encrypt(data, key):
        e = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        return e.update(data) + e.finalize()

    def aes_ecb_decrypt(data, key):
        d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        return d.update(data) + d.finalize()
except ImportError:  # pragma: no cover
    from Crypto.Cipher import AES

    def aes_ecb_encrypt(data, key):
        return AES.new(key, AES.MODE_ECB).encrypt(data)

    def aes_ecb_decrypt(data, key):
        return AES.new(key, AES.MODE_ECB).decrypt(data)


class Chunked2021:
    """One per BLE connection. Holds encoder handle/seq and decoder reassembly state."""

    def __init__(self, mtu=23):
        self.mtu = mtu
        self.session_key = None          # 16 bytes once auth derives it
        self.encrypted_seq = 0           # seeded from ECDH shared secret during auth
        # encoder
        self._write_handle = 0
        # decoder reassembly
        self._cur_handle = None
        self._cur_type = 0
        self._cur_length = 0
        self._cur_encrypted = False
        self._reasm = bytearray()
        self.last_handle = 0
        self.last_count = 0

    # -- encoder: Huami2021ChunkedEncoder.write (extended_flags = True) --------
    def encode(self, type_, data, encrypt):
        """Return a list of chunk byte-strings to write to char 0016."""
        if encrypt and self.session_key is None:
            raise RuntimeError("can't encrypt without session key")

        self._write_handle = (self._write_handle + 1) & 0xFF
        handle = self._write_handle
        length = len(data)

        if encrypt:
            messagekey = bytes((self.session_key[i] ^ handle) & 0xFF for i in range(16))
            enc_len = length + 8
            overflow = enc_len % 16
            if overflow:
                enc_len += 16 - overflow
            buf = bytearray(enc_len)
            buf[0:length] = data
            struct.pack_into("<I", buf, length, self.encrypted_seq & 0xFFFFFFFF)
            self.encrypted_seq = (self.encrypted_seq + 1) & 0xFFFFFFFF
            crc = zlib.crc32(bytes(buf[0:length + 4])) & 0xFFFFFFFF
            struct.pack_into("<I", buf, length + 4, crc)
            data = aes_ecb_encrypt(bytes(buf), messagekey)
            remaining = enc_len
        else:
            remaining = length

        chunks = []
        count = 0
        header_size = 11  # extended first-chunk header
        offset = 0
        while remaining > 0:
            max_chunk = self.mtu - 3 - header_size
            copybytes = min(remaining, max_chunk)
            chunk = bytearray(copybytes + header_size)

            flags = 0
            if encrypt:
                flags |= 0x08
            if count == 0:
                flags |= 0x01
                struct.pack_into("<I", chunk, 5, length)   # plaintext length
                struct.pack_into("<H", chunk, 9, type_)    # endpoint/type
            if remaining <= max_chunk:
                flags |= 0x06  # last: last(0x02) | needs-ack(0x04)

            chunk[0] = 0x03
            chunk[1] = flags
            chunk[2] = 0
            chunk[3] = handle
            chunk[4] = count
            chunk[header_size:] = data[offset:offset + copybytes]

            chunks.append(bytes(chunk))
            remaining -= copybytes
            offset += copybytes
            header_size = 5  # extended continuation header
            count += 1
        return chunks

    # -- decoder: Huami2021ChunkedDecoder.decode ------------------------------
    def decode(self, data):
        """Feed one notification. Returns (needs_ack, handle, count, message),
        where message is (type, payload) once a full message reassembles, else None.
        Returns (False, None, None, None) for a non-chunked frame (e.g. an 0x04 ack)."""
        i = 0
        if data[i] != 0x03:
            return (False, None, None, None)
        i += 1
        flags = data[i]; i += 1
        encrypted = bool(flags & 0x08)
        first = bool(flags & 0x01)
        last = bool(flags & 0x02)
        needs_ack = bool(flags & 0x04)

        i += 1  # force2021: skip extended-header pad byte
        handle = data[i]; i += 1
        if self._cur_handle is not None and self._cur_handle != handle:
            return (False, handle, None, None)  # unexpected handle, ignore
        self.last_handle = handle
        count = data[i]; i += 1
        self.last_count = count

        if first:
            full_length = struct.unpack_from("<I", data, i)[0]; i += 4
            self._cur_length = full_length
            self._cur_encrypted = encrypted
            self._cur_type = struct.unpack_from("<H", data, i)[0]; i += 2
            self._cur_handle = handle
            self._reasm = bytearray()

        self._reasm += data[i:]

        message = None
        if last:
            buf = bytes(self._reasm)
            if self._cur_encrypted:
                if self.session_key is None:
                    self._cur_handle = None
                    return (needs_ack, handle, count, None)
                messagekey = bytes((self.session_key[j] ^ handle) & 0xFF for j in range(16))
                buf = aes_ecb_decrypt(buf, messagekey)[:self._cur_length]
            message = (self._cur_type, buf)
            self._cur_handle = None
            self._cur_type = 0
        return (needs_ack, handle, count, message)


if __name__ == "__main__":
    import os

    def roundtrip(msg_type, payload, encrypt, mtu):
        enc = Chunked2021(mtu=mtu)
        dec = Chunked2021(mtu=mtu)
        if encrypt:
            key = os.urandom(16)
            enc.session_key = key
            enc.encrypted_seq = 0x11223344
            dec.session_key = key
        out = None
        for c in enc.encode(msg_type, payload, encrypt):
            _, _, _, message = dec.decode(c)
            if message is not None:
                out = message
        assert out is not None, "nothing reassembled"
        t, p = out
        assert t == msg_type, f"type 0x{t:04x} != 0x{msg_type:04x}"
        assert p == payload, "payload mismatch"

    def nchunks(msg_type, payload, encrypt, mtu):
        c = Chunked2021(mtu=mtu)
        if encrypt:
            c.session_key = os.urandom(16)
        return len(c.encode(msg_type, payload, encrypt))

    roundtrip(0x0082, bytes(range(52)), False, 23)
    roundtrip(0x001a, b"\x03", False, 23)
    roundtrip(0x0082, bytes(range(52)), True, 23)
    roundtrip(0x0011, os.urandom(200), True, 23)
    roundtrip(0x0011, os.urandom(200), False, 247)
    print("chunked round-trips PASSED:")
    print(f"  52B plaintext  @mtu23  -> {nchunks(0x0082, bytes(52), False, 23)} chunks")
    print(f"  1B  plaintext  @mtu23  -> {nchunks(0x001a, b'x', False, 23)} chunk")
    print(f"  52B encrypted  @mtu23  -> {nchunks(0x0082, bytes(52), True, 23)} chunks")
    print(f"  200B encrypted @mtu23  -> {nchunks(0x0011, bytes(200), True, 23)} chunks")
    print(f"  200B plaintext @mtu247 -> {nchunks(0x0011, bytes(200), False, 247)} chunk(s)")
