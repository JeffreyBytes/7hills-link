"""Updater: version checks, release parsing and checksum verification (no network)."""

import hashlib
import json

import pytest

from sevenhills_link import updater


def test_versions():
    assert updater.is_newer("v0.4.0", "0.3.0")
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer("v0.3.0", "0.3.0")
    assert not updater.is_newer("v0.2.9", "0.3.0")


def _release(tag, digest=None, sha_file=False):
    assets = [{"name": "7HillsLink.exe", "browser_download_url": "https://github.com/x/7HillsLink.exe", "size": 3}]
    if digest:
        assets[0]["digest"] = "sha256:" + digest
    if sha_file:
        assets.append({"name": "7HillsLink.exe.sha256", "browser_download_url": "https://github.com/x/7HillsLink.exe.sha256"})
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def test_check_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    blob = b"exe"
    good = hashlib.sha256(blob).hexdigest()
    pages = {updater.API: _release("v99.0.0", sha_file=True), "https://github.com/x/7HillsLink.exe": blob,
             "https://github.com/x/7HillsLink.exe.sha256": (good + "  7HillsLink.exe").encode()}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    info = updater.check()
    assert info["version"] == "99.0.0" and info["sha256"] is None and info["sha256_url"]
    path = updater.download(info)
    assert path.read_bytes() == blob and path.name == "7HillsLink-99.0.0.exe"

    # Same version as this build: nothing to do.
    pages[updater.API] = _release("v" + updater.__version__, digest=good)
    assert updater.check() is None


def test_bad_checksum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pages = {updater.API: _release("v99.0.0", digest="0" * 64), "https://github.com/x/7HillsLink.exe": b"evil"}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(updater.check())
    assert not list((tmp_path / "7HillsLink" / "update").glob("*.exe"))


def test_no_checksum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pages = {updater.API: _release("v99.0.0")}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    with pytest.raises(updater.UpdateError, match="no checksum"):
        updater.download(updater.check())


def test_only_github_hosts():
    with pytest.raises(updater.UpdateError):
        updater._get("https://evil.example/7HillsLink.exe")
    with pytest.raises(updater.UpdateError):
        updater._get("http://github.com/x")


def test_source_build_never_installs():
    assert updater.can_install() is False
    with pytest.raises(updater.UpdateError):
        updater.install(updater.update_dir() / "x.exe")
