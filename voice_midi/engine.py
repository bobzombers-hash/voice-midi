"""Engine: owns pad assignments, target selection, LED feedback, and the
physical-pad -> IAC forwarding. Commands come from parser.parse()."""
import json
import logging
from pathlib import Path

import mido

from .outputs.targets import TARGETS
from . import platform_info
from .outputs.transport import DryMidiPort, DryOsc, find_port, open_midi_out, open_osc
from .parser import Command, ParseError, parse

log = logging.getLogger("voice_midi")


class Engine:
    def __init__(self, cfg, dry_run=True, state_path=None):
        self.cfg, self.dry_run = cfg, dry_run
        self.state_path = Path(state_path) if state_path else None
        self.out = open_midi_out(cfg.midi.get("out_port", "auto"), dry_run=dry_run)
        self.osc = {}
        for name in TARGETS:
            o = cfg.target(name).get("osc")
            if o and o.get("enabled"):
                self.osc[name] = open_osc(o.get("host", "127.0.0.1"), o["port"], dry_run, name)
        self.targets = {n: cls(cfg, self.out, self.osc.get(n) or DryOsc(n), dry_run=dry_run) for n, cls in TARGETS.items()}
        self.os_name = platform_info.current()
        self.target_name = cfg.default_target
        if self.target_name == "logic" and self.os_name != "mac":
            log.warning("default_target is logic but Logic is macOS-only; using ableton")
            self.target_name = "ableton"
        # pads[(controller_index, pad)] = sound name
        self.pads = {}
        self.led_ports = {}   # controller_index -> output port for LEDs
        self._load_state()
        self._open_controller_outputs()

    # ---------------------------------------------------------------- state
    def _load_state(self):
        if self.state_path and self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            self.pads = {(int(k.split(":")[0]), int(k.split(":")[1])): v for k, v in raw.get("pads", {}).items()}

    def _save_state(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"pads": {f"{c}:{p}": s for (c, p), s in self.pads.items()}}, indent=1))

    @property
    def target(self):
        return self.targets[self.target_name]

    # ---------------------------------------------------------------- LEDs
    def _open_controller_outputs(self):
        names = [] if self.dry_run else mido.get_output_names()
        for i, (prof, _) in enumerate(self.cfg.rig, 1):
            if self.dry_run:
                self.led_ports[i] = DryMidiPort(f"LED {prof.id}")
            else:
                n = find_port(prof.port_match, names)
                if not n:
                    log.warning("controller %d (%s) output not found; LED feedback off", i, prof.name)
                    continue
                try:
                    self.led_ports[i] = mido.open_output(n)
                except Exception as e:  # Windows: port held exclusively by another app
                    log.warning("controller %d (%s) output %r busy (%s); LED feedback off. "
                                "On Windows, disable this controller in the DAW's MIDI prefs.", i, prof.name, n, e)
                    continue
            for sx in prof.init_sysex:
                self.led_ports[i].send(mido.Message("sysex", data=sx))
            self.refresh_leds(i)

    def set_led(self, ci, pad, state):
        _, prof = self.cfg.resolve_controller(ci)
        color = prof.led_color(state)
        port = self.led_ports.get(ci)
        if color is None or port is None:
            return
        port.send(mido.Message("note_on", channel=int(prof.led.get("channel", 0)),
                               note=prof.note_for_pad(pad), velocity=int(color)))

    def refresh_leds(self, ci):
        for (c, p) in self.pads:
            if c == ci:
                self.set_led(ci, p, "loaded")

    # ---------------------------------------------------------------- pads
    def iac_note(self, ci, pad):
        """Where a controller pad lands on the IAC bus: (channel, note)."""
        m = self.cfg.midi
        base = int(m.get("drum_base_note", 36))
        offset = int(m.get("controller_note_offset", 32))
        ch = (ci - 1) % 16 if m.get("per_controller_channel", False) else int(m.get("out_channel", 0))
        note = base + (ci - 1) * offset + pad - 1
        if not 0 <= note <= 127:
            raise ValueError(f"controller {ci} pad {pad} maps to note {note}, outside MIDI range; lower drum_base_note/controller_note_offset")
        return ch, note

    def trigger_pad(self, ci, pad, velocity=100, release=True):
        ch, note = self.iac_note(ci, pad)
        self.out.send(mido.Message("note_on", channel=ch, note=note, velocity=velocity))
        self.set_led(ci, pad, "playing")
        if release:
            self.out.send(mido.Message("note_off", channel=ch, note=note, velocity=0))
            self.set_led(ci, pad, "loaded" if (ci, pad) in self.pads else "off")
        return ch, note

    def handle_hardware(self, ci, msg):
        """Forward a physical pad press from controller ci to the IAC bus."""
        _, prof = self.cfg.resolve_controller(ci)
        if msg.type not in ("note_on", "note_off"):
            return None
        pad = prof.pad_for_note(msg.note)
        if pad is None:
            return None
        ch, note = self.iac_note(ci, pad)
        on = msg.type == "note_on" and msg.velocity > 0
        self.out.send(mido.Message("note_on" if on else "note_off", channel=ch, note=note,
                                   velocity=msg.velocity if on else 0))
        self.set_led(ci, pad, "playing" if on else ("loaded" if (ci, pad) in self.pads else "off"))
        return pad

    # ---------------------------------------------------------------- commands
    def run_text(self, text):
        try:
            cmd = parse(text)
        except ParseError as e:
            return f"? {e}"
        try:
            return self.execute(cmd)
        except ValueError as e:
            return f"! {e}"

    def execute(self, cmd: Command):
        a, g, t = cmd.action, cmd.args, self.target
        if a == "load_sound":
            sound = self.cfg.resolve_sound(g["sound"])
            if sound is None:
                return f"! no sound alias matches '{g['sound']}' (add it under sounds: in config.yaml)"
            if "track" in g:
                return t.load_to_slot(sound, g["track"], g.get("slot", 1))
            ci, prof = self.cfg.resolve_controller(g.get("controller"))
            prof.note_for_pad(g["pad"])  # range check
            ch, note = self.iac_note(ci, g["pad"])
            self.pads[(ci, g["pad"])] = sound.name
            self._save_state()
            self.set_led(ci, g["pad"], "loaded")
            res = t.load_to_pad(sound, g["pad"], note)
            return f"'{sound.name}' -> controller {ci} ({prof.name}) pad {g['pad']} [out ch{ch + 1} note {note}]. {res}"
        if a == "clear_pad":
            ci, _ = self.cfg.resolve_controller(g.get("controller"))
            self.pads.pop((ci, g["pad"]), None)
            self._save_state()
            self.set_led(ci, g["pad"], "off")
            return f"cleared controller {ci} pad {g['pad']}"
        if a == "trigger_pad":
            ci, prof = self.cfg.resolve_controller(g.get("controller"))
            prof.note_for_pad(g["pad"])
            ch, note = self.trigger_pad(ci, g["pad"])
            return f"hit controller {ci} pad {g['pad']} ({self.pads.get((ci, g['pad']), 'empty')}) -> ch{ch + 1} note {note}"
        if a == "set_target":
            if g["target"] == "logic" and platform_info.current() != "mac":
                return "Logic Pro is macOS-only, so it isn't available on this PC. Try 'switch to ableton' or 'switch to autopilot'."
            self.target_name = g["target"]
            return f"target is now {self.target_name}"
        if a == "list_pads":
            if not self.pads:
                return "no pads assigned"
            return "; ".join(f"c{c} pad {p}: {s}" for (c, p), s in sorted(self.pads.items()))
        simple = {
            "play_scene": lambda: t.play_scene(g["scene"]),
            "play_clip": lambda: t.play_clip(g["track"], g["slot"]),
            "arm_track": lambda: t.arm_track(g["track"], True),
            "disarm_track": lambda: t.arm_track(g["track"], False),
            "mute_track": lambda: t.mute_track(g["track"], True),
            "unmute_track": lambda: t.mute_track(g["track"], False),
            "solo_track": lambda: t.solo_track(g["track"]),
            "select_track": lambda: t.select_track(g["track"]),
            "stop_track": lambda: t.stop_track(g["track"]),
            "tempo": lambda: t.tempo(g["bpm"]),
            "next_preset": t.next_preset,
            "prev_preset": t.prev_preset,
            "stop_all": t.stop_all,
            "play": t.play,
            "record": t.record,
            "undo": t.undo,
            "deck_play": lambda: self.targets["autopilot"].deck("play", g["deck"]),
            "deck_stop": lambda: self.targets["autopilot"].deck("stop", g["deck"]),
            "deck_cue": lambda: self.targets["autopilot"].deck("cue", g["deck"], g["cue"]),
        }
        if a in simple:
            return simple[a]()
        return f"? no handler for {a}"
