"""Simulated-Windows tests: monkeypatch sys.platform / APPDATA, fake mido port lists."""
import sys
from pathlib import Path

import pytest

from voice_midi import platform_info
from voice_midi.config import load_config
from voice_midi.engine import Engine
from voice_midi.outputs import keys
from voice_midi.outputs.targets import LOGIC_MAC_ONLY
from voice_midi.outputs.transport import (VirtualPortMissing, choose_port, open_midi_out,
                                          resolve_out_port_name)

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "config.yaml"


class FakeMido:
    def __init__(self, outputs):
        self.outputs, self.opened = outputs, []

    def get_output_names(self):
        return list(self.outputs)

    def open_output(self, name=None, virtual=False):
        self.opened.append((name, virtual))
        return f"port:{name}"


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.delenv("VOICE_MIDI_HOME", raising=False)
    return tmp_path


@pytest.mark.parametrize("plat,expected", [("win32", "windows"), ("cygwin", "windows"),
                                           ("darwin", "mac"), ("linux", "linux")])
def test_detect(plat, expected):
    assert platform_info.current(plat) == expected


def test_default_port_names(windows):
    assert resolve_out_port_name("auto") == "loopMIDI Port"
    assert resolve_out_port_name(None) == "loopMIDI Port"
    assert resolve_out_port_name({"mac": "IAC Driver Bus 1", "windows": "VoiceMIDI"}) == "VoiceMIDI"
    assert resolve_out_port_name({"mac": "IAC Driver Bus 1", "windows": "VoiceMIDI"}, "mac") == "IAC Driver Bus 1"
    assert resolve_out_port_name("My Port") == "My Port"


def test_bundled_config_picks_loopmidi_on_windows(windows):
    cfg = load_config(CFG)
    assert resolve_out_port_name(cfg.midi["out_port"]) == "loopMIDI Port"


def test_windows_port_selection_substring(windows):
    # Windows MME names loopMIDI ports like "loopMIDI Port 1"
    fake = FakeMido(["Microsoft GS Wavetable Synth 0", "loopMIDI Port 1", "Launchpad X 2"])
    assert open_midi_out("auto", mido_mod=fake) == "port:loopMIDI Port 1"
    assert fake.opened == [("loopMIDI Port 1", False)]
    assert choose_port("voicemidi", ["VoiceMIDI 3"]) == "VoiceMIDI 3"


def test_windows_missing_port_is_clear_error(windows):
    fake = FakeMido(["Microsoft GS Wavetable Synth 0"])
    with pytest.raises(VirtualPortMissing) as e:
        open_midi_out("auto", mido_mod=fake)
    msg = str(e.value)
    assert "loopMIDI Port" in msg and "loopmidi" in msg.lower() and "Microsoft GS" in msg
    assert fake.opened == []          # never tries a virtual port on Windows


def test_mac_still_falls_back_to_virtual(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    fake = FakeMido([])
    open_midi_out("auto", mido_mod=fake)
    assert fake.opened == [("voice-midi", True)]
    fake2 = FakeMido(["IAC Driver Bus 1"])
    assert open_midi_out({"mac": "IAC Driver Bus 1", "windows": "x"}, mido_mod=fake2) == "port:IAC Driver Bus 1"


def test_paths_windows(windows):
    d = platform_info.user_dir()
    assert d == windows / "AppData" / "Roaming" / "voice-midi"
    assert platform_info.state_file() == d / "state.json"
    assert platform_info.abletonosc_dir().parts[-4:] == ("Documents", "Ableton", "User Library", "Remote Scripts")


def test_paths_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("VOICE_MIDI_HOME", raising=False)
    assert platform_info.user_dir().parts[-3:] == ("Library", "Application Support", "voice-midi")
    assert platform_info.abletonosc_dir().parts[-4:] == ("Music", "Ableton", "User Library", "Remote Scripts")


def test_user_config_in_appdata_is_preferred(windows):
    from voice_midi.cli import init_user_config
    from voice_midi.config import find_config
    assert find_config() == ROOT / "config" / "config.yaml"     # nothing in %APPDATA% yet
    init_user_config()
    user_cfg = platform_info.user_dir() / "config.yaml"
    assert user_cfg.is_file() and find_config() == user_cfg
    cfg = load_config()                                           # loads from %APPDATA%, built-in profiles still found
    assert "push2" in cfg.profiles and cfg.resolve_controller(2)[1].id == "push2"


def test_state_file_under_appdata(windows):
    st = platform_info.state_file()
    Engine(load_config(CFG), dry_run=True, state_path=st).run_text("load kick on pad 1")
    assert st.is_file()
    assert Engine(load_config(CFG), dry_run=True, state_path=st).pads[(1, 1)] == "kick"


def test_logic_blocked_on_windows(windows):
    e = Engine(load_config(CFG), dry_run=True)
    assert "macOS-only" in e.run_text("switch to logic")
    assert e.target_name == "ableton"
    # even if forced, the Logic target sends nothing (no MMC sysex, no CC, no keystrokes)
    e.target_name = "logic"
    e.out.sent.clear()
    for cmd in ["play", "stop", "record", "next preset", "tempo 120", "arm track 1"]:
        assert e.run_text(cmd) == LOGIC_MAC_ONLY
    assert e.out.sent == []


def test_logic_default_target_falls_back_on_windows(windows):
    cfg = load_config(CFG)
    cfg.data["default_target"] = "logic"
    assert Engine(cfg, dry_run=True).target_name == "ableton"


def test_ableton_and_autopilot_work_on_windows(windows):
    e = Engine(load_config(CFG), dry_run=True)
    e.run_text("tempo 128")
    assert e.osc["ableton"].sent[-1] == ("/live/song/set/tempo", [128.0])
    e.run_text("switch to autopilot")
    e.run_text("play deck 1")
    assert e.osc["autopilot"].sent[-1] == ("/AutoPilot/Deck/1/Playing", [1])


def test_keystrokes_cross_platform(windows, monkeypatch):
    assert keys.parse_combo("ctrl+shift+]") == (["ctrl", "shift"], "]")
    assert keys.parse_combo("]") == ([], "]")
    assert "dry-run" in keys.send_keys("ctrl+]", dry_run=True)
    # without pynput installed, Windows gives a friendly hint instead of crashing
    monkeypatch.setitem(sys.modules, "pynput", None)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", None)
    assert "pip install pynput" in keys.send_keys("ctrl+]")


def test_ableton_key_commands_pick_windows_combo(windows):
    cfg = load_config(CFG)
    cfg.data["targets"]["ableton"]["key_commands"]["enabled"] = True
    e = Engine(cfg, dry_run=True)
    assert e.run_text("next preset") == "(dry-run) would press ctrl+shift+]"
