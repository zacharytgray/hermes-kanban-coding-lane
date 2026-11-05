"""steer, stop and resume, shared by the chat tools and the cli."""
import time

from . import board as kanban, session as store, spawn, tmux
from .agents import AGENTS

STOP_WAIT_SECONDS = 20


class LaneError(Exception):
    pass


def _session(task_id, board):
    found = store.load(task_id, board)
    if not found:
        raise LaneError(f"{task_id} has no lane session")
    return found


def _card_status(task_id, board):
    with kanban.connect(board) as conn:
        task = kanban.get_task(conn, task_id)
    if task is None:
        raise LaneError(f"no such task: {task_id}")
    if task.assignee not in AGENTS:
        raise LaneError(f"{task_id} is assigned to {task.assignee}, not to a lane agent")
    return task.status


def _describe(task, board):
    found = store.load(task.id, board) or {}
    name = found.get("tmux")
    live = bool(name) and tmux.exists(name) and tmux.pane_exit(name) is None
    return {"task_id": task.id, "title": task.title, "assignee": task.assignee, "status": task.status,
            "session_live": live, "session_id": found.get("session_id"), "session_link": found.get("link"),
            "branch": found.get("branch"), "worktree": found.get("worktree"),
            "attach": tmux.attach_command(name) if live else None}


def status(task_id=None, board=None):
    with kanban.connect(board) as conn:
        if task_id:
            task = kanban.get_task(conn, task_id)
            if task is None:
                raise LaneError(f"no such task: {task_id}")
            cards = [task]
        else:
            cards = [t for a in AGENTS for t in kanban.tasks(conn, a) if t.status != "done"]
    return {"ok": True, "cards": [_describe(t, board) for t in cards]}


def send(task_id, message, board=None):
    """paste into the live session. the note prefix also keeps a leading / or ! from running as a command."""
    current = _card_status(task_id, board)
    if current != "running":
        raise LaneError(f"{task_id} is {current}, not running. use resume with a message")
    found = _session(task_id, board)
    name = found["tmux"]
    if not tmux.exists(name) or tmux.pane_exit(name) is not None:
        raise LaneError(f"{task_id} has no live session right now")
    screen = tmux.pane(name)
    if tmux.at_dialog(screen):
        raise LaneError(f"{task_id} is waiting at a dialog, and an enter would answer it. "
                        f"open the session or stop it: {tmux.attach_command(name)}")
    result = tmux.deliver(name, f"Note from the operator: {message}")
    if result == "sent":
        store.steered_path(task_id, board).touch()
    with kanban.connect(board) as conn:
        kanban.comment(conn, task_id, f"operator message, delivery {result}: {message[:500]}")
    # unknown can also mean the message finished the work and the session closed
    return {"ok": result == "sent", "delivery": result, "card_status": _card_status(task_id, board),
            "session_link": found.get("link"), "attach": tmux.attach_command(name)}


def stop(task_id, reason="", board=None):
    if _card_status(task_id, board) != "running":
        raise LaneError(f"{task_id} is not running")
    _session(task_id, board)
    store.stop_path(task_id, board).write_text(reason or "no reason given")
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        current = _card_status(task_id, board)
        if current != "running":
            return {"ok": current == "scheduled", "status": current}
        time.sleep(0.5)
    return {"ok": False, "status": "running", "error": "the supervisor has not stopped it yet"}


def resume(task_id, message="", board=None):
    """unblock a stopped or blocked card. the next claim reopens the same cli session."""
    current = _card_status(task_id, board)
    if current == "triage":
        raise LaneError(f"{task_id} is in triage, where hermes puts a card blocked twice for the same "
                        "reason. a person decides what happens next")
    if current not in ("blocked", "scheduled"):
        raise LaneError(f"{task_id} is {current}. only a stopped or blocked card resumes here")
    found = store.load(task_id, board)
    store.stop_path(task_id, board).unlink(missing_ok=True)
    with kanban.connect(board) as conn:
        if message and found is None:
            raise LaneError(f"{task_id} never opened a session, so there is nothing to give the message to. "
                            "resume it without one, or edit the card")
        if message:
            found["note"] = message
            store.save(found, board)
            kanban.comment(conn, task_id, f"operator resume message: {message[:500]}")
        if not kanban.unblock(conn, task_id):
            raise LaneError(f"could not unblock {task_id}")
    started = spawn.tick(board)
    return {"ok": True, "started": task_id in started, "status": _card_status(task_id, board)}
