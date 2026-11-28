from datetime import datetime, timezone
import json

import pytest

from spy_volatility.workflows import retention_probe as probe


def test_disabled_probe_cannot_create_a_fake_receipt_or_study(tmp_path):
    config = tmp_path / "formal.toml"
    config.write_text('[retention]\nmode="disabled"\nprefix="formal"')
    destination = tmp_path / "probes"
    with pytest.raises(ValueError, match="disabled"):
        probe.probe(config, destination)
    assert not destination.exists()


@pytest.mark.parametrize("changed_version", [False, True])
def test_probe_preserves_isolated_package_and_checks_retry_identity(tmp_path, monkeypatch, changed_version):
    config = tmp_path / "formal.toml"
    config.write_text('[retention]\nmode="s3"\nprefix="formal"')
    class Adapter:
        def __init__(self, settings):
            assert settings["prefix"] == "formal/preflight"
            self.calls = 0
            self.instant = datetime.now(timezone.utc).isoformat()
        def preflight(self):
            return {"versioning": "Enabled", "public_access_blocked": True}
        def retain(self, archive, event_hash):
            self.calls += 1
            assert archive.is_file() and len(event_hash) == 64
            return {"server_last_modified_utc": self.instant,
                    "version_id": str(self.calls) if changed_version else "original"}
    monkeypatch.setattr(probe, "S3Retention", Adapter)
    destination = tmp_path / "probes"
    if changed_version:
        with pytest.raises(ValueError, match="original receipt"):
            probe.probe(config, destination)
        assert not list(destination.rglob("probe_result.json"))
    else:
        directory = probe.probe(config, destination)
        result = json.loads((directory / "probe_result.json").read_text())
        assert result["retry_preserved_version"] is True
    assert len(list(destination.rglob("probe.zip"))) == 1
    assert len(list(destination.rglob("first_receipt.json"))) == 1
    assert not list(tmp_path.rglob("journal.sqlite3"))
