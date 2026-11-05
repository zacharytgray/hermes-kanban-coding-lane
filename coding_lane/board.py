"""the one module that touches hermes kanban. it calls the kernel directly, since the
cli heartbeat does not extend a claim and the cli cannot register a worker pid."""
from pathlib import Path

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli.kanban_db_connect import connect_closing
from hermes_cli.kanban_db_workspace import resolve_workspace, set_workspace_path
from hermes_constants import get_hermes_home  # noqa: F401  spawn pins the child home with it

AUTHOR = "coding-lane"
CLAIM_TTL_SECONDS = 300
EXIT_TRAILER = "[kanban-worker-exit] rc="


def connect(board=None):
    return connect_closing(board=board)


def state_dir(task_id, board=None):
    slug = board or kb.get_current_board()
    path = Path(get_hermes_home()) / "plugin-data" / "coding-lane" / slug / task_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def settings():
    from hermes_cli.config import load_config
    entries = (load_config().get("plugins") or {}).get("entries") or {}
    return (entries.get("coding-lane") or {}).get("settings") or {}


def log_path(task_id, board=None):
    path = kb.worker_log_path(task_id, board=board)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def worker_context(conn, task_id):
    return kb.build_worker_context(conn, task_id)


def claim(conn, task_id):
    return kb.claim_task(conn, task_id, ttl_seconds=CLAIM_TTL_SECONDS)


def workspace_for(conn, task, board=None):
    path = resolve_workspace(task, board=board)
    set_workspace_path(conn, task.id, str(path))
    return path


def adopt_pid(conn, task, pid):
    return kbd.adopt_worker_pid(conn, task.id, task.current_run_id, pid)


def heartbeat(conn, task_id, run_id, lock, note=None):
    """records the beat and extends the claim. false means this run lost the card."""
    alive = kbd.heartbeat_worker(conn, task_id, note=note, expected_run_id=run_id)
    return alive and kb.heartbeat_claim(conn, task_id, ttl_seconds=CLAIM_TTL_SECONDS, claimer=lock)


def owns(conn, task_id, run_id):
    task = kb.get_task(conn, task_id)
    return bool(task and task.status == "running" and task.current_run_id == run_id)


def comment(conn, task_id, body):
    kb.add_comment(conn, task_id, AUTHOR, body)


def block(conn, task_id, run_id, reason, kind):
    kb.add_comment(conn, task_id, AUTHOR, f"blocked: {reason}")
    return kb.block_task(conn, task_id, reason=reason, kind=kind, expected_run_id=run_id)


def request_review(conn, task_id, run_id, summary, metadata):
    return kb.request_review(conn, task_id, summary=summary, metadata=metadata,
                             expected_run_id=run_id, with_reason=True)


def comments_after(conn, task_id, after_id):
    return kb.list_comments_after(conn, task_id, after_id=after_id)


def last_comment_id(conn, task_id):
    return max((c.id for c in kb.list_comments(conn, task_id)), default=0)


def get_task(conn, task_id):
    return kb.get_task(conn, task_id)


def tasks(conn, assignee, status=None):
    return kb.list_tasks(conn, assignee=assignee, status=status)


def unblock(conn, task_id):
    return kb.unblock_task(conn, task_id)


def current_board():
    return kb.get_current_board()
