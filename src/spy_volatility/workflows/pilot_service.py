"""Single persistent pilot writer; checkpoint privately before requesting Pages."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from spy_volatility.workflows import hosted_pilot

PUBLIC = "pandeyp1426/spy-volatility-forecasting"
PRIVATE = "https://github.com/pandeyp1426/spy-volatility-pilot-evidence.git"


@contextmanager
def exclusive(path):
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run(root, state, gh, command=None):
    root, state = root.resolve(), state.resolve()
    def checked(*args):
        return subprocess.run(args, cwd=state, check=True, capture_output=True,
                              text=True, timeout=90).stdout.strip()
    command = command or checked
    git = ("git", "-c", f"safe.directory={state.as_posix()}")
    if command(*git, "remote", "get-url", "origin") != PRIVATE:
        raise ValueError("Expected the designated private evidence checkout")
    if command(*git, "branch", "--show-current") != "main":
        raise ValueError("Private evidence must use main")
    if (root / "artifacts").resolve() != state / "artifacts":
        raise ValueError("Worker artifacts must point to the private evidence checkout")
    with exclusive(state / ".git/pilot-service.lock"):
        writer = command(gh, "variable", "get", "PILOT_WRITER", "--repo", PUBLIC)
        if writer != "windows":
            raise ValueError("Windows is not the configured pilot writer")
        # A clean, behind checkout may fast-forward. Dirty or divergent
        # histories require review: never merge SQLite journals or discard an
        # unpublished attempt. Retry local checkpoints only on a known ancestry.
        command(*git, "fetch", "-q", "origin", "main")
        ahead, behind = map(int, command(*git, "rev-list", "--left-right", "--count", "HEAD...origin/main").split())
        if behind:
            if ahead or command(*git, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError("Private journal histories diverged or local evidence is unpublished; preserve both for review")
            command(*git, "merge", "--ff-only", "origin/main")
        def checkpoint():
            command(*git, "add", "--", "artifacts/operations/journal.sqlite3", "artifacts/operations/pilot_2026")
            if command(*git, "diff", "--cached", "--name-only"):
                command(*git, "-c", "user.name=pilot-collector", "-c",
                        "user.email=pilot-collector@users.noreply.github.com", "commit", "-q", "-m",
                        "Checkpoint 2026 pilot evidence")
            command(*git, "push", "-q", "origin", "HEAD:main")
        checkpoint()
        result = {"started_at_utc": datetime.now(timezone.utc).isoformat()}
        try:
            result["collection"] = hosted_pilot.collect(root)
        finally:
            checkpoint()
        result["checkpoint"] = command(*git, "rev-parse", "HEAD")
        result["verification"] = hosted_pilot.verify(root)
        if hosted_pilot.release(root, only_changed=True):
            command(gh, "workflow", "run", "dashboard.yml", "--ref", "main", "--repo", PUBLIC)
            result["publication"] = "requested; inspect Actions deployment result"
        else:
            result["publication"] = "already_current"
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--gh", required=True)
    args = parser.parse_args()
    result = run(args.root, args.state, args.gh)
    print(json.dumps(result, indent=2))
    return int(result["collection"]["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
