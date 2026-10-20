"""Publish this repository via GitHub's API when git HTTPS is unavailable.

Uses Git's existing credential manager non-interactively. Never prints, stores,
or accepts credentials on the command line. No force pushes or visibility edits.
"""
import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from scripts.package_submission import check_file

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/firefelixfu026/DeskCare"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


class GitHub:
    def __init__(self):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        result = subprocess.run(["git", "-c", "credential.interactive=never", "credential", "fill"],
                                input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True,
                                cwd=ROOT, env=env, timeout=30)
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self._token = fields.get("password") if result.returncode == 0 else None
        if not self._token:
            raise RuntimeError("GitHub credentials unavailable. Sign in with Git Credential Manager; do not paste keys into chat.")

    def call(self, method, suffix, data=None, *, binary=None, content_type=None, optional=False):
        url = suffix if suffix.startswith("https://uploads.github.com/") else API + ("" if suffix == "/" else suffix)
        if not (url == API or url.startswith(API + "/") or url.startswith("https://uploads.github.com/repos/firefelixfu026/DeskCare/releases/")):
            raise RuntimeError("Unexpected publication target")
        body = binary if binary is not None else json.dumps(data).encode() if data is not None else None
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "DeskCare-release"}
        if body is not None:
            headers["Content-Type"] = content_type or "application/json"
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        # Object writes are content-addressed and safe to resume. Release/asset
        # creation is not automatically repeated after an uncertain response.
        attempts = 3 if method == "GET" or suffix.startswith("/git/") else 1
        for attempt in range(attempts):
            try:
                with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers, method=method), timeout=120) as response:
                    return json.load(response)
            except HTTPError as exc:
                if optional and exc.code == 404:
                    return None
                if exc.code in {502, 503, 504} and attempt+1 < attempts:
                    time.sleep(attempt+1)
                    continue
                raise RuntimeError(f"GitHub API HTTP {exc.code}; no credential or response body logged") from None
            except (URLError, TimeoutError, ConnectionError):
                if attempt+1 == attempts:
                    raise RuntimeError("GitHub network interrupted; safe to resume identical Git objects") from None
                time.sleep(attempt+1)


def identity(value):
    who, timestamp, zone = value.rsplit(" ", 2)
    name, email = who.rsplit(" <", 1)
    offset = (int(zone[1:3])*60 + int(zone[3:])) * (1 if zone[0] == "+" else -1)
    at = datetime.fromtimestamp(int(timestamp), timezone(timedelta(minutes=offset)))
    return {"name": name, "email": email.rstrip(">"), "date": at.isoformat()}


