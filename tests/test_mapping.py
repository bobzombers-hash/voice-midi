import sys
from pathlib import Path

import mido
import pytest

from voice_midi.config import load_config, load_profiles
from voice_midi.engine import Engine

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def engine():
    return Engine(load_config(ROOT / "config" / "config.yaml"), dry_run=True)


def test_all_profiles_load():
    profs = load_profiles(ROOT / "config" / "controllers")
    for pid in ["push2", "push3", "launchpad_x", "launchpad_mini_mk3", "apc40_mk2",
                "apc_mini_mk2", "mpk_mini", "maschine"]:
        assert pid in profs
    for p in profs.values():
        assert p.pad_count >= 8
        assert len(set(p.pad_notes)) == p.pad_count, f"{p.id} has duplicate pad notes"
        assert all(0 <= n <= 127 for n in p.pad_notes)
        if p.led.get("supported"):
            assert "off" in p.led["colors"]


def test_grid_layouts():
    profs = load_profiles(ROOT / "config" / "controllers")
    lp = profs["launchpad_x"]
    assert lp.note_for_pad(1) == 11 and lp.note_for_pad(8) == 18 and lp.note_for_pad(9) == 21
    assert lp.note_for_pad(64) == 88
    assert profs["push2"].note_for_pad(1) == 36 and profs["push2"].note_for_pad(64) == 99
    assert lp.pad_for_note(21) == 9
    with pytest.raises(ValueError):
        lp.note_for_pad(65)


def test_resolve_controller_and_sound(engine):
    cfg = engine.cfg
    assert cfg.resolve_controller(None)[0] == 1
    assert cfg.resolve_controller(2)[1].id == "push2"
    assert cfg.resolve_controller("launchpad")[0] == 1
    assert cfg.resolve_controller("right")[0] == 2
    with pytest.raises(ValueError):
        cfg.resolve_controller(3)
    assert cfg.resolve_sound("eight oh eight").name == "808 kick"
    assert cfg.resolve_sound("hi hat").name == "closed hat"
    assert cfg.resolve_sound("snair").name == "snare"     # fuzzy
    assert cfg.resolve_sound("banana") is None


def test_load_and_trigger_maps_to_iac(engine):
    engine.out.sent.clear()
    msg = engine.run_text("put the snare on controller two pad five")
    assert "controller 2" in msg
    assert engine.pads[(2, 5)] == "snare"
    # controller 2 pad 5 -> 36 + 32 + 4 = 72
    addr, args = engine.osc["ableton"].sent[-1]
    assert addr == "/voicemidi/drumpad/load_browser" and args == [0, 72, "Snare 909"]
    # LED on Push 2 pad 5 (note 40) set to 'loaded'
    led = engine.led_ports[2].sent[-1]
    assert (led.type, led.note, led.velocity) == ("note_on", 40, 122)
    engine.run_text("hit pad 5 on controller 2")
    on, off = engine.out.sent[-2:]
    assert (on.type, on.note, off.type) == ("note_on", 72, "note_off")


def test_hardware_pad_forwarding(engine):
    engine.out.sent.clear()
    pad = engine.handle_hardware(1, mido.Message("note_on", note=21, velocity=90))  # launchpad pad 9
    assert pad == 9
    m = engine.out.sent[-1]
    assert (m.note, m.velocity) == (36 + 8, 90)
    assert engine.handle_hardware(1, mido.Message("control_change", control=1)) is None


def test_ableton_osc_commands(engine):
    o = engine.osc["ableton"]
    engine.run_text("arm track 2"); assert o.sent[-1] == ("/live/track/set/arm", [1, 1])
    engine.run_text("play scene 1"); assert o.sent[-1] == ("/live/scene/fire", [0])
    engine.run_text("tempo one twenty eight"); assert o.sent[-1] == ("/live/song/set/tempo", [128.0])
    engine.run_text("stop"); assert o.sent[-1] == ("/live/song/stop_playing", [])
    engine.run_text("next preset")
    m = engine.out.sent[-1]
    assert m.type == "control_change" and m.control == 102


def test_logic_target_is_honest(engine, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    engine.run_text("switch to logic")
    engine.run_text("play")
    assert engine.out.sent[-1].type == "sysex" and list(engine.out.sent[-1].data) == [0x7F, 0x7F, 0x06, 0x02]
    assert "LIMITED" in engine.run_text("load clap on pad 2")
    assert "LIMITED" in engine.run_text("tempo 120")
    assert "not supported" in engine.run_text("undo")


def test_autopilot_osc(engine):
    engine.run_text("switch to autopilot")
    o = engine.osc["autopilot"]
    engine.run_text("tempo 126"); assert o.sent[-1] == ("/AutoPilot/Header/BPM", [126.0])
    engine.run_text("play deck 2"); assert o.sent[-1] == ("/AutoPilot/Deck/2/Playing", [1])
    engine.run_text("cue 3 on deck 1"); assert o.sent[-1] == ("/AutoPilot/Deck/1/Cue3", [1])


def test_errors_are_friendly(engine):
    assert engine.run_text("hit pad 99").startswith("!")
    assert engine.run_text("load banana on pad 1").startswith("!")
    assert engine.run_text("blorp").startswith("?")


def test_state_persists(tmp_path):
    cfg = load_config(ROOT / "config" / "config.yaml")
    st = tmp_path / "state.json"
    Engine(cfg, dry_run=True, state_path=st).run_text("load kick on pad 1")
    assert Engine(cfg, dry_run=True, state_path=st).pads[(1, 1)] == "kick"
