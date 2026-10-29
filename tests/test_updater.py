"""Updater tests - all network is mocked; filesystem work happens in tmp_path."""
import hashlib
import io
import json
import shutil
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from voice_midi import __version__, updater

ROOT = Path(__file__).resolve().parent.parent
API = updater.API_LATEST.format(repo=updater.REPO)


# ------------------------------------------------------------------ helpers
@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "userhome"
    monkeypatch.setenv("VOICE_MIDI_HOME", str(h))
    monkeypatch.delenv("VOICE_MIDI_NO_UPDATE", raising=False)
    return h


def make_tree(root: Path, version: str, req="mido\npyyaml\n", extra=None):
    (root / "voice_midi").mkdir(parents=True)
    (root / "voice_midi" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "voice_midi" / "parser.py").write_text(f"# parser {version}\n")
    (root / "requirements.txt").write_text(req)
    (root / "config").mkdir()
    (root / "config" / "config.yaml").write_text(f"# bundled default {version}\n")
    (root / "run.sh").write_text(f"echo {version}\n")
    for k, v in (extra or {}).items():
        (root / k).write_text(v)
    return root


def zip_tree(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in root.rglob("*"):
            if p.is_file():
                z.write(p, Path("voice-midi") / p.relative_to(root))
    return buf.getvalue()


class FakeNet:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, timeout=None, accept=None):
        self.calls.append(url)
        r = self.routes.get(url)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return r


def release_net(tmp_path, version="0.4.0", req="mido\npyyaml\n", tamper=False, extra=None):
    src = make_tree(tmp_path / f"src-{version}", version, req, extra)
    blob = zip_tree(src)
    name = f"voice-midi-{version}.zip"
    digest = hashlib.sha256(blob).hexdigest()
    if tamper:
        blob = blob + b"evil"
    rel = {"tag_name": f"v{version}", "draft": False, "prerelease": False, "assets": [
        {"name": name, "browser_download_url": f"https://dl/{name}"},
        {"name": "SHA256SUMS", "browser_download_url": "https://dl/SHA256SUMS"}]}
    return FakeNet({API: json.dumps(rel).encode(), f"https://dl/{name}": blob,
                    "https://dl/SHA256SUMS": f"{digest}  {name}\n".encode()}), rel


@pytest.fixture
def install(tmp_path):
    inst = make_tree(tmp_path / "install", "0.3.0")
    (inst / ".venv").mkdir()
    (inst / ".venv" / "marker").write_text("keep me")
    return inst


# ------------------------------------------------------------------ versions
@pytest.mark.parametrize("a,b,newer", [
    ("0.3.1", "0.3.0", True), ("v0.10.0", "0.9.9", True), ("1.0.0", "0.99.99", True),
    ("0.3.0", "0.3.0", False), ("v0.2.9", "0.3.0", False),
    ("0.3.0", "0.3.0-rc.1", True), ("0.3.0-rc.2", "0.3.0-rc.1", True), ("0.3.0-rc.10", "0.3.0-rc.9", True),
    ("0.3.0-beta", "0.3.0-alpha", True), ("0.3.0+build5", "0.3.0", False),
])
def test_semver(a, b, newer):
    assert updater.is_newer(a, b) is newer


def test_bad_version():
    with pytest.raises(ValueError):
        updater.parse_version("latest")


def test_version_single_source():
    if sys.version_info >= (3, 11):
        import tomllib
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "voice_midi.__version__"
    assert updater.CURRENT_VERSION == __version__ == updater.read_version(ROOT)


# ------------------------------------------------------------------ checksums
def test_checksum_ok_and_mismatch(tmp_path):
    f = tmp_path / "a.zip"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    assert updater.verify_checksum(f, f"{good}  a.zip\n") == good
    assert updater.verify_checksum(f, f"{good} *a.zip\n") == good          # binary-mode marker
    with pytest.raises(updater.UpdateError, match="mismatch"):
        updater.verify_checksum(f, f"{'0' * 64}  a.zip\n")
    with pytest.raises(updater.UpdateError, match="not listed"):
        updater.verify_checksum(f, f"{good}  other.zip\n")


