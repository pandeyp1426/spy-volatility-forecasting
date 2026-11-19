"""Transactional append-only event journal and a crash-released process lock.

SQLite prevents partial journal appends; evidence files are unique per attempt.
Hashes detect changes relative to the surviving chain, not malicious rewriting
or deletion of its tail. Trusted off-machine retention is a separate requirement.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from spy_volatility.workflows.pilot import sha, verify_files


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class BusyError(RuntimeError):
    pass


class ForecastStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "journal.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL,
                    payload TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE);
                CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'append-only journal'); END;
                CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'append-only journal'); END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def append(self, payload: dict) -> dict:
        text = canonical(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT sequence, event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
            digest = hashlib.sha256(canonical([sequence, previous, text]).encode()).hexdigest()
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (sequence, previous, text, digest))
        return {**payload, "sequence": sequence, "previous_hash": previous, "event_hash": digest}

    def records(self, *, verify_artifacts=True) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT sequence, previous_hash, payload, event_hash FROM events ORDER BY sequence").fetchall()
        previous = "0" * 64
        records = []
        for expected, (sequence, parent, text, digest) in enumerate(rows, 1):
            actual = hashlib.sha256(canonical([sequence, parent, text]).encode()).hexdigest()
            if sequence != expected or parent != previous or digest != actual:
                raise ValueError(f"Journal integrity failure at sequence {sequence}")
            value = json.loads(text)
            if verify_artifacts and value.get("artifact_sha256"):
                path = self.evidence_path(value["evidence_dir"])
                verify_files(path, value["artifact_sha256"])
                files = {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()}
                if files != set(value["artifact_sha256"]):
                    raise ValueError(f"Unrecorded evidence files: {path}")
            records.append({**value, "sequence": sequence, "previous_hash": parent, "event_hash": digest})
            previous = digest
        return records

    def evidence_path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Evidence path escapes store")
        return path

    @contextmanager
    def exclusive(self):
        # The file is permanent; the OS releases the byte lock after a crash.
        with (self.root / "worker.lock").open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise BusyError("Another forecast worker holds the store lock") from error
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def seal(self, relative: str) -> dict:
        path = self.evidence_path(relative)
        hashes = {}
        for file in sorted(path.rglob("*")):
            if file.is_file():
                # Windows _commit requires a writable descriptor. Evidence is
                # opened without truncation; no existing bytes are changed.
                with file.open("r+b") as stream:
                    os.fsync(stream.fileno())
                hashes[file.relative_to(path).as_posix()] = sha(file)
        return hashes
