#!/usr/bin/env python3
"""The change log for a release: the commits since the previous release, as
Markdown — each commit's subject as a heading and its message as the text,
without the trailers (Co-Authored-By, Signed-off-by, …).

    deploy/release-notes.py [--since REF] [--repo DIR]

--since defaults to the newest build-* tag (the last release); with none,
the last 20 commits. Used by deploy/publish-release.sh; the box shows these
notes under Admin → Updates before an update is installed.
"""
import argparse
import re
import subprocess
import sys

TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by|Claude-Session|Reviewed-by|Change-Id|Helped-by):", re.I)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def last_release(repo):
    tags = [t for t in git(repo, "tag", "-l", "build-*").split() if re.fullmatch(r"build-\d+", t)]
    return max(tags, key=lambda t: int(t.split("-")[1])) if tags else None


def commits(repo, since):
    rng = f"{since}..HEAD" if since else "HEAD"
    extra = [] if since else ["-n", "20"]
    raw = git(repo, "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", *extra, rng)
    out = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, subject, body = (rec.split("\x1f") + ["", ""])[:3]
        lines = [l for l in body.strip().splitlines() if not TRAILER.match(l.strip())]
        out.append({"sha": sha[:10], "subject": subject.strip(), "body": "\n".join(lines).strip()})
    return out


def notes(repo, since):
    cs = commits(repo, since)
    if not cs:
        return "No changes since the last release."
    parts = []
    for c in cs:
        parts.append(f"### {c['subject']}\n")
        if c["body"]:
            parts.append(c["body"] + "\n")
        parts.append(f"_commit {c['sha']}_\n")
    return "\n".join(parts).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    since = a.since if a.since is not None else last_release(a.repo)
    sys.stdout.write(notes(a.repo, since))


if __name__ == "__main__":
    main()
