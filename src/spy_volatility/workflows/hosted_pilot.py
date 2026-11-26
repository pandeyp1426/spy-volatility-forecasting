"""Bootstrap private pilot evidence and prepare the public Pages release."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

from spy_volatility.infrastructure.forecast_store import ForecastStore
from spy_volatility.workflows import dashboard_pilot, pilot, public_export, public_history
from spy_volatility.workflows.operations import Operations
from spy_volatility.workflows.public_forecasts import read_forecasts


PUBLISHED = "https://pandeyp1426.github.io/spy-volatility-forecasting/data/forecasts.json"


class PilotEvidenceSeed:
    """Copy pinned inputs and a consistent journal into a new private checkout."""

    def __init__(self, root: Path, destination: Path):
        self.ops = Operations(root / "configs/operations.toml")
        self.root = self.ops.root
        self.destination = destination.resolve()

    def copy(self, path: Path):
        target = self.destination / path.resolve().relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def copy_manifest(self, directory, record_name, digest, selected=None):
        pilot.verify_files(directory, {record_name: digest})
        record = json.loads((directory / record_name).read_bytes())
        hashes = record["artifact_sha256"]
        if selected is not None:
            hashes = {name: hashes[name] for name in selected}
        pilot.verify_files(directory, hashes)
        for name in (record_name, *hashes):
            self.copy(directory / name)

    def create(self):
        if self.destination.is_relative_to(self.root):
            raise ValueError("Private seed destination must be outside the public repository")
        self.destination.mkdir(parents=True, exist_ok=False)
        ops = self.ops
        ops.check()
        if not (ops.store_path / "journal.sqlite3").is_file():
            raise FileNotFoundError("Existing pilot journal required")
        store = ForecastStore(ops.store_path)
        with store.exclusive():
            records = store.records()
            if (not records or records[0].get("kind") != "store_created"
                    or records[0]["config_sha256"] != ops.config_hash
                    or any(row["evidence_mode"] != "live" or row.get("context", {}).get("study")
                           not in (None, "pilot_2026") for row in records)):
                raise ValueError("Expected the designated live 2026 pilot journal")
            for row in records:
                if row.get("artifact_sha256"):
                    for name in row["artifact_sha256"]:
                        self.copy(store.evidence_path(row["evidence_dir"]) / name)
                if row.get("archive_path"):
                    self.copy(store.evidence_path(row["archive_path"]))
            journal = self.destination / store.db.relative_to(self.root)
            journal.parent.mkdir(parents=True, exist_ok=True)
            with store.connect() as source, closing(sqlite3.connect(journal)) as target:
                source.backup(target)
            self.copy_manifest(ops.bundle, "freeze_record.json", ops.config["prepared"]["freeze_record_sha256"])
            manual = ops.config["manual_pilot"]
            self.copy_manifest(self.root / manual["path"], "pilot_record.json", manual["record_sha256"])
            for run, tables in public_history.TABLES.items():
                self.copy_manifest(self.root / "artifacts/runs" / run, "run_record.json",
                                   public_history.RECORD_HASH[run], tables)
            public_export.market_history(self.root)
            snapshot = self.root / "data/raw" / public_export.SNAPSHOT
            for name in ("raw.csv", "metadata.json"):
                self.copy(snapshot / name)
            for notice in (self.root / "artifacts/market_notices").glob("*.json"):
                self.copy(notice)
        (self.destination / ".gitattributes").write_bytes(b"* -text\n")
        (self.destination / ".gitignore").write_bytes(
            b"provider_cache/\nworker.lock\n__pycache__/\n*.pyc\n*.sqlite3-*\n.env*\n")
        return records[-1]["event_hash"]

    def advance_checkout(self, checkout):
        """Extend a private checkout from a fresh seed, preserving journal ancestry."""
        self.create()
        relative = self.ops.store_path.relative_to(self.root) / "journal.sqlite3"
        local_db = self.destination / relative
        remote_db = checkout / relative
        if not remote_db.is_file():
            raise ValueError("Private checkout must contain its existing journal")
        remote = ForecastStore(remote_db.parent).records()
        local = ForecastStore(local_db.parent).records()
        if not remote or len(remote) > len(local) or local[len(remote)-1]["event_hash"] != remote[-1]["event_hash"]:
            raise ValueError("Private and local journals have diverged. Preserve both for review.")
        for directory in ("artifacts", "data"):
            for path in (self.destination / directory).rglob("*"):
                if not path.is_file() or path == local_db:
                    continue
                target = checkout / path.relative_to(self.destination)
                if target.is_file():
                    if pilot.sha(target) != pilot.sha(path):
                        raise ValueError(f"Private evidence differs at {path.name}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        if len(remote) < len(local):
            shutil.copyfile(local_db, remote_db)
        return local[-1]["event_hash"]


def collect(root):
    ops = Operations(root / "configs/operations.toml")
    if not (ops.store_path / "journal.sqlite3").is_file():
        raise FileNotFoundError("Restore the private pilot journal before collection")
    with closing(sqlite3.connect((ops.store_path / "journal.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        first = db.execute("SELECT payload FROM events WHERE sequence=1").fetchone()
    identity = json.loads(first[0]) if first else {}
    if (identity.get("kind") != "store_created" or identity.get("evidence_mode") != "live"
            or identity.get("config_sha256") != ops.config_hash):
        raise ValueError("Private pilot journal does not match the designated configuration")
    ForecastStore(ops.store_path).records()
    return dashboard_pilot.collect(ops.config_path)


def release(root, *, only_changed=False):
    if only_changed:
        rows = read_forecasts(root)
        try:
            with urlopen(PUBLISHED, timeout=15) as response:
                published = json.load(response)
            if published.get("dataset") == "forecasts" and published.get("data", {}).get("rows") == rows:
                return False
        except (URLError, TimeoutError, ValueError):
            pass  # Initial deployment or an unavailable site. Rebuild from verified evidence.
    public_export.export(root)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("seed").add_argument("destination", type=Path)
    commands.add_parser("handoff").add_argument("checkout", type=Path)
    commands.add_parser("tick")
    publish = commands.add_parser("release")
    publish.add_argument("--only-changed", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == "seed":
        print(PilotEvidenceSeed(root, args.destination).create())
    elif args.action == "handoff":
        checkout = args.checkout.resolve()
        if not (checkout / ".git").is_dir() or checkout.is_relative_to(root) or root.is_relative_to(checkout):
            raise ValueError("Handoff requires a separate private checkout outside the research repository")
        with tempfile.TemporaryDirectory(prefix="pilot-handoff-") as scratch:
            print(PilotEvidenceSeed(root, Path(scratch) / "seed").advance_checkout(checkout))
    elif args.action == "tick":
        print(collect(root)["status"])
    else:
        print("publish" if release(root, only_changed=args.only_changed) else "current")


if __name__ == "__main__":
    main()
