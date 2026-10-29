"""Build dist/voice-midi-<version>.zip + dist/SHA256SUMS (used by .github/workflows/release.yml).

    python tools/build_release.py [--tag v0.3.0]
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_midi import __version__  # noqa: E402
from voice_midi.updater import write_profile_sums  # noqa: E402

EXCLUDE_DIRS = {".venv", "venv", ".git", ".github", "__pycache__", ".pytest_cache", "dist", "build"}
EXCLUDE_FILES = {".DS_Store"}


def files():
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or p.name in EXCLUDE_FILES or p.suffix == ".pyc":
            continue
        if p.is_file():
            yield p, rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="git tag being released; must equal v<__version__>")
    a = ap.parse_args()
    if a.tag and a.tag.lstrip("v") != __version__:
        sys.exit(f"tag {a.tag} does not match voice_midi.__version__ {__version__}")
    # profile checksums must be current, or the profile refresher would reject files
    sums = (ROOT / "config" / "controllers" / "SHA256SUMS")
    before = sums.read_text(encoding="utf-8") if sums.exists() else ""
    if write_profile_sums(ROOT / "config" / "controllers").read_text(encoding="utf-8") != before:
        print("note: regenerated config/controllers/SHA256SUMS - commit it")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = f"voice-midi-{__version__}.zip"
    zpath = dist / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in files():
            z.write(p, Path("voice-midi") / rel)
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(f"{digest}  {name}\n", encoding="utf-8", newline="\n")
    print(f"built {zpath} sha256={digest}")


if __name__ == "__main__":
    main()