# ------------------------------------------------------------------ offline / API errors
@pytest.mark.parametrize("exc,status,text", [
    (urllib.error.URLError("no route"), "error", "offline"),
    (TimeoutError("timed out"), "error", "offline"),
    (urllib.error.HTTPError(API, 403, "rate", {"X-RateLimit-Reset": "1700000000"}, None), "error", "rate limit"),
    (urllib.error.HTTPError(API, 404, "nf", {}, None), "none", "no published release"),
    (urllib.error.HTTPError(API, 500, "boom", {}, None), "error", "HTTP 500"),
])
def test_check_handles_network_problems(exc, status, text):
    res = updater.check(current="0.3.0", get=FakeNet({API: exc}))
    assert res["status"] == status and text in res["message"]


def test_check_garbage_and_prerelease():
    assert updater.check(get=FakeNet({API: b"<html>"}))["status"] == "error"
    pre = json.dumps({"tag_name": "v9.0.0", "prerelease": True}).encode()
    assert updater.check(get=FakeNet({API: pre}))["status"] == "error"


def test_check_available_and_current(tmp_path):
    net, _ = release_net(tmp_path, "0.4.0")
    assert updater.check(current="0.3.0", get=net)["status"] == "available"
    assert updater.check(current="0.4.0", get=net)["status"] == "current"


def test_check_uses_short_timeout():
    seen = {}

    def get(url, timeout=None, accept=None):
        seen["t"] = timeout
        raise urllib.error.URLError("x")
    updater.check(get=get)
    assert seen["t"] <= 5


# ------------------------------------------------------------------ staging
def test_stage_verifies_and_writes_pending(home, tmp_path):
    net, rel = release_net(tmp_path, "0.4.0")
    info = updater.stage(rel, get=net)
    assert info["version"] == "0.4.0" and updater.pending_file().exists()
    assert updater.read_version(Path(info["root"])) == "0.4.0"


def test_stage_rejects_bad_checksum(home, tmp_path):
    net, rel = release_net(tmp_path, "0.4.0", tamper=True)
    with pytest.raises(updater.UpdateError, match="mismatch"):
        updater.stage(rel, get=net)
    assert not updater.pending_file().exists()


def test_zip_slip_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../escape.txt", "x")
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater._safe_extract(z, tmp_path / "out")


# ------------------------------------------------------------------ apply / backup / rollback
def _stage(home, tmp_path, **kw):
    net, rel = release_net(tmp_path, **kw)
    return updater.stage(rel, get=net)


def test_apply_success_preserves_user_data(home, tmp_path, install):
    # user config + state live in the per-user dir and must survive untouched
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("my: settings\n")
    (home / "state.json").write_text('{"pads": {"1:3": "808 kick"}}')
    (home / "controllers").mkdir()
    (home / "controllers" / "mine.yaml").write_text("id: mine\n")
    _stage(home, tmp_path, version="0.4.0")
    pip_calls = []
    r = updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: pip_calls.append(p) or True, log=lambda m: None)
    assert r == "applied"
    assert updater.read_version(install) == "0.4.0"
    assert (install / "run.sh").read_text() == "echo 0.4.0\n"
    assert (install / ".venv" / "marker").read_text() == "keep me"          # venv untouched
    assert (home / "config.yaml").read_text() == "my: settings\n"
    assert json.loads((home / "state.json").read_text())["pads"]["1:3"] == "808 kick"
    assert (home / "controllers" / "mine.yaml").exists()
    assert pip_calls == []                                                   # requirements unchanged
    backups = list((home / "updates" / "backups").iterdir())
    assert len(backups) == 1 and updater.read_version(backups[0]) == "0.3.0"
    assert not updater.pending_file().exists()


def test_apply_reinstalls_requirements_when_changed(home, tmp_path, install):
    _stage(home, tmp_path, version="0.4.0", req="mido\npyyaml\nnewdep\n")
    pip_calls = []
    updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: pip_calls.append(p) or True, log=lambda m: None)
    assert pip_calls == [install.resolve()]


def test_removed_files_are_removed_and_new_added(home, tmp_path, install):
    (install / "old_only.txt").write_text("gone in 0.4.0")
    _stage(home, tmp_path, version="0.4.0", extra={"NEW.txt": "hi"})
    updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: True, log=lambda m: None)
    assert not (install / "old_only.txt").exists() and (install / "NEW.txt").exists()


def test_rollback_when_self_test_fails(home, tmp_path, install):
    _stage(home, tmp_path, version="0.4.0")
    r = updater.apply_pending(install, self_test=lambda p: False, pip=lambda p: True, log=lambda m: None)
    assert r == "rolled_back"
    assert updater.read_version(install) == "0.3.0"
    assert (install / "run.sh").read_text() == "echo 0.3.0\n"
    assert (install / ".venv" / "marker").exists()
    assert not updater.pending_file().exists()
    assert json.loads((home / "updates" / "failed.json").read_text())["version"] == "0.4.0"


