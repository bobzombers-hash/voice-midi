"""Low-level senders. Each has a real and a dry-run implementation with the
same interface, so the router and tests never need hardware."""
import logging

from .. import platform_info

log = logging.getLogger("voice_midi")


class DryMidiPort:
    """Collects mido Messages instead of sending them."""
    def __init__(self, name="dry-run"):
        self.name, self.sent = name, []

    def send(self, msg):
        self.sent.append(msg)
        log.info("MIDI %-22s %s", self.name, msg)

    def close(self):
        pass


class DryOsc:
    def __init__(self, name="osc"):
        self.name, self.sent = name, []

    def send_message(self, address, args=None):
        args = [] if args is None else (list(args) if isinstance(args, (list, tuple)) else [args])
        self.sent.append((address, args))
        log.info("OSC  %-22s %s %s", self.name, address, args)


class VirtualPortMissing(IOError):
    pass


def resolve_out_port_name(configured=None, os_name=None):
    """configured may be None/'auto', a string, or a per-OS dict."""
    os_name = os_name or platform_info.current()
    name = platform_info.pick(configured, os_name)
    if not name or name == "auto":
        name = platform_info.DEFAULT_OUT_PORT[os_name]
    return name


def choose_port(wanted, names):
    """Exact match first, then case-insensitive substring (Windows appends ' 1' etc.)."""
    if wanted in names:
        return wanted
    for n in names:
        if wanted.lower() in n.lower():
            return n
    return None


def open_midi_out(configured=None, dry_run=False, os_name=None, mido_mod=None):
    os_name = os_name or platform_info.current()
    wanted = resolve_out_port_name(configured, os_name)
    if dry_run:
        return DryMidiPort(wanted)
    mido = mido_mod
    if mido is None:
        import mido  # needs python-rtmidi backend for real ports
    names = mido.get_output_names()
    found = choose_port(wanted, names)
    if found:
        return mido.open_output(found)
    if platform_info.supports_virtual_ports(os_name):
        log.warning("output %r not found (have %s); creating virtual port 'voice-midi'", wanted, names)
        return mido.open_output("voice-midi", virtual=True)
    raise VirtualPortMissing(
        f"MIDI output {wanted!r} not found. Available outputs: {names or 'none'}.\n"
        f"{platform_info.VIRTUAL_PORT_HELP[os_name]}")


def find_port(candidates, names):
    for c in candidates:
        for n in names:
            if c.lower() in n.lower():
                return n
    return None


def open_osc(host, port, dry_run=False, name="osc"):
    if dry_run:
        return DryOsc(name)
    try:
        from pythonosc.udp_client import SimpleUDPClient
    except ImportError:
        log.warning("python-osc not installed; %s OSC commands will be logged only", name)
        return DryOsc(name)
    return SimpleUDPClient(host, int(port))
