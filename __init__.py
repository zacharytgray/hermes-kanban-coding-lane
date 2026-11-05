"""hermes plugin entry: claim on the dispatcher tick, steer from chat tools."""
import json
import logging

from .coding_lane import cli, control, spawn

log = logging.getLogger(__name__)

TOOLSET = "coding_lane"


def _on_tick(board=None, dry_run=False, **_):
    if dry_run:
        return
    try:
        spawn.tick(board)
    except Exception:
        # a broken lane must not stall the board's dispatcher
        log.exception("coding-lane tick failed")


def _tool(fn):
    def handler(args, **_):
        try:
            return json.dumps(fn(**args))
        except control.LaneError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
    return handler


def _schema(name, description, **props):
    required = [k for k, v in props.items() if not v.pop("optional", False)]
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": props, "required": required},
    }


_TASK = {"type": "string", "description": "kanban task id, like t_1a2b3c4d"}
_BOARD = {"type": "string", "description": "board slug, default is the current board", "optional": True}


def register(ctx):
    ctx.register_hook("on_kanban_dispatch_tick", _on_tick)
    tools = [
        (control.status, _schema(
            "coding_lane_status", "List lane sessions: card status, session link, attach and resume commands.",
            task_id={**_TASK, "optional": True}, board=dict(_BOARD))),
        (control.send, _schema(
            "coding_lane_send", "Send a message straight to a running Claude Code or Codex worker's own session.",
            task_id=dict(_TASK), message={"type": "string", "description": "what to tell the worker"},
            board=dict(_BOARD))),
        (control.stop, _schema(
            "coding_lane_stop", "Stop a running worker. The card goes to blocked and the session can be resumed.",
            task_id=dict(_TASK), reason={"type": "string", "description": "why", "optional": True},
            board=dict(_BOARD))),
        (control.resume, _schema(
            "coding_lane_resume", "Resume a stopped or blocked worker in the same CLI session.",
            task_id=dict(_TASK), message={"type": "string", "description": "first message after resuming", "optional": True},
            board=dict(_BOARD))),
    ]
    for fn, schema in tools:
        ctx.register_tool(schema["name"], TOOLSET, schema, _tool(fn), description=schema["description"])
    ctx.register_cli_command("coding-lane", "Steer Claude Code and Codex kanban sessions", cli.setup, cli.handle)