def test_rollback_when_pip_fails(home, tmp_path, install):
    _stage(home, tmp_path, version="0.4.0", req="brokenpkg\n")
    assert updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: False, log=lambda m: None) == "rolled_back"
    assert updater.read_version(install) == "0.3.0"


def test_windows_locked_file_defers_then_applies(home, tmp_path, install, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    _stage(home, tmp_path, version="0.4.0")
    state = {"n": 0}

    def locked_remove(p):
        state["n"] += 1
        if p.name == "voice_midi":
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        updater._remove(p)
    r = updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: True, remove=locked_remove, log=lambda m: None)
    assert r == "deferred"
    assert updater.read_version(install) == "0.3.0" and (install / "run.sh").exists()   # restored intact
    info = json.loads(updater.pending_file().read_text())
    assert info["attempts"] == 1                                                           # kept for next launch
    # next launch: lock is gone
    assert updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: True, log=lambda m: None) == "applied"
    assert updater.read_version(install) == "0.4.0"


def test_live_session_blocks_swap(home, tmp_path, install, monkeypatch):
    _stage(home, tmp_path, version="0.4.0")
    updater.session_lock().parent.mkdir(parents=True, exist_ok=True)
    updater.session_lock().write_text("424242")
    monkeypatch.setattr(updater, "_pid_alive", lambda pid: True)
    assert updater.apply_pending(install, self_test=lambda p: True, log=lambda m: None) == "deferred"
    assert updater.read_version(install) == "0.3.0" and updater.pending_file().exists()
    monkeypatch.setattr(updater, "_pid_alive", lambda pid: False)                         # stale lock
    assert updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: True, log=lambda m: None) == "applied"


def test_git_checkout_is_not_self_updated(home, tmp_path, install):
    (install / ".git").mkdir()
    _stage(home, tmp_path, version="0.4.0")
    assert updater.apply_pending(install, self_test=lambda p: True, log=lambda m: None) == "skipped"
    assert updater.apply_pending(install, self_test=lambda p: True, pip=lambda p: True, force=True,
                                 log=lambda m: None) == "applied"
    assert (install / ".git").is_dir()


def test_nothing_pending(home, install):
    assert updater.apply_pending(install, log=lambda m: None) == "none"


# ------------------------------------------------------------------ launch policy (never applies mid-session)
def test_on_launch_off_and_interval(home, tmp_path):
    net, _ = release_net(tmp_path)
    assert updater.on_launch({"updates": {"mode": "off"}}, True, get=net) == "skipped"
    assert net.calls == []
    updater._mark_checked({"latest": None})
    assert updater.on_launch({"updates": {"mode": "auto", "check_interval_hours": 24}}, True, get=net) == "skipped"
    assert net.calls == []


def test_env_kill_switch(home, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_MIDI_NO_UPDATE", "1")
    net, _ = release_net(tmp_path)
    assert updater.on_launch({"updates": {"mode": "auto"}}, True, get=net) == "skipped" and net.calls == []


def test_on_launch_auto_stages_but_does_not_apply(home, tmp_path, install):
    net, _ = release_net(tmp_path, "0.4.0")
    assert updater.on_launch({"updates": {"mode": "auto"}}, False, get=net, log=lambda m: None) == "staged"
    assert updater.pending_file().exists()
    assert updater.read_version(install) == "0.3.0"          # running install untouched


def test_on_launch_ask(home, tmp_path):
    net, _ = release_net(tmp_path, "0.4.0")
    assert updater.on_launch({"updates": {"mode": "ask"}}, False, get=net, log=lambda m: None) == "available"
    assert not updater.pending_file().exists()
    updater._write_json(updater.updates_dir() / "state.json", {"last_check": 0})
    assert updater.on_launch({"updates": {"mode": "ask"}}, True, get=net, ask=lambda q: "n", log=lambda m: None) == "declined"
    updater._write_json(updater.updates_dir() / "state.json", {"last_check": 0})
    assert updater.on_launch({"updates": {"mode": "ask"}}, True, get=net, ask=lambda q: "y", log=lambda m: None) == "staged"


def test_on_launch_offline_is_quiet(home):
    net = FakeNet({API: urllib.error.URLError("offline")})
    assert updater.on_launch({"updates": {"mode": "auto"}}, True, get=net, log=lambda m: None) == "error"


def test_known_bad_version_not_restaged(home, tmp_path):
    net, _ = release_net(tmp_path, "0.4.0")
    updater._write_json(updater.updates_dir() / "failed.json", {"version": "0.4.0"})
    assert updater.on_launch({"updates": {"mode": "auto"}}, True, get=net, log=lambda m: None) == "known_bad"


# ------------------------------------------------------------------ real end-to-end helper (subprocess, temp-dir copy)
def _copy_repo(dst: Path, version=None, break_parser=False):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "dist"))
    if version:
        init = dst / "voice_midi" / "__init__.py"
        init.write_text(init.read_text().replace(f'"{__version__}"', f'"{version}"'))
    if break_parser:
        (dst / "voice_midi" / "parser.py").write_text("def parse(:\n")
    return dst


