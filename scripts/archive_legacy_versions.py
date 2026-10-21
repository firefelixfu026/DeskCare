"""Archive selected old product folders with byte-exact deduplication.

No deletion here. Cleanup is a separate native PowerShell gate after server
hash verification and a working replacement build. Personal data is excluded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.github_release import GitHub
from scripts.package_submission import check_file

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "release/Legacy-Archive-2026-10-21"
TAG = "legacy-archive-2026-10-21"
PART_LIMIT = 200_000_000


def audit_file(name, payload):
    # certifi's published CA trust bundle is public data, not a private key.
    if name.replace('\\', '/').endswith('/certifi/cacert.pem'):
        if not payload or b'-----BEGIN CERTIFICATE-----' not in payload or b'PRIVATE KEY' in payload:
            raise ValueError('Unexpected certificate contents; keep locally')
        check_file(name + '.txt', payload)
        return
    if re.search(r'\.(?:sqlite3?|db)(?:$|[.-])', name, re.I):
        raise ValueError('Possible database; keep locally')
    check_file(name, payload)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def targets(root=None):
    root = root or ROOT
    found = []
    for parent in ("dist", "release"):
        for entry in sorted((root / parent).iterdir()):
            if entry.name in {"DeskCare-UI14", "UI14"}:
                continue
            if (entry.name.startswith("DeskCare") or entry.name == "UI13"
                    or (entry.is_file() and entry.name in {"M8_运行说明.txt", "M9_运行说明.txt", "README_运行说明.txt", "SHA256SUMS.txt"})):
                found.append(entry)
    return found


def safe_files(target, root=None):
    root = root or ROOT
    resolved = target.resolve()
    if not any(resolved.is_relative_to(root / name) for name in ("dist", "release")) or resolved == root:
        raise ValueError("Archive target outside selected version roots")
    files = []
    pending = [target]
    while pending:
        entry = pending.pop()
        info = entry.lstat()
        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("Linked paths are not archived or cleaned")
        if not entry.resolve().is_relative_to(resolved if target.is_dir() else resolved.parent):
            raise ValueError("Archive path escaped target")
        if entry.is_dir():
            pending.extend(entry.iterdir())
            continue
        if entry.is_file():
            name = entry.relative_to(root).as_posix()
            audit_file(name, entry.read_bytes() if name.endswith('/certifi/cacert.pem') else b"")
            if entry.suffix.lower() in {".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite3-wal", ".sqlite3-shm", ".bak"}:
                raise ValueError("Possible personal data; keep this target locally")
            if entry.suffix.lower() in {".txt", ".md", ".json", ".py", ".ps1", ".cmd", ".csv", ".toml", ".xml", ".ini"}:
                if info.st_size > 5_000_000:
                    raise ValueError("Unexpected large configuration; keep locally")
                audit_file(name, entry.read_bytes())
            if entry.suffix.lower() == ".zip":
                with ZipFile(entry) as archive:
                    for member in archive.infolist():
                        audit_file(member.filename.rstrip("/") or "directory", archive.read(member) if member.filename.endswith('/certifi/cacert.pem') else b"")
                        if not member.is_dir() and member.file_size < 2_000_000 and Path(member.filename).suffix.lower() in {".txt", ".md", ".json", ".py", ".ps1", ".cmd", ".csv"}:
                            check_file(member.filename, archive.read(member))
            files.append(entry)
    return files


def prepare():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index_path = OUTPUT / "Legacy-Archive-Index.json"
    if index_path.exists():
        print("Existing verified local archive retained; use --upload to resume.", flush=True)
        return
    files, objects, selected, skipped = [], {}, [], []
    for target in targets():
        try:
            members = safe_files(target)
        except (AssertionError, ValueError) as exc:
            skipped.append({"path": target.relative_to(ROOT).as_posix(), "reason": str(exc)})
            continue
        selected.append(target.relative_to(ROOT).as_posix())
        for path in members:
            sha = digest(path)
            size = path.stat().st_size
            relative = path.relative_to(ROOT).as_posix()
            files.append({"path": relative, "sha256": sha, "size": size})
            objects.setdefault(sha, {"source": relative, "size": size})
    bins, current, size = [], [], 0
    for sha, record in objects.items():
        if record["size"] > PART_LIMIT:
            raise ValueError("Single object too large; no cleanup allowed")
        if current and size + record["size"] > PART_LIMIT:
            bins.append(current)
            current, size = [], 0
        current.append(sha)
        size += record["size"]
    if current:
        bins.append(current)
    for index, group in enumerate(bins, 1):
        name = f"DeskCare-Legacy-Archive-part{index:02}.zip"
        for sha in group:
            objects[sha]["part"] = name
    manifest = {"format": 1, "created_day": "2026-10-21", "targets": selected, "skipped": skipped,
                "files": files, "objects": {sha: {key: value for key, value in record.items() if key != "source"}
                                               for sha, record in objects.items()}}
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    parts = []
    for index, group in enumerate(bins, 1):
        name = f"DeskCare-Legacy-Archive-part{index:02}.zip"
        path = OUTPUT / name
        if path.exists():
            raise RuntimeError("Partial archive exists; inspect before retry, never overwrite")
        with ZipFile(path, "x", ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("MANIFEST.json", raw)
            archive.write(ROOT / "scripts/restore_legacy_versions.ps1", "RESTORE.ps1")
            archive.write(ROOT / "docs/历史版本归档说明.md", "README.md")
            for sha in group:
                archive.write(ROOT / objects[sha]["source"], "objects/" + sha)
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Archive CRC check failed")
            for sha in group:
                with archive.open("objects/" + sha) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                        raise RuntimeError("Archive object hash mismatch")
        parts.append({"name": name, "sha256": digest(path), "size": path.stat().st_size})
        print(f"Verified archive {index}/{len(bins)}: {name} {path.stat().st_size} bytes", flush=True)
    index = {"tag": TAG, "manifest": manifest, "parts": parts,
             "original_bytes": sum(record["size"] for record in files),
             "unique_bytes": sum(record["size"] for record in objects.values())}
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"targets": len(selected), "files": len(files), "parts": len(parts),
                      "original_bytes": index["original_bytes"], "unique_bytes": index["unique_bytes"], "skipped": skipped}, ensure_ascii=False), flush=True)


def upload():
    index_path = OUTPUT / "Legacy-Archive-Index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    api = GitHub()
    release = api.call("GET", "/releases/tags/" + TAG, optional=True)
    if release is None:
        release = api.call("POST", "/releases", {"tag_name": TAG, "target_commitish": api.call("GET", "/git/ref/heads/main")["object"]["sha"],
            "name": "DeskCare 历史版本归档 2026-10-21", "prerelease": False, "make_latest": "false", "draft": False,
            "body": "旧版运行包与提交包的逐字节去重归档。下载所有 ZIP 分包以及单独的 RESTORE.ps1、README.md 和索引，按说明恢复。以发布页单独提供的恢复脚本为准。每个原文件均有 SHA256，未包含用户数据库或凭据。最新体验版请到仓库 README 的下载入口。"})
    existing = {item["name"]: item for item in api.call("GET", f"/releases/{release['id']}/assets?per_page=100")}
    expected = index["parts"] + [{"name": index_path.name, "sha256": digest(index_path), "size": index_path.stat().st_size}]
    for source, name in ((ROOT / "scripts/restore_legacy_versions.ps1", "RESTORE.ps1"), (ROOT / "docs/历史版本归档说明.md", "README.md")):
        path = OUTPUT / name
        shutil.copyfile(source, path)
        expected.append({"name": name, "sha256": digest(path), "size": path.stat().st_size})

    def one(record):
        path = OUTPUT / record["name"]
        if digest(path) != record["sha256"] or path.stat().st_size != record["size"]:
            raise RuntimeError("Local archive changed; no upload or cleanup")
        asset = existing.get(record["name"])
        if asset is not None and asset.get("state") == "starter" and asset.get("size") == 0 and not asset.get("digest"):
            api.call("DELETE", f"/releases/assets/{asset['id']}")
            asset = None
        if asset is None:
            print(f"Uploading {record['name']} ({record['size']} bytes)", flush=True)
            asset = api.call("POST", release["upload_url"].split("{")[0] + "?name=" + quote(record["name"]),
                             binary=path.read_bytes(), content_type="application/octet-stream", timeout=900)
        if asset.get("digest") != "sha256:" + record["sha256"] or asset["size"] != record["size"]:
            raise RuntimeError("Remote archive hash mismatch; no cleanup")
        print(f"Server verified {record['name']}", flush=True)
        return {"name": record["name"], "sha256": record["sha256"], "size": record["size"], "url": asset["browser_download_url"], "id": asset["id"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipt = list(executor.map(one, expected))
    (OUTPUT / "UPLOAD-VERIFIED.json").write_text(json.dumps({"release": release["html_url"], "index_sha256": digest(index_path),
                                                            "assets": receipt}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("All archive assets server-hash verified: " + release["html_url"], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    if args.prepare: prepare()
    if args.upload: upload()


if __name__ == "__main__":
    main()
