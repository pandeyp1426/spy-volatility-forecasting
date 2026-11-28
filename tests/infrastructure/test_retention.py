import base64
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from spy_volatility.infrastructure.retention import S3Retention
from spy_volatility.workflows.pilot import sha


class FakeS3:
    def __init__(self, archive):
        self.archive = archive
        self.calls = []
        self.enabled = True
        self.version = "preserved-version-1"
        self.corrupt = False
        self.already_exists = False
        self.private = True

    def __call__(self, cmd, **options):
        assert options["check"] and options["timeout"] == 120
        assert not options.get("shell")
        self.calls.append(cmd)
        operation = cmd[2]
        if operation == "get-bucket-versioning":
            value = {"Status": "Enabled" if self.enabled else "Suspended"}
        elif operation == "get-public-access-block":
            value = {"PublicAccessBlockConfiguration": dict.fromkeys(
                ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"), self.private)}
        elif operation == "get-bucket-policy-status":
            value = {"PolicyStatus": {"IsPublic": not self.private}}
        elif operation == "put-object":
            assert cmd[cmd.index("--if-none-match") + 1] == "*"
            if self.already_exists:
                raise subprocess.CalledProcessError(1, cmd, stderr="PreconditionFailed")
            value = {"VersionId": self.version}
        else:
            assert operation == "head-object"
            value = {"VersionId": self.version, "Metadata": {"sha256": sha(self.archive), "event-hash": "e" * 64},
                     "ChecksumSHA256": "bad" if self.corrupt else base64.b64encode(bytes.fromhex(sha(self.archive))).decode(),
                     "ContentLength": self.archive.stat().st_size, "LastModified": "2026-11-12T21:05:01Z"}
        return SimpleNamespace(stdout=json.dumps(value))


def setup(tmp_path):
    archive = tmp_path / "evidence.zip"
    archive.write_bytes(b"test archive payload")
    fake = FakeS3(archive)
    adapter = S3Retention({"mode": "s3", "bucket": "test-bucket", "prefix": "test-evidence", "region": "us-east-1"}, runner=fake)
    return archive, fake, adapter


def test_version_checksum_server_timestamp_and_conditional_write(tmp_path):
    archive, fake, adapter = setup(tmp_path)
    receipt = adapter.retain(archive, "e" * 64)
    assert receipt["status"] == "retained" and receipt["server_timestamp_verified"]
    assert receipt["archive_sha256"] == sha(archive)
    assert receipt["version_id"] == fake.version
    assert receipt["server_last_modified_utc"] == "2026-11-12T21:05:01+00:00"
    assert len(fake.calls) == 5


@pytest.mark.parametrize("bad", ["versioning", "null_version", "checksum", "public"])
def test_incomplete_external_evidence_is_not_accepted(tmp_path, bad):
    archive, fake, adapter = setup(tmp_path)
    if bad == "versioning":
        fake.enabled = False
    elif bad == "null_version":
        fake.version = "null"
    elif bad == "public":
        fake.private = False
    else:
        fake.corrupt = True
    with pytest.raises(ValueError):
        adapter.retain(archive, "e" * 64)


def test_retry_recovers_same_version_without_overwriting(tmp_path):
    archive, fake, adapter = setup(tmp_path)
    fake.already_exists = True
    receipt = adapter.retain(archive, "e" * 64)
    assert receipt["version_id"] == "preserved-version-1"
    assert len(fake.calls) == 6


def test_unconfigured_retention_never_invokes_external_command(tmp_path):
    adapter = S3Retention({"mode": "disabled"}, runner=lambda *a, **kw: pytest.fail("Unexpected remote call"))
    assert adapter.retain(tmp_path / "absent", "unused")["status"] == "not_configured"


def test_missing_aws_cli_is_reported_without_inventing_receipt(tmp_path):
    archive, _, adapter = setup(tmp_path)
    def missing(*args, **kwargs):
        raise FileNotFoundError("AWS CLI v2 is unavailable")
    adapter.runner = missing
    with pytest.raises(FileNotFoundError, match="AWS CLI"):
        adapter.retain(archive, "e" * 64)
