"""Config + controller-profile loading, sound alias resolution."""
import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import platform_info
from .numbers import normalize_numbers

PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PKG_ROOT / "config" / "config.yaml"
BUILTIN_CONTROLLERS = PKG_ROOT / "config" / "controllers"


@dataclass
class ControllerProfile:
    id: str
    name: str
    port_match: list
    pad_notes: list                  # index 0 -> pad 1
    input_channel: int = 0
    aliases: list = field(default_factory=list)
    led: dict = field(default_factory=dict)
    init_sysex: list = field(default_factory=list)
    verified: bool = False

    @property
    def pad_count(self):
        return len(self.pad_notes)

    def note_for_pad(self, pad: int) -> int:
        if not 1 <= pad <= self.pad_count:
            raise ValueError(f"{self.name} has pads 1-{self.pad_count}, not {pad}")
        return self.pad_notes[pad - 1]

    def pad_for_note(self, note: int):
        try:
            return self.pad_notes.index(note) + 1
        except ValueError:
            return None

    def led_color(self, state: str):
        if not self.led.get("supported"):
            return None
        return self.led.get("colors", {}).get(state)


def _pad_notes(pads: dict) -> list:
    layout = pads.get("layout", "list")
    if layout == "list":
        return [int(n) for n in pads["notes"]]
    if layout == "grid":
        base, rows, cols = pads["base_note"], pads["rows"], pads["cols"]
        stride = pads.get("row_stride", cols)
        return [base + r * stride + c for r in range(rows) for c in range(cols)]
    raise ValueError(f"unknown pad layout {layout!r}")


def load_profile(path) -> ControllerProfile:
    d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for k in ("id", "name", "port_match", "pads"):
        if k not in d:
            raise ValueError(f"{path}: missing required key {k!r}")
    return ControllerProfile(
        id=d["id"], name=d["name"], port_match=list(d["port_match"]),
        pad_notes=_pad_notes(d["pads"]), input_channel=int(d.get("input_channel", 0)),
        aliases=[a.lower() for a in d.get("aliases", [])], led=_fix_led(d.get("led") or {}),
        init_sysex=d.get("init_sysex") or [], verified=bool(d.get("verified", False)))


def load_profiles(directory) -> dict:
    out = {}
    for p in sorted(Path(directory).glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        prof = load_profile(p)
        out[prof.id] = prof
    return out


@dataclass
class Sound:
    name: str
    file: str = None
    browser: str = None
    logic_patch: str = None


class Config:
    def __init__(self, data: dict, base_dir: Path):
        self.data = data
        self.base_dir = base_dir
        cdir = Path(data.get("controllers_dir", "controllers")).expanduser()
        self.controllers_dir = cdir if cdir.is_absolute() else base_dir / cdir
        # built-in profiles first, then the user's own (same id overrides)
        self.profiles = load_profiles(BUILTIN_CONTROLLERS)
        if self.controllers_dir.is_dir() and self.controllers_dir.resolve() != BUILTIN_CONTROLLERS.resolve():
            self.profiles.update(load_profiles(self.controllers_dir))
        self.rig = []          # list of (profile, extra_aliases), index 0 = controller 1
        for entry in data.get("controllers", []):
            cid = entry["id"] if isinstance(entry, dict) else entry
            if cid not in self.profiles:
                raise ValueError(f"controller {cid!r} has no profile in {self.controllers_dir}")
            extra = [a.lower() for a in (entry.get("aliases", []) if isinstance(entry, dict) else [])]
            self.rig.append((self.profiles[cid], extra))
        self.sounds = {}
        self._sound_phrases = {}
        for name, spec in (data.get("sounds") or {}).items():
            spec = spec or {}
            f = platform_info.pick(spec.get("file"))
            s = Sound(name, str(Path(f).expanduser()) if f else None, spec.get("browser"), spec.get("logic_patch"))
            self.sounds[name] = s
            for phrase in [name] + list(spec.get("say", [])):
                self._sound_phrases[normalize_numbers(str(phrase))] = s

    # -- sections -----------------------------------------------------------
    @property
    def midi(self):
        return self.data.get("midi", {})

    def target(self, name):
        return (self.data.get("targets") or {}).get(name, {})

    @property
    def default_target(self):
        return self.data.get("default_target", "ableton")

    @property
    def speech(self):
        return self.data.get("speech", {})

    # -- lookups ------------------------------------------------------------
    def resolve_controller(self, ref=None):
        """ref: None (default), 1-based int, or a spoken name/alias. Returns (index, profile)."""
        if ref is None:
            ref = int(self.data.get("default_controller", 1))
        if not self.rig:
            raise ValueError("no controllers configured")
        if isinstance(ref, int):
            if not 1 <= ref <= len(self.rig):
                raise ValueError(f"controller {ref} not configured (have {len(self.rig)})")
            return ref, self.rig[ref - 1][0]
        ref = ref.lower().strip()
        for i, (prof, extra) in enumerate(self.rig, 1):
            if ref in extra or ref in prof.aliases or ref == prof.id or ref == prof.name.lower():
                return i, prof
        raise ValueError(f"no configured controller called {ref!r}")

    def resolve_sound(self, spoken: str, cutoff=0.6):
        key = normalize_numbers(spoken)
        if key in self._sound_phrases:
            return self._sound_phrases[key]
        match = difflib.get_close_matches(key, list(self._sound_phrases), n=1, cutoff=cutoff)
        return self._sound_phrases[match[0]] if match else None


def find_config(path=None) -> Path:
    if path:
        return Path(path).expanduser()
    env = os.environ.get("VOICE_MIDI_CONFIG")
    if env:
        return Path(env).expanduser()
    user = platform_info.user_dir() / "config.yaml"
    return user if user.is_file() else DEFAULT_CONFIG


def load_config(path=None) -> Config:
    path = find_config(path)
    return Config(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, path.parent)


def _fix_led(led: dict) -> dict:
    """YAML 1.1 turns a bare `off:` key into False; map it back."""
    cols = led.get("colors")
    if cols and False in cols:
        cols["off"] = cols.pop(False)
    return led
