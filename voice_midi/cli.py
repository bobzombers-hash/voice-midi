"""Command-line entry point: python -m voice_midi [--dry-run] [--speech text|vosk|whisper]"""
import argparse
import logging
import sys
from pathlib import Path

import os
import subprocess

from . import __version__, platform_info, updater
from .config import find_config, load_config
from .engine import Engine
from .speech import make_input


def list_ports():
    try:
        import mido
        print("MIDI inputs: ", mido.get_input_names())
        print("MIDI outputs:", mido.get_output_names())
    except Exception as e:  # no rtmidi backend
        print(f"can't list ports ({e}); pip install python-rtmidi")


def init_user_config(dest_dir=None):
    import shutil
    from .config import DEFAULT_CONFIG
    dest_dir = Path(dest_dir) if dest_dir else platform_info.user_dir()
    dest = dest_dir / "config.yaml"
    if dest.exists():
        return f"{dest} already exists (left unchanged)"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "controllers").mkdir(exist_ok=True)
    shutil.copyfile(DEFAULT_CONFIG, dest)
    return f"wrote {dest} (put extra controller profiles in {dest_dir / 'controllers'})"


def start_hardware_listeners(engine):
    import mido
    from .outputs.transport import find_port
    names = mido.get_input_names()
    for i, (prof, _) in enumerate(engine.cfg.rig, 1):
        n = find_port(prof.port_match, names)
        if not n:
            logging.warning("controller %d (%s) input not found in %s", i, prof.name, names)
            continue

        def cb(msg, i=i):
            engine.handle_hardware(i, msg)
        try:
            mido.open_input(n, callback=cb)
        except Exception as e:  # Windows: port already opened exclusively by Ableton etc.
            msg = f"controller {i} ({prof.name}) input {n!r} could not be opened: {e}."
            if platform_info.current() == "windows":
                msg += (" On Windows a MIDI port can only be opened by one app at a time: "
                        "turn this controller's Track/Remote INPUT off in Ableton (or close the other app), see README.")
            logging.warning(msg)
            continue
        print(f"  controller {i}: {prof.name} <- {n}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="voice-midi", description=__doc__)
    ap.add_argument("--config", help="path to config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="print MIDI/OSC instead of sending")
    ap.add_argument("--speech", choices=["text", "vosk", "whisper"], help="override speech.backend")
    ap.add_argument("--state", default=None, help="file to persist pad assignments (default: per-user dir, e.g. %%APPDATA%%\\voice-midi\\state.json)")
    ap.add_argument("--init-config", action="store_true", help="copy the bundled config to your per-user config dir and exit")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("-c", "--command", action="append", help="run one command and exit (repeatable)")
    ap.add_argument("-q", "--quiet", action="store_true", help="hide raw MIDI/OSC log lines")
    ap.add_argument("--version", action="version", version=f"voice-midi {__version__}")
    ap.add_argument("--check-update", action="store_true", help="check GitHub for a newer release and exit")
    ap.add_argument("--update", action="store_true", help="download, verify and install the latest release now")
    ap.add_argument("--refresh-profiles", action="store_true", help="fetch new/changed controller profiles and exit")
    ap.add_argument("--no-update-check", action="store_true", help="skip the launch-time update check")
    a = ap.parse_args(argv)
    argv = sys.argv[1:] if argv is None else list(argv)

    if a.check_update or a.update:
        return updater.main(["--update" if a.update else "--check"])
    if a.refresh_profiles:
        names = updater.refresh_profiles()
        print("updated profiles: " + (", ".join(names) if names else "none"))
        return 0
    # Apply an update downloaded last time - BEFORE anything else, via the temp-dir helper
    # (safe on Windows), then restart into the new code.
    if updater.pending_file().exists() and os.environ.get("VOICE_MIDI_UPDATE_APPLIED") != "1":
        updater.run_helper()
        os.environ["VOICE_MIDI_UPDATE_APPLIED"] = "1"
        return subprocess.run([sys.executable, "-m", "voice_midi", *argv]).returncode

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="    %(message)s", stream=sys.stdout)
    if a.list_ports:
        list_ports()
        return 0
    if a.init_config:
        print(init_user_config())
        return 0
    cfg = load_config(a.config)
    print(f"config: {find_config(a.config)}  platform: {platform_info.current()}")
    state = a.state
    if state is None and not a.dry_run:
        state = platform_info.state_file()
    try:
        engine = Engine(cfg, dry_run=a.dry_run, state_path=state)
    except IOError as e:  # e.g. loopMIDI port missing on Windows
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"voice-midi {'(DRY RUN) ' if a.dry_run else ''}target={engine.target_name} "
          f"controllers=" + ", ".join(f"{i}:{p.name}" for i, (p, _) in enumerate(cfg.rig, 1)))
    if a.command:
        for c in a.command:
            print(f"> {c}\n  {engine.run_text(c)}")
        return 0
    if not a.no_update_check:
        st = updater.settings(cfg.data)
        profiles_due = st.get("profiles") and st["mode"] != "off" and updater.due(float(st["check_interval_hours"]))
        updater.on_launch(cfg.data, interactive=sys.stdin.isatty())
        if profiles_due:
            names = updater.refresh_profiles(ref=st.get("profiles_ref", "main"))
            if names:
                print("new controller profiles: " + ", ".join(names) + " (restart to use)")
    if not a.dry_run:
        start_hardware_listeners(engine)
    src = make_input(cfg, a.speech)
    updater.acquire_session_lock()   # a running session blocks update swaps
    try:
        return _loop(engine, src)
    finally:
        updater.release_session_lock()


def _loop(engine, src):
    print("say/type a command ('quit' to exit)")
    while True:
        text = src.listen()
        if text is None or text.strip().lower() in ("quit", "exit"):
            break
        if text.strip():
            if not getattr(src, "interactive", True):
                print(f"> {text.strip()}")
            print("  " + engine.run_text(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
