"""Platform detection + per-OS defaults. Everything OS-specific lives here so
tests can monkeypatch `current()` (or sys.platform) to simulate Windows/macOS."""
import os
import sys
from pathlib import Path

APP = "voice-midi"

# Default virtual MIDI port the DAW listens to, per OS.
DEFAULT_OUT_PORT = {
    "mac": "IAC Driver Bus 1",       # Audio MIDI Setup > IAC Driver
    "windows": "loopMIDI Port",      # loopMIDI (Tobias Erichsen) default port name
    "linux": "voice-midi",           # ALSA virtual port created by rtmidi
}
VIRTUAL_PORT_HELP = {
    "mac": "Open Audio MIDI Setup > Window > Show MIDI Studio > double-click IAC Driver > tick 'Device is online'.",
    "windows": ("Install loopMIDI (https://www.tobias-erichsen.de/software/loopmidi.html), start it, "
                "type a port name (e.g. 'loopMIDI Port' or 'VoiceMIDI') and click '+'. "
                "Then set midi.out_port.windows in config.yaml to that name."),
    "linux": "rtmidi can create a virtual ALSA port; or use `modprobe snd-virmidi`.",
}


def current(platform=None) -> str:
    """'mac' | 'windows' | 'linux'."""
    p = platform or sys.platform
    if p == "darwin":
        return "mac"
    if p.startswith("win") or p == "cygwin":
        return "windows"
    return "linux"


def supports_virtual_ports(os_name=None) -> bool:
    """rtmidi can create virtual ports on CoreMIDI and ALSA, NOT on Windows MME."""
    return (os_name or current()) != "windows"


def pick(value, os_name=None):
    """Config values may be a plain value or a per-OS dict {mac:..., windows:..., linux:...}."""
    if isinstance(value, dict) and set(value) & {"mac", "windows", "linux", "default"}:
        os_name = os_name or current()
        return value.get(os_name, value.get("default"))
    return value


def user_dir(os_name=None) -> Path:
    """Per-user config/state dir:
    Windows: %APPDATA%\\voice-midi   macOS: ~/Library/Application Support/voice-midi
    Linux:   $XDG_CONFIG_HOME/voice-midi (~/.config/voice-midi)"""
    os_name = os_name or current()
    override = os.environ.get("VOICE_MIDI_HOME")
    if override:
        return Path(override).expanduser()
    if os_name == "windows":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP
    if os_name == "mac":
        return Path.home() / "Library" / "Application Support" / APP
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / APP


def state_file(os_name=None) -> Path:
    return user_dir(os_name) / "state.json"


def abletonosc_dir(os_name=None) -> Path:
    """Where Live looks for user Remote Scripts."""
    os_name = os_name or current()
    if os_name == "windows":
        return Path.home() / "Documents" / "Ableton" / "User Library" / "Remote Scripts"
    return Path.home() / "Music" / "Ableton" / "User Library" / "Remote Scripts"
