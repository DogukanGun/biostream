"""
Pure-Python port of Gadgetbridge's ECDH_B163.java (NIST B-163 binary-field ECDH),
which is itself a port of tiny-ECDH-c. Ported faithfully (ugly on purpose) to match
byte-for-byte so the Huami-2021 auth handshake interoperates with the real device.

Layout (matches the Java):
  private key : 24 bytes
  public key  : 48 bytes  = x || y, each 24 bytes, little-endian 32-bit words
  shared      : 48 bytes  = point (x || y); the handshake uses the x-coordinate.

Field elements are arrays of BITVEC_NWORDS (6) 32-bit words, word 0 = least significant.
All word values are kept in [0, 2**32).
"""
import os

CURVE_DEGREE = 163
ECC_PRV_KEY_SIZE = 24
ECC_PUB_KEY_SIZE = 2 * ECC_PRV_KEY_SIZE          # 48
BITVEC_MARGIN = 3
BITVEC_NBITS = CURVE_DEGREE + BITVEC_MARGIN       # 166
BITVEC_NWORDS = (BITVEC_NBITS + 31) // 32         # 6
BITVEC_NBYTES = 4 * BITVEC_NWORDS                 # 24
MASK32 = 0xFFFFFFFF

# NIST B-163 curve parameters (little-endian words, exactly as in the Java)
polynomial = [0x000000c9, 0x00000000, 0x00000000, 0x00000000, 0x00000000, 0x00000008]
coeff_b    = [0x4a3205fd, 0x512f7874, 0x1481eb10, 0xb8c953ca, 0x0a601907, 0x00000002]
base_x     = [0xe8343e36, 0xd4994637, 0xa0991168, 0x86a2d57e, 0xf0eba162, 0x00000003]
base_y     = [0x797324f1, 0xb11c5c0c, 0xa2cdd545, 0x71a0094f, 0xd51fbc6c, 0x00000000]
base_order = [0xa4234c33, 0x77e70c12, 0x000292fe, 0x00000000, 0x00000000, 0x00000004]


def _new():
    return [0] * BITVEC_NWORDS


