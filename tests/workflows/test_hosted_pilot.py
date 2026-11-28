from io import BytesIO
import json
import sqlite3
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from spy_volatility.workflows import hosted_pilot as hosted
from spy_volatility.infrastructure.forecast_store import ForecastStore


def test_hosted_tick_cannot_initialize_a_missing_or_empty_journal(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/operations.toml").write_text(
        '[collection]\nstore="artifacts/operations"\npilot_start="2026-11-12"\n[prepared]\nbundle="bundle"')
    with pytest.raises(FileNotFoundError, match="journal"):
        hosted.collect(tmp_path)
    with pytest.raises(FileNotFoundError, match="journal"):
        hosted.verify(tmp_path)
    state = tmp_path / "artifacts/operations"
    assert not state.exists()
    state.mkdir(parents=True)
    with sqlite3.connect(state / "journal.sqlite3") as db:
        db.execute("CREATE TABLE events(sequence, payload)")
    with pytest.raises(ValueError, match="configuration"):
        hosted.collect(tmp_path)
    with pytest.raises(ValueError, match="configuration"):
        hosted.verify(tmp_path)


@pytest.mark.parametrize(("mode", "expected"), [("current", False), ("old", True), ("unreachable", True)])
def test_retry_compares_the_deployed_rows_before_publishing(tmp_path, monkeypatch, mode, expected):
    rows = [{"id": "verified"}]
    exported = []
    monkeypatch.setattr(hosted, "read_forecasts", lambda root: rows)
    coverage = {"missed_origins": [], "missed_outcome_origins": []}
    monkeypatch.setattr(hosted, "read_coverage", lambda root: coverage)
    monkeypatch.setattr(hosted.public_export, "export", exported.append)

    def fetch(url, timeout):
        if url.endswith("status.json"):
            return BytesIO(json.dumps({"data": {"collection": coverage}}).encode())
        assert url == hosted.PUBLISHED
        if mode == "unreachable":
            raise URLError("offline")
        data = {"dataset": "forecasts", "data": {"rows": rows if mode == "current" else []}}
        return BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(hosted, "urlopen", fetch)
    assert hosted.release(tmp_path, only_changed=True) is expected
    assert exported == ([tmp_path] if expected else [])


def test_handoff_preserves_the_remote_journal_prefix(tmp_path, monkeypatch):
    seed = hosted.PilotEvidenceSeed.__new__(hosted.PilotEvidenceSeed)
    seed.root = tmp_path / "app"
    seed.ops = SimpleNamespace(store_path=seed.root / "artifacts/operations")
    seed.destination = tmp_path / "seed"
    checkout = tmp_path / "private"
    local = ForecastStore(seed.destination / "artifacts/operations")
    remote = ForecastStore(checkout / "artifacts/operations")
    monkeypatch.setattr(seed, "create", lambda: None)
    local.append({"kind": "start"})
    remote.append({"kind": "start"})
    head = local.append({"kind": "pilot"})
    assert seed.advance_checkout(checkout) == head["event_hash"]
    assert remote.records() == local.records()
    remote.append({"kind": "independent"})
    local.append({"kind": "different"})
    preserved = remote.db.read_bytes()
    with pytest.raises(ValueError, match="diverged"):
        seed.advance_checkout(checkout)
    assert remote.db.read_bytes() == preserved


def test_new_missing_session_publishes_even_when_forecasts_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(hosted, "read_forecasts", lambda root: [])
    monkeypatch.setattr(hosted, "read_coverage", lambda root: {"missed_origins": ["2026-11-27"], "missed_outcome_origins": []})
    def fetch(url, timeout):
        data = {"dataset": "forecasts", "data": {"rows": []}} if url.endswith("forecasts.json") else {
            "data": {"collection": {"missed_origins": [], "missed_outcome_origins": []}}}
        return BytesIO(json.dumps(data).encode())
    monkeypatch.setattr(hosted, "urlopen", fetch)
    exported = []
    monkeypatch.setattr(hosted.public_export, "export", exported.append)
    assert hosted.release(tmp_path, only_changed=True)
    assert exported == [tmp_path]
