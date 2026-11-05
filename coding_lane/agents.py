"""everything that differs between claude code and codex."""
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from . import tmux

STATUS_LINE = re.compile(r"^\s*LANE-STATUS:\s*(done|blocked)\b[ \t:]*(.*)$", re.M)

# only read off a pane that ended or went quiet, never off a busy transcript
AUTH_ERRORS = re.compile(
    r"failed to authenticate|oauth session expired|please run /login|not logged in|invalid api key"
    r"|run codex login|401 unauthorized", re.I)
QUOTA_ERRORS = re.compile(
    r"hit your (usage )?limit|usage limit reached|limit reached|quota exceeded|exceeded your current quota"
    r"|rate limit exceeded|too many requests", re.I)

PERMISSION_MODES = {"default", "acceptEdits", "plan", "auto", "dontAsk"}
SANDBOXES = {"read-only", "workspace-write"}
APPROVALS = {"never", "on-request", "untrusted"}

# what a cli may see. hermes secrets stay out unless env_passthrough names them
BASE_ENV = ("USER", "LOGNAME", "HOME", "PATH", "SHELL", "LANG", "LC_ALL", "TMPDIR", "SSH_AUTH_SOCK",
            "CLAUDE_CONFIG_DIR", "CODEX_HOME")


class ConfigError(Exception):
    pass


def child_env(settings):
    names = list(BASE_ENV) + list(settings.get("env_passthrough") or [])
    env = {k: os.environ[k] for k in names if k in os.environ}
    env["TERM"] = "xterm-256color"
    return env


def hook_command(events_path):
    hook = Path(__file__).with_name("hook.py")
    return [sys.executable, "-I", str(hook), str(events_path)]


class Claude:
    name = "claude-code"
    link_pattern = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9_-]{20,}")

    def __init__(self, settings):
        self.cfg = settings.get("claude") or {}
        self.bin = self.cfg.get("bin", "claude")
        self.mode = self.cfg.get("permission_mode", "acceptEdits")
        if self.mode not in PERMISSION_MODES:
            raise ConfigError(f"claude.permission_mode {self.mode!r} is not allowed. the lane refuses permission bypass")

    def new_session_id(self):
        return str(uuid.uuid4())

    def preflight(self, env):
        """an auth problem as text, or None. no model call."""
        out = subprocess.run([self.bin, "auth", "status"], capture_output=True, text=True, env=env, timeout=30)
        try:
            return None if json.loads(out.stdout).get("loggedIn") else "claude code is not logged in. run: claude auth login"
        except ValueError:
            return None  # a cli without this subcommand, let the session report it

    def command(self, session, prompt, hook, resuming):
        events = {e: [{"hooks": [{"type": "command", "command": _shell(hook)}]}]
                  for e in ("Stop", "StopFailure", "Notification")}
        argv = [self.bin, "--permission-mode", self.mode, "--settings", json.dumps({"hooks": events}),
                "--remote-control", session["tmux"]]
        argv += ["--resume", session["session_id"]] if resuming else ["--session-id", session["session_id"]]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        if self.cfg.get("effort"):
            argv += ["--effort", self.cfg["effort"]]
        if self.cfg.get("allowed_tools"):
            argv += ["--allowedTools", ",".join(self.cfg["allowed_tools"])]
        # --allowedTools takes many values and would swallow a bare prompt
        return [*argv, "--", prompt]

    def has_transcript(self, session):
        root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        return bool(glob.glob(f"{glob.escape(root)}/projects/*/{session['session_id']}.jsonl"))

    def find_session_id(self, session):
        return session["session_id"]

    def find_link(self, screen):
        match = self.link_pattern.search(screen)
        return match.group(0) if match else None

    def accept_trust(self, name, screen):
        # the first row is "no, exit" until the arrow moves off it
        if re.search(r"^\s*❯.*no, exit", screen, re.M | re.I):
            tmux.keys(name, "Down")
        tmux.keys(name, "Enter")

    def resume_command(self, session):
        return f"cd {session['worktree']} && {self.bin} --resume {session['session_id']}"

    def last_message(self, event):
        return event.get("last_assistant_message") or ""

    def turn_ended(self, event):
        return event.get("hook_event_name") == "Stop"

    def turn_failed(self, event):
        return event.get("error") or "unknown" if event.get("hook_event_name") == "StopFailure" else None

    def needs_approval(self, event):
        return event.get("hook_event_name") == "Notification" and event.get("notification_type") == "permission_prompt"


class Codex:
    name = "codex"

    def __init__(self, settings):
        self.cfg = settings.get("codex") or {}
        self.bin = self.cfg.get("bin", "codex")
        self.sandbox = self.cfg.get("sandbox", "workspace-write")
        self.approval = self.cfg.get("approval", "never")
        if self.sandbox not in SANDBOXES:
            raise ConfigError(f"codex.sandbox {self.sandbox!r} is not allowed. the lane refuses sandbox bypass")
        if self.approval not in APPROVALS:
            raise ConfigError(f"codex.approval {self.approval!r} is not allowed")

    def new_session_id(self):
        return None  # codex names its own thread, found once it starts

    def preflight(self, env):
        out = subprocess.run([self.bin, "login", "status"], capture_output=True, text=True, env=env, timeout=30)
        return None if out.returncode == 0 else "codex is not logged in. run: codex login"

    def command(self, session, prompt, hook, resuming):
        argv = [self.bin]
        if resuming:
            argv += ["resume", session["session_id"]]
        argv += ["--cd", session["worktree"], "--no-alt-screen", "--sandbox", self.sandbox,
                 "--ask-for-approval", self.approval, "-c", "notify=" + json.dumps(hook)]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        return [*argv, "--", prompt]

    def has_transcript(self, session):
        return bool(session.get("session_id"))

    def find_session_id(self, session):
        """the thread whose rollout started in this worktree. side threads have no rollout."""
        root = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
        paths = sorted(glob.glob(f"{glob.escape(root)}/sessions/*/*/*/rollout-*.jsonl"), key=os.path.getmtime, reverse=True)
        for path in paths[:50]:
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.loads(f.readline()).get("payload") or {}
            except (OSError, ValueError):
                continue
            if meta.get("cwd") and os.path.realpath(meta["cwd"]) == os.path.realpath(session["worktree"]):
                return meta.get("id")
        return None

    def find_link(self, screen):
        return None  # codex has no per-session url. the resume command is the handle

    def accept_trust(self, name, screen):
        tmux.keys(name, "Enter")  # the first row is "trust and continue"

    def resume_command(self, session):
        return f"{self.bin} resume {session.get('session_id') or '<thread id not known yet>'} --cd {session['worktree']}"

    def last_message(self, event):
        return event.get("last-assistant-message") or ""

    def turn_ended(self, event):
        return event.get("type") == "agent-turn-complete"

    def turn_failed(self, event):
        return None

    def needs_approval(self, event):
        return False


AGENTS = {Claude.name: Claude, Codex.name: Codex}


def for_assignee(assignee, settings):
    return AGENTS[assignee](settings)


def _shell(argv):
    return " ".join(shlex.quote(a) for a in argv)


def at_trust_prompt(screen):
    return "trust this folder" in screen.lower()


def classify_failure(screen):
    if AUTH_ERRORS.search(screen):
        return "auth"
    if QUOTA_ERRORS.search(screen):
        return "quota"
    return None
