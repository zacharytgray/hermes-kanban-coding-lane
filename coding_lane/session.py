"""per-card state kept beside the board, so a later run can resume the same session."""
import json
import os

from . import board


def _path(task_id, board_slug=None):
    return board.state_dir(task_id, board_slug) / "session.json"


def load(task_id, board_slug=None):
    path = _path(task_id, board_slug)
    return json.loads(path.read_text()) if path.exists() else None


def save(session, board_slug=None):
    path = _path(session["task_id"], board_slug)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, indent=2))
    os.replace(tmp, path)


def events_path(task_id, board_slug=None):
    return board.state_dir(task_id, board_slug) / "events.jsonl"


def stop_path(task_id, board_slug=None):
    return board.state_dir(task_id, board_slug) / "stop-request"
