"""Verify a password against a Pi-hole FTL BALLOON-SHA256 hash, on the controller.

Port of nettle's balloon_sha256 as FTL calls it (src/config/password.c):
s_cost=1024, t_cost=32, delta=3, 16-byte salt; PHC string
$BALLOON-SHA256$v=1$s=1024,t=32$<salt b64>$<hash b64>.
"""

import base64
import hashlib
import hmac
import struct

_S_COST = 1024  # FTL ignores the PHC's s=/t= and always uses these
_T_COST = 32
_DELTA = 3


def _h(cnt, a=b"", b=b""):
    return hashlib.sha256(struct.pack("<Q", cnt) + a + b).digest()


def _balloon_sha256(password, salt):
    buf = []
    cnt = 0
    buf.append(_h(cnt, password, salt))
    cnt += 1
    for i in range(1, _S_COST):
        buf.append(_h(cnt, buf[i - 1]))
        cnt += 1
    for i in range(_T_COST):
        for j in range(_S_COST):
            buf[j] = _h(cnt, buf[j - 1 if j else _S_COST - 1], buf[j])
            cnt += 1
            for k in range(_DELTA):
                block = hashlib.sha256(struct.pack("<QQQ", i, j, k)).digest()
                block = _h(cnt, salt, block)
                cnt += 1
                other = int.from_bytes(block, "little") % _S_COST
                buf[j] = _h(cnt, buf[j], buf[other])
                cnt += 1
    return buf[_S_COST - 1]


def ftl_password_matches(password, phc):
    """True if password verifies against an FTL BALLOON-SHA256 PHC string."""
    parts = str(phc).split("$")
    if len(parts) != 6 or parts[1] != "BALLOON-SHA256":
        return False
    salt = base64.b64decode(parts[4])
    want = base64.b64decode(parts[5])
    got = _balloon_sha256(str(password).encode(), salt)
    return hmac.compare_digest(got, want)


class FilterModule:
    def filters(self):
        return {"ftl_password_matches": ftl_password_matches}
