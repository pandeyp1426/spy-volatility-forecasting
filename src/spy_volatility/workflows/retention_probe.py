"""Validate an isolated, genuine S3 timestamp receipt; never create a forecast."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tomllib
from uuid import uuid4
import zipfile

import pandas as pd

from spy_volatility.infrastructure.retention import S3Retention
from spy_volatility.workflows.pilot import sha


def probe(config_path, destination):
    config = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))["retention"]
    # The test prefix is separate from all production event keys.
    config = {**config, "prefix": config["prefix"].rstrip("/") + "/preflight"}
    adapter = S3Retention(config)
    checks = adapter.preflight()  # Fail before creating any local probe if unconfigured.
    directory = Path(destination) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    began = datetime.now(timezone.utc)
    record = {"kind": "retention_probe", "id": directory.name,
              "created_at_utc": began.isoformat(), "is_forecast": False}
    archive = directory / "probe.zip"
    with zipfile.ZipFile(archive, "x") as bundle:
        bundle.writestr("record.json", json.dumps(record, sort_keys=True))
    event_hash = sha(archive)
    receipt = adapter.retain(archive, event_hash)
    (directory / "first_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    retry = adapter.retain(archive, event_hash)
    if receipt != retry:
        raise ValueError("Conditional retry did not return the original receipt")
    ended = datetime.now(timezone.utc)
    server = pd.Timestamp(receipt["server_last_modified_utc"])
    if not pd.Timestamp(began).floor("s") <= server <= pd.Timestamp(ended).ceil("s"):
        raise ValueError("S3 timestamp falls outside the observed probe interval; check clock")
    result = {"status": "passed", "checks": checks, "started_at_utc": began.isoformat(),
              "finished_at_utc": ended.isoformat(), "retry_preserved_version": True, "receipt": receipt,
              "credential_scope_review": "Requires administrator review of effective IAM policies"}
    (directory / "probe_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/retention_probes"))
    args = parser.parse_args()
    print(probe(args.config, args.output))


if __name__ == "__main__":
    main()
