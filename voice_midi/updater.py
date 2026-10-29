"""Self-updater for voice-midi.

Flow
  check   : GET api.github.com/repos/<REPO>/releases/latest (unauthenticated, short timeout)
  stage   : download voice-midi-<ver>.zip + SHA256SUMS, verify, extract to <user_dir>/updates/staged/<ver>,
            write <user_dir>/updates/pending.json.  Never touches the running install.
  apply   : on the NEXT launch, before the app starts (launchers run `--apply-pending`):
            refuse if a live session holds the lock -> back up current files -> swap in staged files ->
            pip install if requirements.txt changed -> self-test (import + parser smoke) -> rollback on failure.
User config/state live in the per-user dir (%APPDATA%\\voice-midi, ~/Library/Application Support/voice-midi)
and are never part of the swap. `.venv` and `.git` in the install dir are never touched.

This file is importable as voice_midi.updater AND runnable as a standalone script copied to a temp dir
(the Windows-safe helper path), so it only depends on the standard library + platform_info.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    from . import platform_info
    from . import __version__ as CURRENT_VERSION, REPO
except ImportError:  # running as a standalone helper script
    import platform_info  # type: ignore  # copied next to this file
    CURRENT_VERSION, REPO = os.environ.get("VOICE_MIDI_VERSION", "0.0.0"), os.environ.get("VOICE_MIDI_REPO", "")

API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
TIMEOUT = 4.0
# Never backed up / replaced / deleted in the install dir
PROTECTED = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "dist", "build", ".DS_Store"}
SMOKE_TEST = ("import voice_midi, voice_midi.engine, voice_midi.cli; "
              "from voice_midi.parser import parse; "
              "assert parse('tempo one twenty eight').args['bpm'] == 128; "
              "assert parse('load 808 kick on pad 3').action == 'load_sound'; "
              "from voice_midi.config import load_config, DEFAULT_CONFIG; load_config(DEFAULT_CONFIG); "
              "print(voice_midi.__version__)")


class UpdateError(Exception):
    pass


class Deferred(UpdateError):
    """Swap couldn't happen now (file locked / live session) - pending update kept for next launch."""


# ------------------------------------------------------------------ versions
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(v: str):
    m = _SEMVER.match(v.strip())
    if not m:
        raise ValueError(f"not a semantic version: {v!r}")
    major, minor, patch, pre = m.groups()
    pre_key = () if pre is None else tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split("."))
    # releases sort after pre-releases of the same version
    return (int(major), int(minor), int(patch), 1 if pre is None else 0, pre_key)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# ------------------------------------------------------------------ paths & state
def updates_dir() -> Path:
    return platform_info.user_dir() / "updates"


def pending_file() -> Path:
    return updates_dir() / "pending.json"


def session_lock() -> Path:
    return platform_info.user_dir() / "session.lock"


