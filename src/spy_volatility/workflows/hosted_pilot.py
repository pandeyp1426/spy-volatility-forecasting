"""Bootstrap private pilot evidence and prepare the public Pages release."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import os
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

from spy_volatility.infrastructure.forecast_store import ForecastStore
from spy_volatility.workflows import pilot, public_export, public_history
from spy_volatility.workflows.operations import Operations
from spy_volatility.workflows.public_forecasts import read_forecasts, read_coverage


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
            started = {row["attempt_id"] for row in records if row["kind"] == "attempt_started"}
            sealed = {row["attempt_id"] for row in records if "artifact_sha256" in row}
            if started - sealed:
                raise ValueError("Recover the unfinished local attempt before transferring its evidence")
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


def restored_operations(root):
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
    return ops


def collect(root):
    ops = restored_operations(root)
    results = ops.execute("pilot-cycle")
    failed = any(r.get("status") in {"failed", "invalid", "busy", "interrupted"}
                 or r.get("external_retention_status") == "failed" for r in results)
    issued = [r for r in results if r.get("kind") == "forecast"]
    return {"status": "failed" if failed else "forecast_created" if issued else "no_forecast",
            "forecast_status": results[0].get("status"), "new_forecasts": len(issued),
            "new_outcomes": sum(r.get("kind") == "outcome" for r in results),
            "new_missing": sum(r.get("kind") == "forecast_missing" for r in results),
            "origin": issued[0]["context"]["origin"] if issued else None,
            "issued_at_utc": issued[0]["issued_at_utc"] if issued else None}


def verify(root):
    result, = restored_operations(root).execute("verify")
    if result.get("status") != "passed":
        raise ValueError("Private evidence replay failed")
    return result


def release(root, *, only_changed=False):
    if only_changed:
        rows = read_forecasts(root)
        coverage = read_coverage(root)
        try:
            with urlopen(PUBLISHED, timeout=15) as response:
                published = json.load(response)
            with urlopen(PUBLISHED.replace("forecasts.json", "status.json"), timeout=15) as response:
                status = json.load(response)
            if (published.get("dataset") == "forecasts" and published.get("data", {}).get("rows") == rows
                    and status.get("data", {}).get("collection") == coverage):
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
    commands.add_parser("verify")
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
        result = collect(root)
        print(json.dumps(result))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write("\n### Collection\n\n" + "\n".join(f"- {k}: {v}" for k, v in result.items()) + "\n")
        if result["status"] == "failed":
            raise SystemExit(1)
    elif args.action == "verify":
        print(json.dumps(verify(root)))
    else:
        print("publish" if release(root, only_changed=args.only_changed) else "current")


if __name__ == "__main__":
    main()
