"""
Zepp key-fetcher — obtain the 16-byte strap auth key by logging into Zepp/Amazfit servers.
Wraps the `huami-token` package (a dependency). The key is bound to the device at pairing and
lives in the account; this fetches it. Unpairing in the Zepp app invalidates it.
"""
import re
import shutil
import subprocess
import sys


def fetch_zepp_key(email, password, method="amazfit"):
    """Log into Zepp/Amazfit and return the strap's 16-byte auth key (bytes).

    `method` is "amazfit" (Zepp app) or "xiaomi" (Mi Fitness). Raises RuntimeError on failure.
    """
    cmd = (["huami-token"] if shutil.which("huami-token")
           else [sys.executable, "-m", "huami_token"])
    try:
        proc = subprocess.run(
            cmd + ["--method", method, "--email", email, "--password", password, "--bt_keys"],
            capture_output=True, text=True, timeout=90,
        )
    except FileNotFoundError:
        raise RuntimeError("huami-token not available (pip install huami-token)")
    m = (re.search(r"Key:\s*0x([0-9A-Fa-f]{32})", proc.stdout or "")
         or re.search(r"Key:\s*0x([0-9A-Fa-f]{32})", proc.stderr or ""))
    if not m:
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
        raise RuntimeError("could not fetch the Zepp auth key — check email/password/region "
                           "and that the strap is paired in the app.\n" + tail)
    return bytes.fromhex(m.group(1))