# ---- bit-vector helpers ----------------------------------------------------
def bitvec_get_bit(x, idx):
    return (x[idx // 32] >> (idx & 31)) & 1

def bitvec_clr_bit(x, idx):
    x[idx // 32] &= (~(1 << (idx & 31))) & MASK32

def bitvec_copy(x, y):
    for i in range(BITVEC_NWORDS):
        x[i] = y[i]

def bitvec_swap(x, y):
    tmp = list(x)
    for i in range(BITVEC_NWORDS):
        x[i] = y[i]
        y[i] = tmp[i]

def bitvec_equal(x, y):
    for i in range(BITVEC_NWORDS):
        if x[i] != y[i]:
            return False
    return True

def bitvec_set_zero(x):
    for i in range(BITVEC_NWORDS):
        x[i] = 0

def bitvec_is_zero(x):
    i = 0
    while i < BITVEC_NWORDS:
        if x[i] != 0:
            break
        i += 1
    return i == BITVEC_NWORDS

def bitvec_degree(x):
    i = BITVEC_NWORDS * 32
    y = BITVEC_NWORDS
    while i > 0:
        y -= 1
        if x[y] == 0:
            i -= 32
        else:
            break
    if i != 0:
        u32mask = 1 << 31
        while (x[y] & u32mask) == 0:
            u32mask >>= 1
            i -= 1
    return i

def bitvec_lshift(x, y, nbits):
    nwords = nbits // 32
    i = 0
    while i < nwords:
        x[i] = 0
        i += 1
    j = 0
    while i < BITVEC_NWORDS:
        x[i] = y[j]
        i += 1
        j += 1
    nbits &= 31
    if nbits != 0:
        for i in range(BITVEC_NWORDS - 1, 0, -1):
            x[i] = ((x[i] << nbits) | (x[i - 1] >> (32 - nbits))) & MASK32
        x[0] = (x[0] << nbits) & MASK32


# ---- GF(2^163) field arithmetic --------------------------------------------
def gf2field_set_one(x):
    x[0] = 1
    for i in range(1, BITVEC_NWORDS):
        x[i] = 0

def gf2field_is_one(x):
    if x[0] != 1:
        return False
    for i in range(1, BITVEC_NWORDS):
        if x[i] != 0:
            return False
    return True

def gf2field_add(z, x, y):
    for i in range(BITVEC_NWORDS):
        z[i] = x[i] ^ y[i]

def gf2field_inc(x):
    x[0] ^= 1

def gf2field_mul(z, x, y):
    tmp = list(x)
    if bitvec_get_bit(y, 0) != 0:
        for i in range(BITVEC_NWORDS):
            z[i] = x[i]
    else:
        bitvec_set_zero(z)
    for i in range(1, CURVE_DEGREE):
        bitvec_lshift(tmp, tmp, 1)
        if bitvec_get_bit(tmp, CURVE_DEGREE) != 0:
            gf2field_add(tmp, tmp, polynomial)
        if bitvec_get_bit(y, i) != 0:
            gf2field_add(z, z, tmp)

def gf2field_inv(z, x):
    u = _new(); v = _new(); g = _new(); h = _new()
    bitvec_copy(u, x)
    bitvec_copy(v, polynomial)
    bitvec_set_zero(g)
    gf2field_set_one(z)
    while not gf2field_is_one(u):
        i = bitvec_degree(u) - bitvec_degree(v)
        if i < 0:
            bitvec_swap(u, v)
            bitvec_swap(g, z)
            i = -i
        bitvec_lshift(h, v, i)
        gf2field_add(u, u, h)
        bitvec_lshift(h, g, i)
        gf2field_add(z, z, h)


# ---- elliptic curve point arithmetic ---------------------------------------
def gf2point_copy(x1, y1, x2, y2):
    bitvec_copy(x1, x2)
    bitvec_copy(y1, y2)

def gf2point_set_zero(x, y):
    bitvec_set_zero(x)
    bitvec_set_zero(y)

def gf2point_is_zero(x, y):
    return bitvec_is_zero(x) and bitvec_is_zero(y)

def gf2point_double(x, y):
    if bitvec_is_zero(x):
        bitvec_set_zero(y)
    else:
        l = _new()
        gf2field_inv(l, x)
        gf2field_mul(l, l, y)
        gf2field_add(l, l, x)
        gf2field_mul(y, x, x)
        gf2field_mul(x, l, l)
        gf2field_inc(l)
        gf2field_add(x, x, l)
        gf2field_mul(l, l, x)
        gf2field_add(y, y, l)

def gf2point_add(x1, y1, x2, y2):
    if not gf2point_is_zero(x2, y2):
        if gf2point_is_zero(x1, y1):
            gf2point_copy(x1, y1, x2, y2)
        else:
            if bitvec_equal(x1, x2):
                if bitvec_equal(y1, y2):
                    gf2point_double(x1, y1)
                else:
                    gf2point_set_zero(x1, y1)
            else:
                a = _new(); b = _new(); c = _new(); d = _new()
                gf2field_add(a, y1, y2)
                gf2field_add(b, x1, x2)
                gf2field_inv(c, b)
                gf2field_mul(c, c, a)
                gf2field_mul(d, c, c)
                gf2field_add(d, d, c)
                gf2field_add(d, d, b)
                gf2field_inc(d)
                gf2field_add(x1, x1, d)
                gf2field_mul(a, x1, c)
                gf2field_add(a, a, d)
                gf2field_add(y1, y1, a)
                bitvec_copy(x1, d)

def gf2point_mul(x, y, exp):
    tmpx = _new(); tmpy = _new()
    nbits = bitvec_degree(exp)
    gf2point_set_zero(tmpx, tmpy)
    for i in range(nbits - 1, -1, -1):
        gf2point_double(tmpx, tmpy)
        if bitvec_get_bit(exp, i) != 0:
            gf2point_add(tmpx, tmpy, x, y)
    gf2point_copy(x, y, tmpx, tmpy)

def gf2point_on_curve(x, y):
    a = _new(); b = _new()
    if gf2point_is_zero(x, y):
        return False
    gf2field_mul(a, x, x)
    gf2field_mul(b, a, x)
    gf2field_add(a, a, b)
    gf2field_add(a, a, coeff_b)
    gf2field_mul(b, y, y)
    gf2field_add(a, a, b)
    gf2field_mul(b, x, y)
    return bitvec_equal(a, b)


# ---- byte<->int conversion (little-endian words) ---------------------------
def bytes_to_int(data, offset):
    value = _new()
    p = offset
    for i in range(BITVEC_NWORDS):
        value[i] = (data[p] | (data[p + 1] << 8) | (data[p + 2] << 16) | (data[p + 3] << 24)) & MASK32
        p += 4
    return value

def ints_to_bytes(buf, ints, offset):
    p = offset
    for i in range(BITVEC_NWORDS):
        buf[p] = ints[i] & 0xFF
        buf[p + 1] = (ints[i] >> 8) & 0xFF
        buf[p + 2] = (ints[i] >> 16) & 0xFF
        buf[p + 3] = (ints[i] >> 24) & 0xFF
        p += 4


# ---- ECDH ------------------------------------------------------------------
def ecdh_generate_keys(public_key, private_key):
    priv = bytes_to_int(private_key, 0)
    pub1 = bytes_to_int(public_key, 0)
    pub2 = bytes_to_int(public_key, BITVEC_NBYTES)
    gf2point_copy(pub1, pub2, base_x, base_y)
    if bitvec_degree(priv) < (CURVE_DEGREE // 2):
        return False
    nbits = bitvec_degree(base_order)
    for i in range(nbits - 1, BITVEC_NWORDS * 32):
        bitvec_clr_bit(priv, i)
    gf2point_mul(pub1, pub2, priv)
    ints_to_bytes(public_key, pub1, 0)
    ints_to_bytes(public_key, pub2, BITVEC_NBYTES)
    return True

def ecdh_shared_secret(private_key, others_pub, output):
    priv = bytes_to_int(private_key, 0)
    op1 = bytes_to_int(others_pub, 0)
    op2 = bytes_to_int(others_pub, BITVEC_NBYTES)
    if (not gf2point_is_zero(op1, op2)) and gf2point_on_curve(op1, op2):
        for i in range(BITVEC_NBYTES * 2):
            output[i] = others_pub[i]
        nbits = bitvec_degree(base_order)
        for i in range(nbits - 1, BITVEC_NWORDS * 32):
            bitvec_clr_bit(priv, i)
        out1 = bytes_to_int(output, 0)
        out2 = bytes_to_int(output, BITVEC_NBYTES)
        gf2point_mul(out1, out2, priv)
        ints_to_bytes(output, out1, 0)
        ints_to_bytes(output, out2, BITVEC_NBYTES)
        return True
    return False


# ---- public API (mirrors the Java wrappers) --------------------------------
def ecdh_generate_public(private_ec):
    pub = bytearray(ECC_PUB_KEY_SIZE)
    if ecdh_generate_keys(pub, private_ec):
        return bytes(pub)
    return None

def ecdh_generate_shared(private_ec, remote_public_ec):
    shared = bytearray(ECC_PUB_KEY_SIZE)
    if ecdh_shared_secret(private_ec, remote_public_ec, shared):
        return bytes(shared)
    return None


if __name__ == "__main__":
    import time
    TRIALS = 2
    t0 = time.time()
    for trial in range(TRIALS):
        priv_a = os.urandom(24)
        priv_b = os.urandom(24)
        pub_a = ecdh_generate_public(priv_a)
        pub_b = ecdh_generate_public(priv_b)
        assert pub_a and pub_b, "key generation failed"
        # both public keys must satisfy the curve equation
        ax, ay = bytes_to_int(pub_a, 0), bytes_to_int(pub_a, 24)
        bx, by = bytes_to_int(pub_b, 0), bytes_to_int(pub_b, 24)
        assert gf2point_on_curve(ax, ay), "pub_a not on curve"
        assert gf2point_on_curve(bx, by), "pub_b not on curve"
        # the ECDH property: a*B == b*A
        shared_a = ecdh_generate_shared(priv_a, pub_b)
        shared_b = ecdh_generate_shared(priv_b, pub_a)
        assert shared_a == shared_b, "ECDH shared-secret mismatch!"
        print(f"  trial {trial+1}: on-curve OK, shared secrets agree "
              f"(x={shared_a[:8].hex()}...)")
    dt = time.time() - t0
    print(f"ECDH B-163 self-consistency PASSED ({TRIALS} trials, {dt:.1f}s, "
          f"~{dt/(TRIALS*2):.1f}s per point-mul)")
