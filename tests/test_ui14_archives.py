import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import time
from zipfile import ZipFile

import pytest

import scripts.archive_legacy_versions as archiver


@pytest.fixture
def archive_fixture(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(archiver.ROOT / "scripts/restore_legacy_versions.ps1", scripts / "restore_legacy_versions.ps1")
    shutil.copyfile(archiver.ROOT / "scripts/cleanup_archived_versions.ps1", scripts / "cleanup_archived_versions.ps1")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/历史版本归档说明.md").write_text("fictional fixture", encoding="utf-8")
    (tmp_path / "dist/DeskCare-UI12").mkdir(parents=True)
    (tmp_path / "dist/DeskCare-UI13").mkdir()
    (tmp_path / "release").mkdir()
    for name in ("DeskCare-UI12", "DeskCare-UI13"):
        (tmp_path / "dist" / name / "runtime.txt").write_bytes(b"shared fictional runtime"*10)
        (tmp_path / "dist" / name / (name+".exe")).write_bytes(name.encode())
    output = tmp_path / "release/Legacy-Archive-2026-10-21"
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    monkeypatch.setattr(archiver, "OUTPUT", output)
    monkeypatch.setattr(archiver, "PART_LIMIT", 300)
    return tmp_path, output


def test_archive_dedup_has_exact_original_paths_and_native_restore(archive_fixture):
    root, output = archive_fixture
    archiver.prepare()
    index = json.loads((output / "Legacy-Archive-Index.json").read_text(encoding="utf-8"))
    assert index["original_bytes"] > index["unique_bytes"]
    assert len(index["manifest"]["files"]) == 4 and len(index["manifest"]["objects"]) == 3
    restore = output / "RESTORE.ps1"
    shutil.copyfile(root / "scripts/restore_legacy_versions.ps1", restore)
    destination = root / "recovered"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(restore), "-Destination", str(destination)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    for entry in index["manifest"]["files"]:
        assert (destination / entry["path"]).read_bytes() == (root / entry["path"]).read_bytes()
    # Existing destinations are never overwritten.
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(restore), "-Destination", str(destination)], capture_output=True, timeout=30)
    assert result.returncode != 0


def test_personal_database_is_never_archived_or_selected_for_cleanup(archive_fixture):
    root, output = archive_fixture
    private = root / "dist/DeskCare-UI12/personal.sqlite3.before-ui10"
    private.write_bytes(b"fictional private data")
    archiver.prepare()
    index = json.loads((output / "Legacy-Archive-Index.json").read_text(encoding="utf-8"))
    assert "dist/DeskCare-UI12" not in index["manifest"]["targets"]
    assert index["manifest"]["skipped"] and private.is_file()


def test_public_ca_bundle_is_not_confused_with_private_key(archive_fixture):
    root, output = archive_fixture
    public = b"-----BEGIN CERTIFICATE-----\nFAKE-PUBLIC-FIXTURE\n-----END CERTIFICATE-----"
    archiver.audit_file("dist/DeskCare-UI1/_internal/certifi/cacert.pem", public)
    with pytest.raises(ValueError):
        archiver.audit_file("dist/DeskCare-UI1/_internal/certifi/cacert.pem", b"-----BEGIN " + b"PRIVATE KEY-----")
    with pytest.raises(AssertionError):
        archiver.audit_file("dist/DeskCare-UI1/key.pem", public)


def test_cleanup_requires_receipt_and_retains_changed_targets(archive_fixture):
    root, output = archive_fixture
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    archiver.prepare()
    exe = root / "dist/DeskCare-UI14/DeskCare-UI14.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"fake replacement test fixture")
    sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    script = root / "scripts/cleanup_archived_versions.ps1"
    def cleanup():
        return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(script), "-ProjectRoot", str(root), "-CurrentExeSha256", sha], capture_output=True, timeout=45)
    assert cleanup().returncode != 0
    assert (root / "dist/DeskCare-UI12/runtime.txt").exists()
    index_path = output / "Legacy-Archive-Index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    receipt = {"release": "https://github.com/firefelixfu026/DeskCare/releases/tag/legacy-archive-2026-10-21",
               "index_sha256": archiver.digest(index_path), "assets": index["parts"]}
    (output / "UPLOAD-VERIFIED.json").write_text(json.dumps(receipt), encoding="utf-8")
    (root / "dist/DeskCare-UI12/runtime.txt").write_bytes(b"a change after snapshot")
    result = cleanup()
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert (root / "dist/DeskCare-UI12/runtime.txt").read_bytes() == b"a change after snapshot"
    assert not (root / "dist/DeskCare-UI13").exists()
    assert exe.exists()


def test_real_running_windows_image_preserves_entire_version(archive_fixture, monkeypatch):
    root, output = archive_fixture
    monkeypatch.setattr(archiver, "PART_LIMIT", 5_000_000)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    old_exe = root / "dist/DeskCare-UI12/LOCK-TEST.exe"
    # Compile a disposable sleeping process, never launch the user's app or
    # depend on Windows utilities' localized MUI resources or network access.
    source = "public class LockTest { public static void Main() { System.Threading.Thread.Sleep(60000); } }"
    command = "Add-Type -TypeDefinition '" + source + "' -OutputAssembly '" + str(old_exe).replace("'", "''") + "' -OutputType ConsoleApplication"
    compiled = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    archiver.prepare()
    index_path = output / "Legacy-Archive-Index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    receipt = {"release": "https://github.com/firefelixfu026/DeskCare/releases/tag/legacy-archive-2026-10-21",
               "index_sha256": archiver.digest(index_path), "assets": index["parts"]}
    (output / "UPLOAD-VERIFIED.json").write_text(json.dumps(receipt), encoding="utf-8")
    replacement = root / "dist/DeskCare-UI14/DeskCare-UI14.exe"
    replacement.parent.mkdir()
    replacement.write_bytes(b"fake verified replacement")
    child = subprocess.Popen([str(old_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        time.sleep(.15)
        assert child.poll() is None
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(root / "scripts/cleanup_archived_versions.ps1"), "-ProjectRoot", str(root), "-CurrentExeSha256",
            archiver.digest(replacement)], capture_output=True, timeout=45)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        for entry in index["manifest"]["files"]:
            if entry["path"].startswith("dist/DeskCare-UI12/"):
                assert archiver.digest(root / entry["path"]) == entry["sha256"]
        assert not (root / "dist/DeskCare-UI13").exists()
    finally:
        child.terminate()
        child.wait(timeout=5)
