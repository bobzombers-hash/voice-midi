"""Speech input. Every heavy dependency is imported lazily so dry-run/tests
only need mido + pyyaml.

Backends:
  text    - type commands (or pipe a file). Always available.
  vosk    - offline, fast, small model (~50 MB). pip install vosk sounddevice
  whisper - faster-whisper, better accuracy. pip install faster-whisper sounddevice
Push-to-talk: press Enter to start talking, Enter again to stop.
"""
import sys
from pathlib import Path

from . import platform_info


def vocabulary(cfg):
    words = ("load put place on pad controller track scene clip arm disarm play stop tempo bpm "
             "next previous preset hit trigger mute unmute solo select record undo deck cue switch to "
             "ableton logic autopilot list pads clear zero one two three four five six seven eight nine ten "
             "eleven twelve thirteen fourteen fifteen sixteen twenty thirty forty fifty sixty seventy eighty "
             "ninety hundred oh slot into the").split()
    for name in cfg.sounds:
        words += name.split()
    for prof, extra in cfg.rig:
        for a in prof.aliases + extra:
            words += a.split()
    return sorted(set(w for w in words if w.isalpha()))


def _record_ptt(sample_rate):
    import numpy as np
    import sounddevice as sd
    input("  [Enter] to talk ... ")
    chunks = []
    stream = sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16",
                            callback=lambda d, *_: chunks.append(d.copy()))
    with stream:
        input("  listening — [Enter] to stop ")
    return np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype="int16")


class TextInput:
    def __init__(self, cfg):
        self.interactive = sys.stdin.isatty()

    def listen(self):
        try:
            line = input("voice-midi> " if self.interactive else "")
        except EOFError:
            return None
        return line


class VoskInput:
    def __init__(self, cfg):
        import json
        from vosk import KaldiRecognizer, Model
        sp = cfg.speech
        self.rate = int(sp.get("sample_rate", 16000))
        path = Path(platform_info.pick(sp.get("vosk_model")) or "").expanduser()
        if not path.is_dir():
            raise SystemExit(f"Vosk model not found at {path}. Download one from https://alphacephei.com/vosk/models")
        self.model = Model(str(path))
        # Restricting the grammar makes recognition much more accurate for commands
        self.grammar = json.dumps([" ".join(vocabulary(cfg)), "[unk]"])
        self._json = json
        self._KR = KaldiRecognizer

    def listen(self):
        audio = _record_ptt(self.rate)
        rec = self._KR(self.model, self.rate, self.grammar)
        rec.AcceptWaveform(audio.tobytes())
        text = self._json.loads(rec.FinalResult()).get("text", "")
        print(f"  heard: {text!r}")
        return text


class WhisperInput:
    def __init__(self, cfg):
        from faster_whisper import WhisperModel
        sp = cfg.speech
        self.rate = int(sp.get("sample_rate", 16000))
        self.model = WhisperModel(sp.get("whisper_model", "base.en"), device="cpu", compute_type="int8")
        self.prompt = "Commands: " + ", ".join(list(cfg.sounds)[:30]) + ", pad, controller, track, scene, tempo."

    def listen(self):
        audio = _record_ptt(self.rate).astype("float32") / 32768.0
        segs, _ = self.model.transcribe(audio, language="en", initial_prompt=self.prompt, vad_filter=True)
        text = " ".join(s.text for s in segs).strip()
        print(f"  heard: {text!r}")
        return text


BACKENDS = {"text": TextInput, "vosk": VoskInput, "whisper": WhisperInput}


def make_input(cfg, name=None):
    name = name or cfg.speech.get("backend", "text")
    if name not in BACKENDS:
        raise SystemExit(f"unknown speech backend {name!r}; choose from {list(BACKENDS)}")
    try:
        return BACKENDS[name](cfg)
    except ImportError as e:
        raise SystemExit(f"backend {name!r} needs extra packages ({e}). See README 'Speech backends'.")
