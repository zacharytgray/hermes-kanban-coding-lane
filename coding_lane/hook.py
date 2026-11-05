"""append an agent hook payload to the session's events file. stdlib only."""
import json
import sys
import time


def main(argv):
    path = argv[1]
    # claude code sends json on stdin, codex notify passes it as the last argument
    raw = argv[2] if len(argv) > 2 else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {"raw": raw}
    payload["lane_time"] = time.time()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main(sys.argv)
