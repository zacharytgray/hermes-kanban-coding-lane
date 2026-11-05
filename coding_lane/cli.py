"""hermes coding-lane <verb>, also python -m coding_lane <verb>."""
import json

from . import control, spawn


def setup(parser):
    parser.add_argument("--board", default=None)
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("tick", help="claim ready lane cards now")
    show = verbs.add_parser("status", help="list lane sessions")
    show.add_argument("task_id", nargs="?")
    send = verbs.add_parser("send", help="send a message to a running session")
    send.add_argument("task_id")
    send.add_argument("message")
    stop = verbs.add_parser("stop", help="stop a session and block its card")
    stop.add_argument("task_id")
    stop.add_argument("reason", nargs="?", default="")
    resume = verbs.add_parser("resume", help="resume a blocked card in the same session")
    resume.add_argument("task_id")
    resume.add_argument("message", nargs="?", default="")


def handle(args):
    try:
        if args.verb == "tick":
            result = {"ok": True, "started": spawn.tick(args.board)}
        elif args.verb == "status":
            result = control.status(args.task_id, board=args.board)
        elif args.verb == "send":
            result = control.send(args.task_id, args.message, board=args.board)
        elif args.verb == "stop":
            result = control.stop(args.task_id, args.reason, board=args.board)
        else:
            result = control.resume(args.task_id, args.message, board=args.board)
    except control.LaneError as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1