def publish_history(api, remote_sha, local_sha):
    if subprocess.run(["git", "merge-base", "--is-ancestor", remote_sha, local_sha], cwd=ROOT,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise RuntimeError("Remote main is not an ancestor. No force update attempted.")
    remote_commit = api.call("GET", "/git/commits/" + remote_sha)
    remote_tree = api.call("GET", "/git/trees/" + remote_commit["tree"]["sha"] + "?recursive=1")
    if remote_tree.get("truncated"):
        raise RuntimeError("Remote tree unexpectedly large")
    known = {item["sha"] for item in remote_tree["tree"] if item["type"] == "blob"}
    commits = git("rev-list", "--reverse", "--topo-order", f"{remote_sha}..{local_sha}").decode().splitlines()
    for number, sha in enumerate(commits, 1):
        records = git("ls-tree", "-r", "--full-tree", "-z", sha).split(b"\0")
        if api.call("GET", "/git/commits/" + sha, optional=True) is not None:
            known.update(record.split(b"\t", 1)[0].decode().split()[2] for record in records if record)
            print(f"Reused commit {number}/{len(commits)} {sha[:8]}", flush=True)
            continue
        tree = []
        for record in records:
            if not record:
                continue
            header, path = record.split(b"\t", 1)
            mode, kind, blob = header.decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise RuntimeError("Unsupported tree entry")
            if blob not in known:
                payload = git("cat-file", "blob", blob)
                check_file(path.decode("utf-8"), payload)
                created = api.call("POST", "/git/blobs", {"encoding": "base64", "content": base64.b64encode(payload).decode()})
                if created["sha"] != blob:
                    raise RuntimeError("Blob hash mismatch")
                known.add(blob)
            tree.append({"path": path.decode("utf-8"), "mode": mode, "type": "blob", "sha": blob})
        created_tree = api.call("POST", "/git/trees", {"tree": tree})
        expected_tree = git("rev-parse", sha + "^{tree}").decode().strip()
        if created_tree["sha"] != expected_tree:
            raise RuntimeError("Tree hash mismatch")
        header, message = git("cat-file", "commit", sha).decode("utf-8").split("\n\n", 1)
        fields, parents = {}, []
        for line in header.splitlines():
            key, value = line.split(" ", 1)
            if key == "parent": parents.append(value)
            elif key in {"author", "committer"}: fields[key] = identity(value)
            elif key not in {"tree"}: raise RuntimeError("Signed or extra commit headers need normal git push")
        created = api.call("POST", "/git/commits", {"message": message, "tree": expected_tree, "parents": parents, **fields})
        if created["sha"] != sha:
            raise RuntimeError("Commit hash mismatch; main was not changed")
        print(f"Uploaded commit {number}/{len(commits)} {sha[:8]}", flush=True)
    # Compare again, and use force=false. Concurrent changes cannot be overwritten.
    if api.call("GET", "/git/ref/heads/main")["object"]["sha"] != remote_sha:
        raise RuntimeError("Remote changed during upload; main not changed")
    api.call("PATCH", "/git/refs/heads/main", {"sha": local_sha, "force": False})
    actual = api.call("GET", "/git/ref/heads/main")["object"]["sha"]
    if actual != local_sha:
        raise RuntimeError("Remote verification mismatch")
    print("Verified main: " + actual, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--committed-only", action="store_true", help="Publish HEAD objects only while unrelated presentation artifacts are being prepared")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--tag", default="v2.0.0-ui13")
    parser.add_argument("--asset", action="append", type=Path, default=[])
    args = parser.parse_args()
    api = GitHub()
    repo = api.call("GET", "/")
    remote_sha = api.call("GET", "/git/ref/heads/main")["object"]["sha"]
    local_sha = git("rev-parse", "HEAD").decode().strip()
    print(json.dumps({"repository": repo["html_url"], "visibility": repo["visibility"], "remote": remote_sha,
                      "local": local_sha, "can_push": repo.get("permissions", {}).get("push", False)}), flush=True)
    if args.push:
        if git("status", "--porcelain").strip() and not args.committed_only:
            raise RuntimeError("Commit reviewed changes before publishing")
        publish_history(api, remote_sha, local_sha)
    if args.release:
        if api.call("GET", "/git/ref/heads/main")["object"]["sha"] != local_sha:
            raise RuntimeError("Publish current main before release")
        release = api.call("GET", "/releases/tags/" + quote(args.tag), optional=True)
        if release is None:
            notes = (ROOT / "docs" / "release-ui13.md").read_text(encoding="utf-8")
            release = api.call("POST", "/releases", {"tag_name": args.tag, "target_commitish": local_sha,
                               "name": "DeskCare UI13 Windows 体验版", "body": notes, "draft": False, "prerelease": True})
        if release["tag_name"] != args.tag or release.get("draft"):
            raise RuntimeError("Unexpected release")
        assets = {item["name"]: item for item in api.call("GET", f"/releases/{release['id']}/assets")}
        for path in args.asset:
            selected = path.resolve()
            if not selected.is_relative_to(ROOT) or selected.suffix.lower() not in {".zip", ".pdf", ".txt"}:
                raise RuntimeError("Only selected repository release artifacts are allowed")
            content = selected.read_bytes()
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            if selected.name in assets:
                if assets[selected.name].get("digest") != digest:
                    raise RuntimeError("Different existing asset; will not overwrite")
                continue
            uploaded = api.call("POST", release["upload_url"].split("{")[0] + "?name=" + quote(selected.name),
                                binary=content, content_type="application/octet-stream")
            if uploaded.get("digest") != digest or uploaded["size"] != len(content):
                raise RuntimeError("Release asset verification failed")
            print(json.dumps({"asset": uploaded["browser_download_url"], "sha256": digest, "size": len(content)}), flush=True)
        print("Release: " + release["html_url"], flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(str(exc))
        raise SystemExit(1)
