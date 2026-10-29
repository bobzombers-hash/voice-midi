"""Send a keyboard shortcut to the focused app. macOS: osascript (no extra deps,
needs Accessibility permission). Windows/Linux: pynput (optional: pip install pynput)."""
import shutil
import subprocess

from .. import platform_info

MODS = {"cmd": "command", "command": "command", "ctrl": "control", "control": "control",
        "alt": "option", "option": "option", "shift": "shift"}


def parse_combo(combo: str):
    """'cmd+shift+]' -> (['cmd','shift'], ']')"""
    parts = [p.strip().lower() for p in combo.split("+")] if combo != "+" else ["+"]
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-2] + ["+"]
    return parts[:-1], parts[-1]


def send_keys(combo: str, app=None, os_name=None, dry_run=False):
    """Returns a description string. Never raises for a missing optional dependency."""
    os_name = os_name or platform_info.current()
    mods, key = parse_combo(combo)
    if dry_run:
        return f"(dry-run) would press {combo}"
    if os_name == "mac":
        if not shutil.which("osascript"):
            return "osascript not found"
        using = ""
        if mods:
            using = " using {" + ", ".join(f"{MODS[m]} down" for m in mods) + "}"
        script = (f'tell application "{app}" to activate\n' if app else "") + \
            f'tell application "System Events" to keystroke "{key}"{using}'
        subprocess.run(["osascript", "-e", script], check=False)
        return f"pressed {combo}" + (f" in {app}" if app else "")
    try:
        from pynput.keyboard import Controller, Key
    except ImportError:
        return f"can't press {combo}: pip install pynput (optional, for keyboard shortcuts on {os_name})"
    kb = Controller()
    keymap = {"cmd": Key.cmd, "command": Key.cmd, "ctrl": Key.ctrl, "control": Key.ctrl,
              "alt": Key.alt, "option": Key.alt, "shift": Key.shift}
    held = [keymap[m] for m in mods]
    for k in held:
        kb.press(k)
    try:
        kb.press(key)
        kb.release(key)
    finally:
        for k in reversed(held):
            kb.release(k)
    return f"pressed {combo} (focused window)"
