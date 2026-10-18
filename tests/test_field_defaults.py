"""A field server boots with no config file: what nobody wrote down is filled in."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, finish  # noqa: E402

LIB = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint/lib/humint-common.sh")


def resolve(prelude):
    r = subprocess.run(["bash", "-c", f". {LIB}\nload_config /nonexistent\n{prelude}\nresolve_open_settings\n"
                        'echo "$TIMEZONE|$WIFI_COUNTRY|$AP_PSK|$AP_PSK_GENERATED"'],
                       capture_output=True, text=True)
    return r.stdout.strip().split("|")


tz, country, psk, gen = resolve("TIMEZONE=America/Chicago")
check(country == "US", f"the Wi-Fi country comes from the time zone ({country})")
check(gen == "1" and len(psk) == 14 and psk.count("-") == 2 and not set(psk) & set("01ilo"),
      f"a hotspot password is made up, readable off a screen ({psk})")
check(resolve("TIMEZONE=Europe/Berlin")[1] == "DE", "Europe/Berlin is DE")
check(resolve("TIMEZONE=UTC")[1] == "", "UTC has no country, so first boot stops and says to set WIFI_COUNTRY")
tz, country, psk, gen = resolve("TIMEZONE=Europe/London; WIFI_COUNTRY=IE; AP_PSK=our-own-pass")
check((country, psk, gen) == ("IE", "our-own-pass", "0"), "anything set in the file is kept")
check(resolve("TIMEZONE=Europe/London; AP_PSK=changeme-now")[3] == "1",
      "the old example's placeholder password is replaced, not deployed")

env = os.path.join(tempfile.mkdtemp(), "env")
open(env, "w").write('HOSTNAME=humint\nWIFI_COUNTRY=\nAP_PSK=\n')
subprocess.run(["bash", "-c", f'. {LIB}; set_env_value {env} WIFI_COUNTRY US; '
                f'set_env_value {env} AP_PSK abcd-efgh-jkmn; set_env_value {env} TIMEZONE America/Chicago'],
               check=True)
lines = open(env).read().splitlines()
check(lines == ['HOSTNAME=humint', 'WIFI_COUNTRY="US"', 'AP_PSK="abcd-efgh-jkmn"', 'TIMEZONE="America/Chicago"'],
      f"the decided values are written back for later boots ({lines})")
finish()
