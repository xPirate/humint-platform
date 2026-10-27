"""Signed updates for the field server: only the builder's bundles, only
newer ones, and anything that goes wrong is put back."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, ok  # noqa: E402

OPT = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint")
tmp = tempfile.mkdtemp()
R = os.path.join(tmp, "box")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- keys, and two bundles ------------------------------------------------------
key, other = os.path.join(tmp, "builder.key"), os.path.join(tmp, "stranger.key")
for k in (key, other):
    run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", k], check=True)
out = os.path.join(tmp, "out")
os.makedirs(out)
r = run([os.path.join(ROOT, "deploy/pi/make-update.sh"), "--key", key, "--out", out])
check(r.returncode == 0, f"make-update.sh builds a bundle ({r.stderr[-300:]})")
bundle = os.path.join(out, sorted(os.listdir(out))[0])
manifest = json.loads(tarfile.open(bundle).extractfile("manifest.json").read())
check(manifest["build"] > 0 and "migrate-v1.13-hardening.sql" in manifest["migrations"],
      "its manifest names the build and the migrations it carries")
foreign_dir = os.path.join(tmp, "foreign")
os.makedirs(foreign_dir)
run([os.path.join(ROOT, "deploy/pi/make-update.sh"), "--key", other, "--out", foreign_dir], check=True)
foreign = os.path.join(foreign_dir, os.listdir(foreign_dir)[0])

# ---- a box ---------------------------------------------------------------------------
def make_box(build=1, req=None):
    shutil.rmtree(R, ignore_errors=True)
    for d in ("opt/humint-platform/api", "opt/humint/bin", "opt/humint/venv/bin", "etc/systemd/system",
              "var/lib/humint", "srv/humint-data", "run/humint"):
        os.makedirs(os.path.join(R, d), exist_ok=True)
    open(os.path.join(R, "opt/humint-platform/api/OLD_VERSION_MARKER"), "w").write("v1")
    json.dump({"build": build, "commit": "old", "requirements_sha256": req or manifest["requirements_sha256"]},
              open(os.path.join(R, "opt/humint-platform/BUILD.json"), "w"))
    run(["openssl", "pkey", "-in", key, "-pubout", "-out", os.path.join(R, "opt/humint/update-signing.pub")],
        check=True)
    applied = [m for m in manifest["migrations"] if m != "migrate-v1.13-hardening.sql"]
    open(os.path.join(R, "var/lib/humint/migrations-applied"), "w").write("\n".join(applied) + "\n")
    open(os.path.join(R, "var/lib/humint/env"), "w").write("TLS=off\nAPI_PORT=80\n")
    open(os.path.join(R, "run/humint-data.ready"), "w").close()
    for name in ("python", "pip"):
        p = os.path.join(R, "opt/humint/venv/bin", name)
        open(p, "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)


stubs = os.path.join(tmp, "stubs")
os.makedirs(stubs)
LOG = os.path.join(tmp, "calls.log")
scripts = {
    "systemctl": f'echo "systemctl $*" >> {LOG}',
    "mountpoint": "exit 0",
    "runuser": 'while [ "$1" != "--" ]; do shift; done; shift; exec "$@"',
    "pg_dump": f'echo "pg_dump $*" >> {LOG}; echo DUMPDATA',
    "pg_restore": f'echo "pg_restore $*" >> {LOG}',
    "psql": f'for a; do case "$a" in *.sql) echo "psql $(basename "$a")" >> {LOG};; esac; done; '
            f'[ -f {tmp}/fail-migration ] && exit 3; exit 0',
    "curl": f'[ -f {tmp}/fail-health ] && exit 7; exit 0',
    "sleep": "exit 0",
}
for name, body in scripts.items():
    p = os.path.join(stubs, name)
    open(p, "w").write("#!/bin/bash\n" + body + "\n")
    os.chmod(p, 0o755)


def update(*args):
    open(LOG, "w").close()
    env = {**os.environ, "HUMINT_TEST_ROOT": R, "HUMINT_LIB": os.path.join(OPT, "lib"),
           "PATH": stubs + ":" + os.environ["PATH"], "TMPDIR": tmp}
    env.pop("HUMINT_UPDATE_COPY", None)
    return run(["bash", os.path.join(OPT, "bin/humint-update.sh"), *args], env=env)


def calls():
    return open(LOG).read()


def installed():
    return json.load(open(os.path.join(R, "opt/humint-platform/BUILD.json")))["build"]


make_box()
r = update("verify", bundle)
check(r.returncode == 0 and "Signed by this box's builder" in r.stdout, "a bundle from the builder verifies")
check(update("verify", foreign).returncode == 3, "one signed by anyone else is refused")
bad = os.path.join(tmp, "tampered.tar")
with tarfile.open(bundle) as src, tarfile.open(bad, "w") as dst:
    for m in src.getmembers():
        data = src.extractfile(m).read()
        if m.name == "payload.tar.gz":
            data = data[:-10] + b"x" * 10
        import io
        m.size = len(data)
        dst.addfile(m, io.BytesIO(data))
check(update("verify", bad).returncode == 3, "one whose contents were altered after signing is refused")

r = update("apply", bundle)
check(r.returncode == 0, f"a newer signed bundle applies ({r.stderr[-400:]})")
check(installed() == manifest["build"], "the box now reports the new build")
check(os.path.exists(os.path.join(R, "opt/humint-platform/api/main.py")) and
      not os.path.exists(os.path.join(R, "opt/humint-platform/api/OLD_VERSION_MARKER")), "the code was swapped in")
check(os.path.exists(os.path.join(R, "opt/humint/bin/humint-update.sh")), "and the appliance's own scripts")
c = calls()
check("pg_dump" in c and c.index("pg_dump") < c.index("systemctl stop"), "the database is backed up before anything stops")
check([l for l in c.splitlines() if l.startswith("psql")] == ["psql migrate-v1.13-hardening.sql"],
      "only the migration this box had not had is run")
check("systemctl start humint.target" in c, "and the console is started again")
check(json.load(open(os.path.join(R, "run/humint/update.json")))["state"] == "done", "the outcome is recorded")

check(update("apply", bundle).returncode == 4, "the same build again is refused as not newer")

# ---- failure puts everything back -------------------------------------------------
for what in ("fail-migration", "fail-health"):
    make_box()
    open(os.path.join(tmp, what), "w").close()
    r = update("apply", bundle)
    os.unlink(os.path.join(tmp, what))
    c = calls()
    check(r.returncode == 7 and installed() == 1 and
          os.path.exists(os.path.join(R, "opt/humint-platform/api/OLD_VERSION_MARKER")),
          f"{what.replace('fail-', 'a failing ')}: the old code is back")
    check("pg_restore" in c, f"{what.replace('fail-', 'a failing ')}: the database is restored from the backup")
    check("migrate-v1.13-hardening.sql" not in open(os.path.join(R, "var/lib/humint/migrations-applied")).read(),
          f"{what.replace('fail-', 'a failing ')}: the migration record is as it was")

make_box(req="something-else")
check(update("apply", bundle).returncode == 5, "a bundle that changes Python packages but carries none is refused")
make_box()
os.unlink(os.path.join(R, "run/humint-data.ready"))
check(update("apply", bundle).returncode == 6, "a locked case file must be opened first")

make_box()
update("apply", bundle)
r = update("rollback")
check(r.returncode == 0 and installed() == 1 and "pg_restore" in calls(),
      "rollback returns code and database to before the update")

# ---- x86: its own bundles, the native app, Ubuntu's packages -------------------------------
import io  # noqa: E402
out86 = os.path.join(tmp, "out86")
os.makedirs(out86)
r = run([os.path.join(ROOT, "deploy/x86/make-update.sh"), "--key", key, "--out", out86, "--no-os", "--no-wheels"])
check(r.returncode == 0, f"the x86 make-update.sh builds a code-only bundle ({r.stderr[-300:]})")
b86 = os.path.join(out86, [f for f in os.listdir(out86) if f.endswith(".tar")][0])
m86 = json.loads(tarfile.open(b86).extractfile("manifest.json").read())
check(m86["platform"] == "x86" and b86.endswith("-x86.tar"), "it is marked as an x86 bundle")

make_box()
check(update("apply", b86).returncode == 8 and installed() == 1, "a Pi refuses an x86 bundle (they share a signing key)")


def make_x86_box(native_req=None):
    make_box()
    open(os.path.join(R, "opt/humint/platform"), "w").write("x86\n")
    os.makedirs(os.path.join(R, "opt/humint/native"), exist_ok=True)
    os.makedirs(os.path.join(R, "opt/humint/ui-venv/bin"), exist_ok=True)
    nr = native_req if native_req is not None else open(os.path.join(ROOT, "native/requirements.txt")).read()
    open(os.path.join(R, "opt/humint/native/requirements.txt"), "w").write(nr)
    open(os.path.join(R, "opt/humint/native/OLD_SCREEN_MARKER"), "w").write("v1")
    p = os.path.join(R, "opt/humint/ui-venv/bin/pip")
    open(p, "w").write("#!/bin/sh\nexit 0\n")
    os.chmod(p, 0o755)


make_x86_box()
check(update("apply", bundle).returncode == 8, "and an x86 machine refuses a Pi bundle")
r = update("apply", b86)
check(r.returncode == 0 and installed() == m86["build"], f"an x86 machine applies an x86 bundle ({r.stderr[-300:]})")
check(os.path.exists(os.path.join(R, "opt/humint/native/humint_ui/__main__.py")) and
      os.path.exists(os.path.join(R, "opt/humint/native/fonts/IBMPlexMono-Regular.ttf")) and
      not os.path.exists(os.path.join(R, "opt/humint/native/OLD_SCREEN_MARKER")), "the screen's app is swapped in")
units = os.listdir(os.path.join(R, "etc/systemd/system"))
check("humint-ui.service" in units and "humint-boxd.service" in units and "humint-panel.service" not in units,
      "with the x86 units, not the Pi's screen units")
check(os.path.exists(os.path.join(R, "opt/humint/bin/humint-ui-launch")), "and the x86 scripts")
check("systemctl try-restart humint-ui.service" in calls(), "the screen restarts on its new code")

make_x86_box(native_req="PySide6-Essentials==0.0.1\n")
check(update("apply", b86).returncode == 5, "a bundle that changes the screen's packages but carries none is refused")


# A bundle with Ubuntu's packages: the same bundle, plus the archive, re-signed.
def with_os(debs_tar_bytes, sha=None):
    path = os.path.join(tmp, "os-bundle.tar")
    with tarfile.open(b86) as src:
        man = json.loads(src.extractfile("manifest.json").read())
        payload = src.extractfile("payload.tar.gz").read()
    import hashlib
    man["os_sha256"] = sha or hashlib.sha256(debs_tar_bytes).hexdigest()
    man["os_packages"] = 1
    mj = os.path.join(tmp, "m.json")
    json.dump(man, open(mj, "w"))
    sig = os.path.join(tmp, "m.sig")
    run(["openssl", "pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", mj, "-out", sig], check=True)
    with tarfile.open(path, "w") as dst:
        for name, data in (("manifest.json", open(mj, "rb").read()), ("manifest.sig", open(sig, "rb").read()),
                           ("payload.tar.gz", payload), ("os-packages.tar", debs_tar_bytes)):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            dst.addfile(ti, io.BytesIO(data))
    return path


buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as t:
    for name, data in (("openssl_3.0.13-0ubuntu3.9_amd64.deb", b"!<arch>\nfake"), ("Packages.gz", b"")):
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
debs = buf.getvalue()
apt_stub = os.path.join(stubs, "apt-get")
open(apt_stub, "w").write(f'#!/bin/bash\necho "apt-get $*" >> {LOG}\n'
                          f'[ -f {tmp}/fail-apt ] && [[ "$*" == *dist-upgrade* ]] && exit 100\nexit 0\n')
os.chmod(apt_stub, 0o755)
dpkg_stub = os.path.join(stubs, "dpkg")
open(dpkg_stub, "w").write(f'#!/bin/bash\necho "dpkg $*" >> {LOG}\nexit 0\n')
os.chmod(dpkg_stub, 0o755)

make_x86_box()
check(update("verify", with_os(debs, sha="0" * 64)).returncode == 3, "a system-package archive that is not the signed one is refused")
make_x86_box()
r = update("apply", with_os(debs))
c = calls()
check(r.returncode == 0 and "dist-upgrade" in c, f"Ubuntu's packages from the bundle are installed ({r.stderr[-300:]})")
check(c.index("pg_dump") < c.index("dist-upgrade") < c.index("systemctl stop"),
      "after the database backup, and before the console stops for the new code")
check("Dir::Etc::SourceParts=/dev/null" in c and "Dir::State::Lists=" in c,
      "from the bundle alone, not the machine's usual package sources")
stage = os.path.join(R, "srv/humint-data/updates/stage")
check(os.path.isdir(stage) and oct(os.stat(stage).st_mode & 0o777) == "0o700" and not os.listdir(stage),
      "unpacked in a root-only folder inside the encrypted store, and nothing left there after")
make_x86_box()
open(os.path.join(tmp, "fail-apt"), "w").close()
r = update("apply", with_os(debs))
os.unlink(os.path.join(tmp, "fail-apt"))
check(r.returncode == 9 and installed() == 1 and os.path.exists(os.path.join(R, "opt/humint/native/OLD_SCREEN_MARKER")),
      "if they fail, the update stops there: nothing else is changed")
check("dpkg --configure -a" in calls(), "and the package manager is left consistent")

# ---- uploading one through the console -----------------------------------------------
inbox = os.path.join(tmp, "inbox", "incoming.tar")
con = Console("update", env={"UPDATE_INBOX": inbox, "UPDATE_STATUS_FILE": os.path.join(tmp, "st.json"),
                             "BUILD_FILE": os.path.join(tmp, "nobuild.json")}).start()
admin = con.register_admin()
ana = con.add_user(admin, "ana")
check(ok(admin.get(con.url + "/api/admin/field-update"))["managed"] is True, "a field server offers updates")
files = {"file": (os.path.basename(bundle), open(bundle, "rb"), "application/x-tar")}
check(ana.post(con.url + "/api/admin/field-update", files=files).status_code == 403, "only admins may upload one")
files = {"file": (os.path.basename(bundle), open(bundle, "rb"), "application/x-tar")}
r = admin.post(con.url + "/api/admin/field-update", files=files)
check(r.status_code == 202 and open(inbox, "rb").read() == open(bundle, "rb").read(),
      "an admin's upload is left, whole, for root to check and apply")
files = {"file": (os.path.basename(bundle), open(bundle, "rb"), "application/x-tar")}
check(admin.post(con.url + "/api/admin/field-update", files=files).status_code == 409,
      "a second upload waits for the first")
con.stop()
plain = Console("update_plain").start()
pa = plain.register_admin()
check(ok(pa.get(plain.url + "/api/admin/field-update"))["managed"] is False, "the Docker console does not offer it")
finish()
