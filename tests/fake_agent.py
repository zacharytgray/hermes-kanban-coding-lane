#!/usr/bin/env python3
"""stands in for claude and codex. the scenario comes from the prompt text."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


def read_line():
    """one line in cbreak mode with our own echo. a cooked tty caps a line near 1 kb, a real cli does not"""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    chars = []
    try:
        while True:
            ch = os.read(fd, 1).decode(errors="replace")
            if not ch:
                return None
            if ch in "\r\n":
                print(flush=True)
                return "".join(chars)
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    args = sys.argv[1:]
    if args[:2] in (["auth", "status"], ["login", "status"]):
        logged_in = "FAKE_NOT_LOGGED_IN" not in os.environ
        print(json.dumps({"loggedIn": logged_in}))
        sys.exit(0 if logged_in else 1)

    prompt = args[-1]
    scenario = (re.search(r"scenario=(\w+)", prompt) or [None, "resumed"])[1]
    settings = json.loads(flag(args, "--settings") or "{}")
    notify = next((a[len("notify="):] for a in args if a.startswith("notify=")), None)

    def fire(event, **fields):
        hook = (settings.get("hooks", {}).get(event) or [{"hooks": [{"command": ""}]}])[0]["hooks"][0]["command"]
        if hook:
            subprocess.run(hook, shell=True, input=json.dumps({"hook_event_name": event, **fields}), text=True)

    def end_turn(message):
        if notify:
            argv = json.loads(notify)
            payload = {"type": "agent-turn-complete", "thread-id": "fake", "last-assistant-message": message}
            subprocess.run([*argv, json.dumps(payload)])
        else:
            fire("Stop", last_assistant_message=message)

    def record(text):
        with open("fake.txt", "a") as f:
            f.write(text + "\n")

    def box():
        print("\n❯ ", end="", flush=True)

    # a real claude keeps a transcript, which is how the lane knows it can resume
    if "--session-id" in args and "CLAUDE_CONFIG_DIR" in os.environ:
        path = Path(os.environ["CLAUDE_CONFIG_DIR"], "projects", "x", flag(args, "--session-id") + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")

    print("fake agent up", " ".join(a for a in args[:6] if not a.startswith("{")), flush=True)
    with open("argv.json", "w") as f:
        json.dump({"args": args[:-1], "prompt": prompt, "env": dict(os.environ)}, f)

    if scenario == "resumed" and "keep waiting" in prompt:
        record("resumed and waiting: " + prompt)
    elif scenario == "resumed":
        record("resumed: " + prompt)
        end_turn("picked up where I left off\nLANE-STATUS: done")
    elif scenario == "done":
        record("work")
        end_turn("I did the work.\nLANE-STATUS: done")
    elif scenario == "blocked":
        end_turn("I need the staging password.\nLANE-STATUS: blocked need the staging password")
    elif scenario == "question":
        end_turn("Which database should I use?")
    elif scenario == "crash":
        print("segfault in the agent", flush=True)
        sys.exit(3)
    elif scenario == "clean_exit":
        sys.exit(0)
    elif scenario == "auth":
        print("Failed to authenticate: OAuth session expired and could not be refreshed", flush=True)
        sys.exit(1)
    elif scenario == "quota":
        print("You've hit your usage limit. It resets at 3pm.", flush=True)
    elif scenario == "quota_event":
        fire("StopFailure", error="rate_limit")
    elif scenario == "hang":
        print("thinking hard", flush=True)
        time.sleep(3600)
    elif scenario == "trust":
        print("Trust this folder?\n› 1. Trust and continue\n  2. Quit", flush=True)
        sys.stdin.readline()
        record("trusted")
        end_turn("Trusted and done.\nLANE-STATUS: done")
    elif scenario == "trust_claude":
        print(" Quick safety check: Is this a project you trust?\n ❯ No, exit\n   Yes, I trust this folder\n"
              " Enter to confirm · Esc to cancel", flush=True)
        sys.stdin.readline()
        sys.exit(1)
    elif scenario == "dialog":
        print("Do you want to proceed?\n❯ 1. Yes\n  2. No", flush=True)
        fire("Notification", notification_type="permission_prompt")
        time.sleep(3600)

    # stay interactive, like a real session waiting for its next message
    while True:
        box()
        line = read_line()
        if line is None:
            return
        record(line.strip())
        if "finish" in line:
            end_turn("Finished after your note.\nLANE-STATUS: done")
        else:
            end_turn("noted")


if __name__ == "__main__":
    main()
