"""Joining a Wi-Fi from the box (humint-ctl net client): a name and password a
person typed reach the settings file — which root sources — exactly as
typed, and never as anything that runs; bad ones are refused; the file stays
private."""
import os
import re
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, finish  # noqa: E402

OPT = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint")
CTL = open(os.path.join(OPT, "bin/humint-ctl")).read()
cmd_net = re.search(r"^cmd_net\(\) \{.*?^\}", CTL, re.S | re.M).group(0)

tmp = tempfile.mkdtemp()
env_file = os.path.join(tmp, "env")
applied = os.path.join(tmp, "applied")
cmd_net = cmd_net.replace("/opt/humint/bin/humint-net.sh deploy", f'echo applied >> "{applied}"')
cmd_net = cmd_net.replace("/run/humint/net-fallback", f"{tmp}/net-fallback")


def net(*args, stdin=None, env_extra=None):
    with open(env_file, "w") as f:
        f.write('HOSTNAME="humint"\nNET_MODE="hotspot"\nAP_SSID="humint-field"\nAP_PSK="abcd-efgh"\nCLIENT_SSID=""\nCLIENT_PSK=""\n')
    os.chmod(env_file, 0o600)
    try:
        os.unlink(applied)
    except OSError:
        pass
    script = f""". {OPT}/lib/humint-common.sh
HUMINT_ENV={env_file}
need_root() {{ :; }}
{cmd_net}
cmd_net "$@"
"""
    return subprocess.run(["bash", "-c", script, "net", *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env_extra or {})}, cwd=tmp)


def loaded():
    """What root sees when it sources the file (as humint-net.sh does)."""
    r = subprocess.run(["bash", "-c", f'set -a; . "{env_file}"; printf "%s\\0%s\\0%s" "$NET_MODE" "$CLIENT_SSID" "$CLIENT_PSK"'],
                       capture_output=True, text=True, cwd=tmp)
    return r.stdout.split("\0")


nasty = "J's $(touch PWNED)`id`\"p\"\\x"   # 27 bytes: within Wi-Fi's 32
r = net("client", nasty, "pa$$ 'w' ord")
check(r.returncode == 0, f"a name with quotes, $ and backticks is accepted ({r.stderr.strip()})")
check(loaded() == ["client", nasty, "pa$$ 'w' ord"], "and reads back exactly as typed")
check(not os.path.exists(os.path.join(tmp, "PWNED")), "nothing in it ever runs")
check(stat.S_IMODE(os.stat(env_file).st_mode) == 0o600, "the settings file stays private (it holds passwords)")
check(os.path.exists(applied), "the network is switched")

r = net("client", "Field Office", stdin="from stdin pw\n", env_extra={"HUMINT_PSK_STDIN": "1"})
check(r.returncode == 0 and loaded()[1:] == ["Field Office", "from stdin pw"],
      "the password can come on stdin (off the command line)")
r = net("client", "Open Cafe")
check(r.returncode == 0 and loaded() == ["client", "Open Cafe", ""], "an open network has no password")

for args, why in ((["client", ""], "no name"), (["client", "x" * 33], "a name over 32 bytes"),
                  (["client", "ok", "short"], "a password under 8"), (["client", "ok", "x" * 65], "one over 64"),
                  (["client", "a\nNET_MODE=evil", "password1"], "a line break"), (["client", "ok", "pass\tword"], "a tab in the password")):
    r = net(*args)
    check(r.returncode != 0 and loaded()[0] == "hotspot" and not os.path.exists(applied),
          f"refused, nothing changed: {why}")

r = net("wired")
check(r.returncode == 0 and loaded()[0] == "wired" and stat.S_IMODE(os.stat(env_file).st_mode) == 0o600,
      "switching mode keeps the file private too")

# The helper reads the same quoting back (what the screen shows).
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("boxd", os.path.join(ROOT, "deploy/x86/files/opt/humint/bin/humint-boxd.py"))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
net("client", nasty, "password1")
e = B.read_env(env_file)
check(e["CLIENT_SSID"] == nasty and e["AP_PSK"] == "abcd-efgh" and e["HOSTNAME"] == "humint",
      "the root helper reads the quoted name back exactly, and the plain values as before")
finish()
