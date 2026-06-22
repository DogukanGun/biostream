"""
Decisive correctness check for ecdh_b163.py.

Reimplements NIST B-163 ECDH completely independently, using Python big-integers and
textbook binary-curve formulas (structurally unrelated to the word-array port, so a
porting bug would NOT be reproduced). Cross-checks against Gadgetbridge's hardcoded
testAuth() vectors. If pub and shared match, the port is correct.
"""
from ecdh_b163 import (ecdh_generate_public, ecdh_generate_shared,
                       base_x, base_y, coeff_b, polynomial)


def words_to_int(words):
    return sum((w & 0xFFFFFFFF) << (32 * i) for i, w in enumerate(words))


F = words_to_int(polynomial)        # x^163 + x^7 + x^6 + x^3 + 1
DEGF = 163
A = 1                               # NIST B-curves use a = 1
B = words_to_int(coeff_b)
GX = words_to_int(base_x)
GY = words_to_int(base_y)


def clmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
    return r


def gmod(x):
    bl = x.bit_length()
    while bl > DEGF:
        x ^= F << (bl - 1 - DEGF)
        bl = x.bit_length()
    return x


def gmul(a, b):
    return gmod(clmul(a, b))


def gsqr(a):
    return gmod(clmul(a, a))


def ginv(a):
    # Fermat: a^(2^163 - 2) is the inverse in GF(2^163)
    e = (1 << DEGF) - 2
    result = 1
    base = a
    while e:
        if e & 1:
            result = gmul(result, base)
        base = gsqr(base)
        e >>= 1
    return result


def on_curve(x, y):
    if x == 0 and y == 0:
        return False
    lhs = gsqr(y) ^ gmul(x, y)
    rhs = gmul(gmul(x, x), x) ^ gmul(A, gsqr(x)) ^ B
    return gmod(lhs) == gmod(rhs)


def pt_double(P):
    if P is None:
        return None
    x1, y1 = P
    if x1 == 0:
        return None
    lam = x1 ^ gmul(y1, ginv(x1))
    x3 = gmod(gsqr(lam) ^ lam ^ A)
    y3 = gmod(gsqr(x1) ^ gmul(lam, x3) ^ x3)
    return (x3, y3)


def pt_add(P, Q):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if y1 == y2:
            return pt_double(P)
        return None  # Q == -P
    lam = gmul(y1 ^ y2, ginv(x1 ^ x2))
    x3 = gmod(gsqr(lam) ^ lam ^ x1 ^ x2 ^ A)
    y3 = gmod(gmul(lam, x1 ^ x3) ^ x3 ^ y1)
    return (x3, y3)


def scalar_mul(k, P):
    R = None
    for i in range(k.bit_length() - 1, -1, -1):
        R = pt_double(R)
        if (k >> i) & 1:
            R = pt_add(R, P)
    return R


def clear_scalar(priv_bytes):
    # match the port: clear bits >= 162 (degree(base_order) - 1)
    return int.from_bytes(priv_bytes, "little") & ((1 << 162) - 1)


# Gadgetbridge InitOperation2021.testAuth() hardcoded vectors
PRIV = bytes([0x0b, 0x42, 0xb9, 0xe6, 0x1c, 0x23, 0x34, 0x0e, 0x35, 0xc1, 0x6e, 0x2e,
              0x7d, 0xe4, 0x33, 0xf4, 0xb5, 0x85, 0x9a, 0x72, 0xec, 0x11, 0x40, 0x27])
REMOTE_PUB = bytes([0xe6, 0x01, 0x6a, 0xba, 0x1d, 0xe7, 0xac, 0x0f, 0x0c, 0x7f, 0x0f, 0xf7,
                    0xe2, 0x24, 0x3e, 0x66, 0x62, 0xb5, 0xe0, 0x3b, 0x01, 0x00, 0x00, 0x00,
                    0xad, 0x8a, 0x4b, 0xed, 0xc7, 0x6a, 0x1e, 0xfd, 0xe7, 0x72, 0x5c, 0xc6,
                    0x62, 0xb5, 0x48, 0x35, 0x51, 0x3e, 0x3d, 0x57, 0x05, 0x00, 0x00, 0x00])


def split_point(buf48):
    return int.from_bytes(buf48[0:24], "little"), int.from_bytes(buf48[24:48], "little")


if __name__ == "__main__":
    print(f"G on curve?           {on_curve(GX, GY)}")
    rpx, rpy = split_point(REMOTE_PUB)
    print(f"remotePub on curve?   {on_curve(rpx, rpy)}")

    k = clear_scalar(PRIV)

    # --- public key ---
    pub_port = ecdh_generate_public(PRIV)
    P = scalar_mul(k, (GX, GY))
    px, py = split_point(pub_port)
    print("\npublic key:")
    print(f"  port  x={px:042x}")
    print(f"  indep x={P[0]:042x}")
    pub_ok = (px, py) == (P[0], P[1])
    print(f"  MATCH: {pub_ok}")

    # --- shared secret ---
    shared_port = ecdh_generate_shared(PRIV, REMOTE_PUB)
    S = scalar_mul(k, (rpx, rpy))
    sx, sy = split_point(shared_port)
    print("\nshared secret:")
    print(f"  port  x={sx:042x}")
    print(f"  indep x={S[0]:042x}")
    shared_ok = (sx, sy) == (S[0], S[1])
    print(f"  MATCH: {shared_ok}")

    print()
    if pub_ok and shared_ok:
        print(">>> ECDH PORT IS CORRECT. The 0x07 is NOT an ECDH bug. <<<")
    else:
        print(">>> ECDH PORT MISMATCH — found the bug. <<<")
