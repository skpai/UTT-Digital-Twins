"""
See a solution once the instructor opens it.

    python unlock.py                  list what can be unlocked, and from when
    python unlock.py 1a               show the solution of TODO(1a) (asks for the password)
    python unlock.py 1a --apply       ...and put it into the code, in place of the gap
    python unlock.py 1 --apply        every TODO of Step 1 at once
    python unlock.py app.py           a whole file: it is saved to revealed/app.py

A solution opens only when BOTH are true: the password is right (the instructor writes it on
the board) and the local time has passed its unlock time.
Standard library only.
"""
import base64
import datetime as dt
import getpass
import hashlib
import hmac
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
LOCKED = HERE / "solutions.lock"
REVEALED = HERE / "revealed"


# ---------------------------------------------------------------- sealing (used by make_starter.py)

def _key(password: str, name: str, when: str) -> bytes:
    # the unlock time is part of the key: editing it in solutions.lock breaks the lock
    salt = f"{name}|{when}".encode()
    return hashlib.pbkdf2_hmac("sha256", password.strip().lower().encode(), salt, 200_000)


def _xor(key: bytes, data: bytes) -> bytes:
    stream = b"".join(hashlib.sha256(key + i.to_bytes(4, "big")).digest()
                      for i in range(len(data) // 32 + 1))
    return bytes(a ^ b for a, b in zip(data, stream))


def seal(password: str, name: str, when: str, text: str, **info) -> dict:
    key = _key(password, name, when)
    data = _xor(key, text.encode("utf-8"))
    mac = hmac.new(key, data, hashlib.sha256).hexdigest()
    return {"at": when, **info, "mac": mac, "data": base64.b64encode(data).decode()}


def _open(password: str, name: str, item: dict) -> str | None:
    key = _key(password, name, item["at"])
    data = base64.b64decode(item["data"])
    if not hmac.compare_digest(hmac.new(key, data, hashlib.sha256).hexdigest(), item["mac"]):
        return None
    return _xor(key, data).decode("utf-8")


# ---------------------------------------------------------------- unlocking (students)

def _opens_at(when: str) -> dt.datetime:
    """'2026-11-26 15:30' or '15:30' (today)."""
    if " " in when:
        return dt.datetime.strptime(when, "%Y-%m-%d %H:%M")
    return dt.datetime.combine(dt.date.today(), dt.datetime.strptime(when, "%H:%M").time())


def _apply(name: str, item: dict, code: str) -> None:
    if "file" not in item:                      # a whole file
        REVEALED.mkdir(exist_ok=True)
        (REVEALED / name).write_text(code, encoding="utf-8")
        print(f"  saved to revealed/{name}")
        return
    path = HERE / item["file"]
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if line.strip() == item["stub"]]
    if len(hits) != 1:
        print(f"  could not find the gap of TODO({name}) in {item['file']} (did you change it?)."
              " Copy the code above by hand.")
        return
    i = hits[0]
    lines[i:i + 1] = code.rstrip("\n").splitlines()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  put into {item['file']}, line {i + 1}")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(errors="replace")    # Windows consoles cannot print every character
    if not LOCKED.exists():
        print("No solutions.lock here: nothing to unlock.")
        return 1
    items = json.loads(LOCKED.read_text(encoding="utf-8"))
    args = [a for a in argv if not a.startswith("--")]
    apply = "--apply" in argv
    now = dt.datetime.now()

    if not args:
        print(f"Now: {now:%H:%M}\n")
        for name, item in items.items():
            what = f"TODO({name}) in {item['file']}" if "file" in item else name
            state = "open with the password" if now >= _opens_at(item["at"]) else "locked"
            print(f"  {name:<16} {what:<26} from {item['at']:<17} {state}")
        print("\npython unlock.py <name> [--apply]")
        return 0

    want = args[0]
    names = [n for n in items if n == want or ("file" in items[n] and n.startswith(want))]
    if not names:
        print(f"Nothing called {want!r}. Run `python unlock.py` to see the list.")
        return 1
    ready = [n for n in names if now >= _opens_at(items[n]["at"])]
    for n in names:
        if n not in ready:
            print(f"{n}: still locked, opens at {items[n]['at']} (now {now:%H:%M}).")
    if not ready:
        return 1

    password = args[1] if len(args) > 1 else getpass.getpass("Password: ")
    for n in ready:
        code = _open(password, n, items[n])
        if code is None:
            print("Wrong password.")
            return 1
        print(f"\n===== {n} " + "=" * 40)
        if "file" not in items[n]:              # a whole file: save it, do not flood the terminal
            _apply(n, items[n], code)
            continue
        print(code.rstrip("\n"))
        if apply:
            _apply(n, items[n], code)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