@pytest.mark.parametrize("broken,expect_version,rc", [(False, "9.9.9", 0), (True, __version__, 1)])
def test_helper_end_to_end(home, tmp_path, broken, expect_version, rc):
    inst = _copy_repo(tmp_path / "inst")
    staged = _copy_repo(tmp_path / "staged", "9.9.9", break_parser=broken)
    updater._write_json(updater.pending_file(), {"version": "9.9.9", "root": str(staged), "attempts": 0})
    sys.path.insert(0, str(inst))
    try:
        assert updater.run_helper(inst) == rc
    finally:
        sys.path.remove(str(inst))
    assert updater.read_version(inst) == expect_version


# ------------------------------------------------------------------ controller profile refresh
def _raw(name):
    return updater.RAW_URL.format(repo=updater.REPO, ref="main", path="config/controllers/" + name)


def test_refresh_profiles(home, tmp_path):
    good = b"id: newpad\nname: New Pad\nport_match: [NewPad]\npads: {layout: list, notes: [36, 37, 38, 39, 40, 41, 42, 43]}\n"
    bad_yaml = b"id: broken\n"
    tampered = b"id: x\n"
    sums = "\n".join([f"{hashlib.sha256(good).hexdigest()}  newpad.yaml",
                      f"{hashlib.sha256(bad_yaml).hexdigest()}  broken.yaml",
                      f"{'0' * 64}  tampered.yaml",
                      f"{hashlib.sha256(good).hexdigest()}  ../escape.yaml"])
    net = FakeNet({_raw("SHA256SUMS"): sums.encode(), _raw("newpad.yaml"): good,
                   _raw("broken.yaml"): bad_yaml, _raw("tampered.yaml"): tampered})
    dest = home / "controllers"
    assert updater.refresh_profiles(get=net, log=lambda m: None) == ["newpad.yaml"]
    assert (dest / "newpad.yaml").read_bytes() == good
    assert not (dest / "broken.yaml").exists() and not (dest / "tampered.yaml").exists()
    assert not any("escape" in c for c in net.calls)
    net.calls.clear()
    assert updater.refresh_profiles(get=net, log=lambda m: None) == []          # unchanged -> not re-downloaded
    assert _raw("newpad.yaml") not in net.calls
    # the refreshed profile is picked up by the config loader
    from voice_midi.config import Config
    import yaml
    cfg = Config(yaml.safe_load((ROOT / "config" / "config.yaml").read_text()), home)
    assert "newpad" in cfg.profiles


def test_refresh_profiles_offline(home):
    assert updater.refresh_profiles(get=FakeNet({_raw("SHA256SUMS"): urllib.error.URLError("x")}), log=lambda m: None) == []


def test_repo_profile_sums_are_current():
    folder = ROOT / "config" / "controllers"
    sums = updater.parse_sums((folder / "SHA256SUMS").read_text())
    files = {p.name for p in folder.glob("*.yaml")}
    assert set(sums) == files, "run: python -c \"from voice_midi.updater import write_profile_sums; write_profile_sums('config/controllers')\""
    for name in files:
        assert updater.sha256_file(folder / name) == sums[name], f"{name} changed; regenerate SHA256SUMS"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
def test_extract_keeps_exec_bit(tmp_path):
    z = tmp_path / "r.zip"
    info = zipfile.ZipInfo("voice-midi/run.sh")
    info.external_attr = (0o100755 << 16)
    with zipfile.ZipFile(z, "w") as f:
        f.writestr(info, "#!/bin/sh\n")
    updater._safe_extract(z, tmp_path / "out")
    assert (tmp_path / "out" / "voice-midi" / "run.sh").stat().st_mode & 0o111