def install_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ network
def http_get(url: str, timeout=TIMEOUT, accept="application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"voice-midi/{CURRENT_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_latest(repo=REPO, get=http_get, timeout=TIMEOUT):
    """Returns (release_dict | None, message). Never raises for network problems."""
    try:
        data = json.loads(get(API_LATEST.format(repo=repo), timeout=timeout))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            reset = e.headers.get("X-RateLimit-Reset") if e.headers else None
            when = f" (resets {time.strftime('%H:%M', time.localtime(int(reset)))})" if reset and reset.isdigit() else ""
            return None, f"GitHub rate limit hit{when}; will try again later"
        if e.code == 404:
            return None, "no published release yet"
        return None, f"update server error HTTP {e.code}"
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, f"offline or GitHub unreachable ({getattr(e, 'reason', e)})"
    except ValueError:
        return None, "bad response from GitHub"
    if data.get("draft") or data.get("prerelease"):
        return None, "latest release is a draft/pre-release; skipping"
    return data, "ok"


def check(current=CURRENT_VERSION, repo=REPO, get=http_get):
    """Returns dict(status=..., message=..., latest=..., release=...)."""
    rel, msg = fetch_latest(repo, get)
    if rel is None and msg == "no published release yet":
        return {"status": "none", "message": msg, "latest": None, "release": None}
    if rel is None:
        return {"status": "error", "message": msg, "latest": None, "release": None}
    tag = rel.get("tag_name", "")
    try:
        newer = is_newer(tag, current)
    except ValueError:
        return {"status": "error", "message": f"release tag {tag!r} isn't semver", "latest": None, "release": None}
    latest = tag.lstrip("v")
    if not newer:
        return {"status": "current", "message": f"up to date ({current})", "latest": latest, "release": rel}
    return {"status": "available", "message": f"update available: {current} -> {latest}", "latest": latest, "release": rel}


# ------------------------------------------------------------------ checksums
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_sums(text: str) -> dict:
    """sha256sum format: '<hex>  <name>' (also accepts '<hex> *<name>')."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[1].lstrip("*").strip()] = parts[0].lower()
    return out


def verify_checksum(path: Path, sums_text: str, name=None) -> str:
    name = name or Path(path).name
    sums = parse_sums(sums_text)
    if name not in sums:
        raise UpdateError(f"{name} is not listed in SHA256SUMS")
    actual = sha256_file(path)
    if actual != sums[name]:
        raise UpdateError(f"checksum mismatch for {name}: expected {sums[name][:12]}…, got {actual[:12]}…")
    return actual


# ------------------------------------------------------------------ staging
def _asset(rel, predicate):
    for a in rel.get("assets", []):
        if predicate(a.get("name", "")):
            return a
    return None


def _safe_extract(zpath: Path, dest: Path):
    dest = dest.resolve()
    with zipfile.ZipFile(zpath) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if dest not in target.parents and target != dest:
                raise UpdateError(f"unsafe path in zip: {member.filename}")
        z.extractall(dest)
        # zipfile drops Unix permissions; restore the executable bit (run.sh) where the zip recorded it
        for member in z.infolist():
            mode = (member.external_attr >> 16) & 0o777
            if mode & 0o111 and not member.is_dir():
                p = dest / member.filename
                p.chmod(p.stat().st_mode | 0o111)


def _find_root(extracted: Path) -> Path:
    if (extracted / "voice_midi" / "__init__.py").is_file():
        return extracted
    for child in extracted.iterdir():
        if child.is_dir() and (child / "voice_midi" / "__init__.py").is_file():
            return child
    raise UpdateError("release zip doesn't contain voice_midi/")


def read_version(root: Path) -> str:
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', (root / "voice_midi" / "__init__.py").read_text(encoding="utf-8"))
    if not m:
        raise UpdateError("no __version__ in staged release")
    return m.group(1)


def stage(release: dict, get=http_get, timeout=60.0) -> dict:
    """Download + verify + extract a release. Writes pending.json; does NOT touch the install."""
    tag = release["tag_name"]
    version = tag.lstrip("v")
    zip_a = _asset(release, lambda n: n.endswith(".zip") and n.startswith("voice-midi"))
    sums_a = _asset(release, lambda n: n in ("SHA256SUMS", "SHA256SUMS.txt"))
    if not zip_a or not sums_a:
        raise UpdateError("release is missing the zip or SHA256SUMS asset")
    work = updates_dir() / "staged" / version
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    zpath = work / zip_a["name"]
    zpath.write_bytes(get(zip_a["browser_download_url"], timeout=timeout, accept="application/octet-stream"))
    sums = get(sums_a["browser_download_url"], timeout=timeout, accept="application/octet-stream").decode("utf-8")
    digest = verify_checksum(zpath, sums, zip_a["name"])
    _safe_extract(zpath, work / "files")
    root = _find_root(work / "files")
    staged_version = read_version(root)
    if staged_version != version:
        raise UpdateError(f"tag {tag} but package says {staged_version}")
    info = {"version": version, "root": str(root), "sha256": digest, "staged_at": time.time(), "attempts": 0}
    _write_json(pending_file(), info)
    return info


# ------------------------------------------------------------------ live-session lock
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if platform_info.current() == "windows":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=5)
            return str(pid) in out.stdout
        except (OSError, subprocess.SubprocessError):
            return True  # can't tell -> be safe
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_session_lock():
    lock = session_lock()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def release_session_lock():
    lock = session_lock()
    try:
        if lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lock.unlink()
    except OSError:
        pass


def live_session_running() -> bool:
    try:
        pid = int(session_lock().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


# ------------------------------------------------------------------ apply / rollback
def _managed(dir_: Path):
    return sorted(p for p in dir_.iterdir() if p.name not in PROTECTED)


def _copy_entry(src: Path, dst: Path):
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*PROTECTED))
    else:
        shutil.copy2(src, dst)


def _remove(p: Path):
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def backup(install: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=False)
    for entry in _managed(install):
        _copy_entry(entry, dest / entry.name)
    return dest


def swap_in(src_root: Path, install: Path, remove=_remove, copy=_copy_entry):
    """Replace every managed entry of `install` with the contents of `src_root`."""
    for entry in _managed(install):
        remove(entry)
    for entry in _managed(src_root):
        copy(entry, install / entry.name)


def rollback(backup_dir: Path, install: Path):
    for entry in _managed(install):
        try:
            _remove(entry)
        except OSError:
            pass
    for entry in _managed(backup_dir):
        dst = install / entry.name
        if not dst.exists():
            _copy_entry(entry, dst)


def default_self_test(install: Path) -> bool:
    env = dict(os.environ, PYTHONPATH=str(install), VOICE_MIDI_NO_UPDATE="1")
    try:
        r = subprocess.run([sys.executable, "-c", SMOKE_TEST], cwd=str(install), env=env,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def default_pip(install: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(install / "requirements.txt")],
                       cwd=str(install))
    return r.returncode == 0


def _file_hash(p: Path):
    return sha256_file(p) if p.is_file() else None


def apply_pending(install: Path = None, self_test=default_self_test, pip=default_pip,
                  remove=_remove, force=False, log=print) -> str:
    """Returns 'none' | 'applied' | 'deferred' | 'rolled_back' | 'skipped'."""
    install = Path(install or install_dir()).resolve()
    info = _read_json(pending_file())
    if not info:
        return "none"
    root = Path(info["root"])
    if not (root / "voice_midi" / "__init__.py").is_file():
        log("voice-midi update: staged files missing; discarding pending update")
        pending_file().unlink(missing_ok=True)
        return "none"
    if (install / ".git").exists() and not force:
        log("voice-midi update: this is a git checkout - not self-updating (use `git pull`, or --force)")
        return "skipped"
    if live_session_running():
        log("voice-midi update: a live session is running - update stays pending until next launch")
        return "deferred"
    old_version = read_version(install) if (install / "voice_midi" / "__init__.py").is_file() else "unknown"
    old_req = _file_hash(install / "requirements.txt")
    bdir = updates_dir() / "backups" / f"{old_version}-{time.strftime('%Y%m%d-%H%M%S')}"
    if bdir.exists():
        shutil.rmtree(bdir)
    backup(install, bdir)
    log(f"voice-midi update: {old_version} -> {info['version']} (backup: {bdir})")
    try:
        swap_in(root, install, remove=remove)
    except PermissionError as e:   # typical on Windows: a file is open in another process
        rollback(bdir, install)
        info["attempts"] = info.get("attempts", 0) + 1
        _write_json(pending_file(), info)
        log(f"voice-midi update: files in use ({e}); restored {old_version}, will retry next launch")
        return "deferred"
    ok = True
    if _file_hash(install / "requirements.txt") != old_req:
        log("voice-midi update: requirements changed - installing")
        ok = pip(install)
    ok = ok and self_test(install)
    if not ok:
        rollback(bdir, install)
        if old_req != _file_hash(install / "requirements.txt"):
            pip(install)
        pending_file().unlink(missing_ok=True)
        _write_json(updates_dir() / "failed.json", {"version": info["version"], "at": time.time()})
        log(f"voice-midi update: {info['version']} failed its self-test - rolled back to {old_version}")
        return "rolled_back"
    pending_file().unlink(missing_ok=True)
    shutil.rmtree(root.parent.parent if root.parent.name == "files" else root, ignore_errors=True)
    _prune_backups(keep=2)
    log(f"voice-midi update: now running {info['version']}")
    return "applied"


def _prune_backups(keep=2):
    b = updates_dir() / "backups"
    if b.is_dir():
        for old in sorted(b.iterdir(), key=lambda p: p.stat().st_mtime)[:-keep]:
            shutil.rmtree(old, ignore_errors=True)


def run_helper(install: Path = None) -> int:
    """Windows-safe apply: copy this module (+platform_info) to a temp dir and run it from there,
    so nothing under the install dir is executing while files are swapped."""
    install = Path(install or install_dir())
    tmp = Path(tempfile.mkdtemp(prefix="voice-midi-update-"))
    here = Path(__file__).resolve().parent
    shutil.copy2(here / "updater.py", tmp / "updater.py")
    shutil.copy2(here / "platform_info.py", tmp / "platform_info.py")
    env = dict(os.environ, VOICE_MIDI_VERSION=CURRENT_VERSION, VOICE_MIDI_REPO=REPO)
    try:
        return subprocess.run([sys.executable, str(tmp / "updater.py"), "--apply-pending",
                              "--install-dir", str(install)], env=env, cwd=str(tmp)).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ launch-time policy
def settings(cfg_data: dict) -> dict:
    u = dict(mode="ask", check_interval_hours=24, profiles=False, profiles_ref="main")
    u.update((cfg_data or {}).get("updates") or {})
    if os.environ.get("VOICE_MIDI_NO_UPDATE") == "1":
        u["mode"] = "off"
    return u


def due(interval_hours: float, now=None) -> bool:
    st = _read_json(updates_dir() / "state.json", {}) or {}
    return (now or time.time()) - st.get("last_check", 0) >= interval_hours * 3600


def _mark_checked(result):
    _write_json(updates_dir() / "state.json", {"last_check": time.time(), "latest": result.get("latest"),
                                               "message": result.get("message")})


def on_launch(cfg_data: dict, interactive: bool, get=http_get, ask=input, log=print, now=None) -> str:
    """Called at app start. Only ever STAGES; the swap happens on the next launch."""
    s = settings(cfg_data)
    if s["mode"] == "off" or not due(float(s["check_interval_hours"]), now):
        return "skipped"
    if pending_file().exists():
        return "pending"
    res = check(get=get)
    _mark_checked(res)
    if res["status"] != "available":
        return res["status"]
    failed = _read_json(updates_dir() / "failed.json", {}) or {}
    if failed.get("version") == res["latest"]:
        return "known_bad"
    if s["mode"] == "ask":
        if not interactive:
            log(f"voice-midi: {res['message']} - run `python -m voice_midi --update`")
            return "available"
        if ask(f"voice-midi: {res['message']}. Download now and install on next launch? [y/N] ").strip().lower() not in ("y", "yes"):
            return "declined"
    try:
        stage(res["release"], get=get)
    except (UpdateError, urllib.error.URLError, OSError) as e:
        log(f"voice-midi: couldn't download update ({e})")
        return "error"
    log(f"voice-midi: {res['latest']} downloaded and verified - it will be installed next time you start voice-midi")
    return "staged"


# ------------------------------------------------------------------ controller-profile refresh
def refresh_profiles(repo=REPO, ref="main", get=http_get, dest=None, log=print) -> list:
    """Opt-in: pull new/changed controller profiles listed in config/controllers/SHA256SUMS of the repo.
    Each file is verified against that list and must parse as a profile before it is saved to
    <user_dir>/controllers (which overrides built-ins). Returns the names updated."""
    dest = Path(dest or platform_info.user_dir() / "controllers")
    base = "config/controllers/"
    try:
        sums = parse_sums(get(RAW_URL.format(repo=repo, ref=ref, path=base + "SHA256SUMS"), timeout=TIMEOUT,
                              accept="text/plain").decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        log(f"voice-midi: profile refresh skipped ({e})")
        return []
    updated = []
    for name, digest in sorted(sums.items()):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.yaml", name) or name.startswith("_"):
            continue
        target = dest / name
        if target.is_file() and sha256_file(target) == digest:
            continue
        try:
            blob = get(RAW_URL.format(repo=repo, ref=ref, path=base + name), timeout=TIMEOUT, accept="text/plain")
        except (urllib.error.URLError, OSError) as e:
            log(f"voice-midi: couldn't fetch {name} ({e})")
            continue
        if hashlib.sha256(blob).hexdigest() != digest:
            log(f"voice-midi: checksum mismatch for profile {name}; ignored")
            continue
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / (name + ".tmp")
        tmp.write_bytes(blob)
        try:
            from voice_midi.config import load_profile
            load_profile(tmp)
        except Exception as e:  # invalid profile -> don't install it
            tmp.unlink(missing_ok=True)
            log(f"voice-midi: profile {name} failed validation ({e}); ignored")
            continue
        os.replace(tmp, target)
        updated.append(name)
    return updated


def write_profile_sums(folder: Path) -> Path:
    """Maintainer tool: regenerate config/controllers/SHA256SUMS."""
    lines = [f"{sha256_file(p)}  {p.name}" for p in sorted(Path(folder).glob("*.yaml"))]
    out = Path(folder) / "SHA256SUMS"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="voice_midi.updater")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--update", action="store_true", help="check, download+verify, apply now")
    ap.add_argument("--apply-pending", action="store_true", help="apply a staged update in-process")
    ap.add_argument("--apply-pending-safe", action="store_true",
                    help="apply a staged update from a temp-dir copy of this helper (what the launchers use)")
    ap.add_argument("--install-dir")
    ap.add_argument("--force", action="store_true", help="allow updating a git checkout")
    a = ap.parse_args(argv)
    install = Path(a.install_dir) if a.install_dir else None
    if a.apply_pending_safe:
        return run_helper(install) if pending_file().exists() else 0
    if a.apply_pending:
        r = apply_pending(install, force=a.force)
        return 1 if r == "rolled_back" else 0
    if a.check or a.update:
        res = check()
        print(res["message"])
        if a.update and res["status"] == "available":
            try:
                stage(res["release"])
            except (UpdateError, OSError) as e:
                print(f"download failed: {e}")
                return 1
            print({"applied": "updated", "none": "nothing to apply"}.get(apply_pending(install, force=a.force), "see above"))
        return 0 if res["status"] != "error" else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
