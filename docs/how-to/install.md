# How to install and run it for the first time

**You end up with:** a working console at `http://<machine>:8080` and an admin
account.
**Takes:** about 15 minutes without a model; an hour with one, mostly
download time.
**You need:** a machine you control, Docker, and a port people can reach. No
account anywhere, no API key.

---

## 1. Pick the machine

| | Without a model | With a local model |
|---|---|---|
| CPU | 2 cores | 4+ cores |
| RAM | 2 GB | 8 GB for a 7–8B model, more for larger |
| Disk | 5 GB + attachments | 5 GB + the model (4–40 GB) |

- A Raspberry Pi 4 with 8 GB runs the console well. It runs a model too
  slowly to enjoy; point it at an Ollama on a desktop instead (step 6,
  option C).
- Put it on a network you control. **Anyone who can log in sees the whole
  case file** — there is no per-record access control. Do not expose it to the
  open internet.

## 2. Install Docker

Skip this if `docker compose version` already works. On Debian, Ubuntu or
Raspberry Pi OS:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

Log out and back in, then check:

```bash
docker --version
docker compose version
```

If only `docker-compose --version` works, you have the old standalone tool.
Swap `docker compose` for `docker-compose` in every command, or install the
plugin.

## 3. Get the code

```bash
git clone https://github.com/xPirate/humint-platform.git
cd humint-platform
```

## 4. Write `.env`

```bash
cp .env.example .env
openssl rand -base64 24        # a strong database password, if you want one
```

Open `.env` and set **`POSTGRES_PASSWORD`** to something long. You never type
it into the app.

Change these only if you need to:

| Setting | Default | Change it when |
|---|---|---|
| `API_PORT` | `8080` | Something else already uses 8080. |
| `INSTANCE_NAME` | `HUMINT Platform` | You want your own name in the title bar and on PDFs. |
| `MAX_UPLOAD_MB` | `25` | You will attach files bigger than 25 MB. |
| `OLLAMA_ENABLED` | `true` | You are running without a model — set `false`. |
| `PDF_HEADER_LABEL`, `PDF_FOOTER_NOTE` | blank | Before you send any PDF to anybody. |

`.env` holds your database password. It is in `.gitignore`; keep it there.

## 5. Start it

```bash
docker compose up -d --build
docker compose ps                     # db, api and worker should all be running
curl http://localhost:8080/health     # want {"status":"ok","db":true}
```

The first build takes a few minutes. `"db":false` means the API cannot reach
Postgres — see [Fix common problems](troubleshooting.md).

## 6. Choose a model (optional)

Extraction, duplicate detection and the assistant need a model. Everything
else works without one — records, links, reports, exports, the audit trail and
the SQL-only link-signal pass.

**A. No model.** Set `OLLAMA_ENABLED=false` in `.env`, then
`docker compose up -d`. The app says plainly where a model would have helped.

**B. The bundled container.**

```bash
docker compose --profile local-llm up -d
docker compose exec ollama ollama pull llama3.1:8b
```

The defaults in `.env` already point at it.

**C. An Ollama you already run.**

```
OLLAMA_BASE_URL=http://192.168.1.50:11434
OLLAMA_MODEL=llama3.1:8b
```

Use the machine's address, **not `localhost`** — inside the container,
`localhost` is the container. Then `docker compose up -d`.

**Check it:** account menu → **Admin settings → Model**. It says whether the
model answered and how fast.

## 7. Create the admin account

Open `http://<the machine>:8080`. There are no default credentials: **the first
account you create is the administrator.** Use a password of 10+ characters you
don't use anywhere else, and store it somewhere you'll still have if you lose
this laptop. If you lose it anyway, see
[Recover the last admin](users-and-profiles.md#recover-the-last-admin-password).

## 8. Smoke-test it (five minutes)

1. **Entities → + New Entity → Person**, give it a name, **Save**. It appears
   under PERSON in the tree.
2. Make a second one. On the first, **+ Add relationship**, pick the second,
   type `associate_of`, save. A line appears on the network.
3. **Reports → + New Report**, give it a title and a sentence, **Save**, link
   it to a record, then **Export PDF**. A PDF downloads.
4. **Documents** → drop a PDF or image in. Status goes *Waiting → Reading →
   Read* within a minute. With a model, proposals appear under **Review →
   Extraction**; without one, the text is just searchable — that's correct.
5. **Admin settings → Backup & restore → Download backup.** Now you know
   backups work.

If any of 1–3 fail, stop and read the logs:

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f db
```

## 9. Before real data goes in

- [ ] **Set up nightly backups** — [Back up and restore](backup-and-restore.md).
  There is no other copy of your case file.
- [ ] **Put HTTPS in front of it** if anything but this machine reaches it
  (Caddy, nginx, a Tailscale funnel). Then set `SESSION_COOKIE_SECURE=true`
  and `TRUST_PROXY_HEADERS=true` in `.env` and `docker compose up -d`.
- [ ] **Download map tiles** for your area while you have a connection, if
  this machine will ever be offline — [Use the map](maps-and-zones.md) and
  [Configure the instance → Maps](configure-the-instance.md#maps).
- [ ] **Add users** — [Manage users](users-and-profiles.md).
- [ ] **Enroll phones** if anyone will report from the field —
  [Set up field devices](field-devices.md).
- [ ] **Practise** on [`docs/exercise/`](../exercise/BRIEFING.md), or restore a
  sample case file from `samples/` (log in as `demo` / `humint-demo-2026`).
  **Restoring a sample replaces everything**, so do it before your own data
  goes in, or in a second deployment.
