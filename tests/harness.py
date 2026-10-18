"""Test harness: a real Postgres and a real API process, nothing mocked.

Each test file builds one or more Consoles. A Console is a fresh database
(loaded from db/init.sql) plus the API running under uvicorn on a free port,
torn down when the test ends.

Where Postgres comes from:
  * POSTGRES_HOST/PORT/USER/PASSWORD set (CI: a postgres:16 service) — each
    Console creates a database of its own on that server;
  * otherwise a throwaway cluster is started with initdb from
    /usr/lib/postgresql/<n>/bin (as the 'postgres' user when run as root).

    python3 tests/test_worker_recovery.py
    tests/run.sh              # every test_*.py
"""
import atexit
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg2
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "Test-password-123"
_failures = 0


# ---- reporting ---------------------------------------------------------------

def check(cond, label):
    """One promise the product makes, stated as a sentence."""
    global _failures
    print(("PASS " if cond else "FAIL ") + label, flush=True)
    if not cond:
        _failures += 1
    return cond


def finish():
    print(f"{'OK' if not _failures else 'FAILED'}: {_failures} failure(s)", flush=True)
    sys.exit(1 if _failures else 0)


def ok(r, *codes):
    assert r.status_code in (codes or (200, 201)), (r.request.method, r.url, r.status_code, r.text[:500])
    if r.content and r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---- Postgres ----------------------------------------------------------------

class _Server:
    """Connection details for a server we may create databases on."""
    _shared = None

    def __init__(self):
        if os.environ.get("POSTGRES_HOST"):
            self.host = os.environ["POSTGRES_HOST"]
            self.port = int(os.environ.get("POSTGRES_PORT", "5432"))
            self.user = os.environ.get("POSTGRES_USER", "postgres")
            self.password = os.environ.get("POSTGRES_PASSWORD", "")
            return
        self._start_local()

    @classmethod
    def get(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def _start_local(self):
        bindir = None
        for v in ("17", "16", "15"):
            if os.path.isdir(f"/usr/lib/postgresql/{v}/bin"):
                bindir = f"/usr/lib/postgresql/{v}/bin"
                break
        if bindir is None:
            sys.exit("no Postgres found: install postgresql, or set POSTGRES_HOST")
        self.dir = tempfile.mkdtemp(prefix="humint-pg-")
        self.port = free_port()
        self.host, self.user, self.password = "127.0.0.1", "humint_test", PASSWORD
        as_user = []
        if os.geteuid() == 0:
            pwd.getpwnam("postgres")
            shutil.chown(self.dir, "postgres")
            as_user = ["runuser", "-u", "postgres", "--"]
        pwfile = os.path.join(self.dir, "pw")
        with open(pwfile, "w") as fh:
            fh.write(PASSWORD)
        if as_user:
            shutil.chown(pwfile, "postgres")
        data = os.path.join(self.dir, "data")
        subprocess.run(as_user + [f"{bindir}/initdb", "-D", data, "-U", self.user,
                                  f"--pwfile={pwfile}", "-A", "md5", "-E", "UTF8",
                                  "--locale=C.UTF-8"],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(as_user + [f"{bindir}/pg_ctl", "-D", data, "-l", os.path.join(self.dir, "log"),
                                  "-o", f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1 "
                                        "-c fsync=off -c synchronous_commit=off",
                                  "-w", "start"],
                       check=True, stdout=subprocess.DEVNULL)
        atexit.register(lambda: (subprocess.run(as_user + [f"{bindir}/pg_ctl", "-D", data, "-m",
                                                           "immediate", "stop"],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                                 shutil.rmtree(self.dir, ignore_errors=True)))

    def connect(self, dbname="postgres"):
        return psycopg2.connect(host=self.host, port=self.port, user=self.user,
                                password=self.password, dbname=dbname)


# ---- a console ----------------------------------------------------------------

class Console:
    def __init__(self, name="console", env=None, schema=os.path.join(ROOT, "db", "init.sql")):
        self.server = _Server.get()
        self.dbname = f"t_{name}_{uuid.uuid4().hex[:8]}".lower()
        admin = self.server.connect()
        admin.autocommit = True
        admin.cursor().execute(f'CREATE DATABASE "{self.dbname}" ENCODING \'UTF8\' TEMPLATE template0')
        admin.close()
        if schema:
            self.sql_file(schema)
        self.dir = tempfile.mkdtemp(prefix=f"humint-{name}-")
        self.env = {
            **os.environ,
            "POSTGRES_HOST": self.server.host, "POSTGRES_PORT": str(self.server.port),
            "POSTGRES_USER": self.server.user, "POSTGRES_PASSWORD": self.server.password,
            "POSTGRES_DB": self.dbname,
            "FRONTEND_DIR": os.path.join(ROOT, "frontend"),
            "UPLOAD_DIR": os.path.join(self.dir, "uploads"),
            "MAP_PACK_DIR": os.path.join(self.dir, "map-packs"),
            "OLLAMA_ENABLED": "false", "GEOCODE_ENABLED": "false", "OVERPASS_ENABLED": "false",
            "MAP_DOWNLOAD_ENABLED": "false", "LINK_SIGNALS_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            **(env or {}),
        }
        os.makedirs(self.env["UPLOAD_DIR"], exist_ok=True)
        os.makedirs(self.env["MAP_PACK_DIR"], exist_ok=True)
        self.proc = None
        self.url = None
        atexit.register(self.stop)

    # database
    def db(self):
        conn = self.server.connect(self.dbname)
        conn.autocommit = True
        return conn

    def sql(self, query, params=None):
        with self.db() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else cur.rowcount

    def sql_file(self, path):
        with open(path) as fh:
            text = fh.read()
        with self.db() as conn, conn.cursor() as cur:
            cur.execute(text)

    # the API
    def start(self):
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        self.log = open(os.path.join(self.dir, "api.log"), "w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=os.path.join(ROOT, "api"), env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(120):
            try:
                requests.get(self.url + "/api/auth/bootstrap-status", timeout=1)
                return self
            except requests.RequestException:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.25)
        self.log.flush()
        sys.exit("API did not start:\n" + open(self.log.name).read()[-3000:])

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def register_admin(self, username="admin"):
        s = requests.Session()
        ok(s.post(self.url + "/api/auth/register",
                  json={"username": username, "password": PASSWORD, "display_name": username.title()}))
        return s

    def login(self, username, password=PASSWORD, **extra):
        s = requests.Session()
        r = s.post(self.url + "/api/auth/login", json={"username": username, "password": password, **extra})
        return s, r

    def add_user(self, admin, username, role="analyst"):
        ok(admin.post(self.url + "/api/auth/register",
                      json={"username": username, "password": PASSWORD, "display_name": username.title(),
                            "role": role}))
        s, r = self.login(username)
        ok(r)
        return s

    # the worker, imported in-process against this database
    def worker_env(self):
        for k in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
                  "UPLOAD_DIR", "MAP_PACK_DIR", "OLLAMA_ENABLED", "GEOCODE_ENABLED",
                  "MAP_DOWNLOAD_ENABLED", "LINK_SIGNALS_ENABLED"):
            os.environ[k] = self.env[k]
        worker = os.path.join(ROOT, "worker")
        if worker not in sys.path:
            sys.path.insert(0, worker)
