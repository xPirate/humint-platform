#!/usr/bin/env python3
"""The duress PIN: stored only as a slow, salted hash.

    humint-duress.py set      PIN on stdin; replaces any earlier one
    humint-duress.py check    PIN on stdin; exit 0 if it is the duress PIN
    humint-duress.py clear    remove it
    humint-duress.py status   exit 0 if one is set

The file holds scrypt parameters, a random salt and the hash — never the PIN.
It sits on the unencrypted root (it has to be checked before the store is
open), so the hash is deliberately expensive: guessing a 4-digit duress PIN
from a stolen card is possible in principle, which is why the duress PIN
should not be guessable from the real one, and why knowing it only lets
somebody destroy the case file, never read it.

Standard library only.
"""
import hashlib
import hmac
import os
import sys

FILE = os.environ.get("HUMINT_DURESS_FILE", "/var/lib/humint/duress")
N, R, P = 2 ** 15, 8, 1


def _hash(pin: str, salt: bytes, n=N, r=R, p=P) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def read_pin() -> str:
    pin = sys.stdin.readline().rstrip("\n")
    if not pin:
        sys.exit(2)
    return pin


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "set":
        pin = read_pin()
        salt = os.urandom(16)
        line = f"scrypt${N}${R}${P}${salt.hex()}${_hash(pin, salt).hex()}\n"
        tmp = FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(line)
        os.replace(tmp, FILE)
        return 0
    if cmd == "check":
        pin = read_pin()
        try:
            kind, n, r, p, salt, digest = open(FILE).read().strip().split("$")
        except (OSError, ValueError):
            return 1
        if kind != "scrypt":
            return 1
        got = _hash(pin, bytes.fromhex(salt), int(n), int(r), int(p))
        return 0 if hmac.compare_digest(got, bytes.fromhex(digest)) else 1
    if cmd == "clear":
        try:
            os.unlink(FILE)
        except FileNotFoundError:
            pass
        return 0
    if cmd == "status":
        return 0 if os.path.exists(FILE) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
