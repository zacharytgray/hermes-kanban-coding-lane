"""claim ready cards and start one supervisor per card.

spawn_supervisor has the shape of a dispatcher spawn_fn: (task, workspace, board) -> pid.
that is the one piece a public lane api would call instead of tick()."""
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import board as kanban
from .agents import AGENTS

log = logging.getLogger(__name__)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FENCE_MARKER = "HERMES_DELEGATED_CHILD_CONTEXT"


def tick(board=None):
    """start a supervisor for each ready lane card, up to max_running. returns task ids."""
    limit = int(kanban.settings().get("max_running", 2))
    started = []
    with kanban.connect(board) as conn:
        running = sum(len(kanban.tasks(conn, a, "running")) for a in AGENTS)
        for assignee in AGENTS:
            for task in kanban.tasks(conn, assignee, "ready"):
                if running >= limit:
                    return started
                if _claim_and_spawn(conn, task.id, board):
                    running += 1
                    started.append(task.id)
    return started


def _claim_and_spawn(conn, task_id, board):
    task = kanban.claim(conn, task_id)
    if task is None:
        return False
    try:
        if task.workspace_kind != "worktree":
            raise ValueError(f"lane cards need --workspace worktree:<repo>, this one is {task.workspace_kind}")
        workspace = kanban.workspace_for(conn, task, board)
        pid = spawn_supervisor(kanban.get_task(conn, task_id), workspace, board)
        kanban.adopt_pid(conn, task, pid)
    except Exception as exc:
        log.exception("coding-lane could not start %s", task_id)
        kanban.block(conn, task_id, task.current_run_id, f"could not start: {exc}", "capability")
        return False
    return True


def spawn_supervisor(task, workspace, board=None):
    env = dict(os.environ)
    # the dispatcher side grants this worker its card, same as a native spawn
    env.pop(FENCE_MARKER, None)
    # hermes activates its dependencies at startup, so the child takes the same path
    env["PYTHONPATH"] = os.pathsep.join([str(PLUGIN_ROOT), *filter(None, sys.path)])
    env["HERMES_HOME"] = str(kanban.get_hermes_home())
    slug = board or kanban.current_board()
    log_file = open(kanban.log_path(task.id, slug), "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "coding_lane.supervisor", task.id, str(task.current_run_id), task.claim_lock,
             str(workspace), slug],
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, env=env,
            start_new_session=True, cwd=str(workspace),
        )
    finally:
        log_file.close()
    return proc.pid
