"""Optional AWS CLI v2 adapter for independently timestamped, versioned evidence.

Credentials use the normal AWS credential chain, never configuration literals.
Unique, conditional object creation preserves earlier versions and retries.
"""
import base64
import json
from pathlib import Path
import subprocess

import pandas as pd

from spy_volatility.workflows.pilot import sha


class S3Retention:
    def __init__(self, config: dict, runner=subprocess.run):
        self.config, self.runner = config, runner
        if config.get("mode", "disabled") not in ("disabled", "s3"):
            raise ValueError("Retention mode must be disabled or s3")
        if self.enabled and not all(config.get(k) for k in ("bucket", "prefix", "region")):
            raise ValueError("S3 retention requires bucket, prefix and region")

    @property
    def enabled(self):
        return self.config.get("mode") == "s3"

    def call(self, operation, *arguments):
        cmd = ["aws", "s3api", operation, "--bucket", self.config["bucket"],
               "--region", self.config["region"], "--output", "json", "--no-cli-pager", *arguments]
        if self.config.get("profile"):
            cmd.extend(["--profile", self.config["profile"]])
        response = self.runner(cmd, capture_output=True, text=True, check=True, timeout=120)
        return json.loads(response.stdout or "{}")

    def retain(self, archive: Path, event_hash: str) -> dict:
        if not self.enabled:
            return {"status": "not_configured", "server_timestamp_verified": False}
        if self.call("get-bucket-versioning").get("Status") != "Enabled":
            raise ValueError("External evidence bucket must have versioning Enabled")
        digest = sha(archive)
        checksum = base64.b64encode(bytes.fromhex(digest)).decode()
        key = self.config["prefix"].strip("/") + "/" + event_hash + ".zip"
        try:
            result = self.call("put-object", "--key", key, "--body", str(archive.resolve()),
                               "--if-none-match", "*", "--metadata", f"sha256={digest},event-hash={event_hash}",
                               "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum)
        except subprocess.CalledProcessError:
            # An upload may have committed before a timeout/retry. Only accept
            # the pre-existing immutable key if its identity matches exactly.
            result = self.call("head-object", "--key", key, "--checksum-mode", "ENABLED")
        version_id = result.get("VersionId")
        if not version_id or version_id == "null":
            raise ValueError("S3 did not return a durable object version ID")
        head = self.call("head-object", "--key", key, "--version-id", version_id, "--checksum-mode", "ENABLED")
        if (head.get("VersionId") != version_id or head.get("Metadata", {}).get("sha256") != digest
                or head.get("Metadata", {}).get("event-hash") != event_hash
                or head.get("ChecksumSHA256") != checksum or head.get("ContentLength") != archive.stat().st_size):
            raise ValueError("External version/checksum/size verification failed")
        modified = pd.Timestamp(head["LastModified"])
        if modified.tz is None:
            raise ValueError("External server timestamp must be timezone-aware")
        return {"status": "retained", "provider": "AWS S3", "bucket": self.config["bucket"],
                "key": key, "version_id": version_id, "archive_sha256": digest,
                "server_last_modified_utc": modified.tz_convert("UTC").isoformat(),
                "server_timestamp_verified": True, "checksum_verified": True,
                "limitations": "Proves this archived version existed by S3 LastModified, not provider publication time; protect version deletion with IAM/Object Lock"}
