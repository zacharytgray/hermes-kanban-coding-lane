"""a private tmux server, so lane sessions never mix with the user's own."""
import os
import re
import subprocess
import time
from pathlib import Path

CONF = Path(__file__).with_name("tmux.conf")
SETTLE_SECONDS = 0.4
VERIFY_SECONDS = 1.5
# a dialog row, like "❯ 1. Yes" or "› 2. Quit". an enter here answers it
_MENU_ROW = re.compile(r"^\s*[❯›]\s*\d+\.\s")
# the footer under a dialog, numbered or not, in either cli
_DIALOG_FOOTER = re.compile(r"enter to confirm|enter continue|esc to cancel|esc quit", re.I)
_BOX_MARKERS = ("❯", "›")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def socket_name():
    return os.environ.get("CODING_LANE_TMUX_SOCKET", "hermes-coding-lane")


def _run(*args, check=False, stdin=None):
    cmd = ["tmux", "-L", socket_name(), "-f", str(CONF), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=check, input=stdin)


def attach_command(name):
    return f"tmux -L {socket_name()} attach -t {name}"


def start(name, cwd, argv, env, prompt_file):
    """the prompt is read from a file inside the pane. tmux refuses commands over about 16 kb"""
    full = ["sh", "-c", 'exec "$@" "$(cat "$0")"', str(prompt_file), "env", "-i",
            *(f"{k}={v}" for k, v in env.items()), *argv]
    _run("new-session", "-d", "-s", name, "-x", "160", "-y", "50", "-c", str(cwd), *full, check=True)


def exists(name):
    return _run("has-session", "-t", f"={name}").returncode == 0


def pane(name, history=0):
    args = ["capture-pane", "-p", "-t", f"={name}:"]
    if history:
        args += ["-S", f"-{history}"]
    result = _run(*args)
    return result.stdout if result.returncode == 0 else ""


def pane_exit(name):
    """the exit status when the program in the pane has ended, else None."""
    out = _run("display-message", "-p", "-t", f"={name}:", "#{pane_dead}:#{pane_dead_status}").stdout
    dead, _, status = out.strip().partition(":")
    if dead != "1":
        return None
    # a program killed by a signal has no status
    return int(status) if status else 128


def kill(name):
    _run("kill-session", "-t", f"={name}")


def keys(name, *key_names):
    _run("send-keys", "-t", f"={name}:", *key_names)


def clean(text):
    # an escape in the text could end the paste early and run the rest as keystrokes
    return _CONTROL.sub("", text)


def at_dialog(screen):
    """true when a dialog is on screen. an enter there would answer it."""
    if _DIALOG_FOOTER.search("\n".join(screen.rstrip().splitlines()[-6:])):
        return True
    for line in reversed(screen.splitlines()):
        if line.lstrip().startswith(_BOX_MARKERS):
            return bool(_MENU_ROW.match(line))
    return False


def _in_box(screen, probe):
    for line in reversed(screen.splitlines()):
        if line.lstrip().startswith(_BOX_MARKERS):
            return probe in line or "[Pasted text" in line
    return False


def deliver(name, text):
    """paste text into the live session and submit it.
    returns sent, stuck, unknown, or held when a dialog would take the enter."""
    text = clean(text)
    # the end of the message, since every message starts with the same prefix
    probe = text.strip().splitlines()[-1][-24:]
    if at_dialog(pane(name)):
        return "held"
    buffer = f"lane-{name}-{os.getpid()}"  # buffers are server-wide, so one per sender
    if _run("load-buffer", "-b", buffer, "-", stdin=text).returncode != 0:
        return "failed"
    if _run("paste-buffer", "-d", "-p", "-b", buffer, "-t", f"={name}:").returncode != 0:
        _run("delete-buffer", "-b", buffer)
        return "failed"
    # enter goes separately: sent with the paste it lands as a newline in the box
    time.sleep(SETTLE_SECONDS)
    for attempt in range(2):
        if at_dialog(pane(name)):
            return "held"
        keys(name, "Enter")
        time.sleep(VERIFY_SECONDS)
        screen = pane(name)
        if not _in_box(screen, probe):
            return "sent" if probe in screen else "unknown"
    return "stuck"
