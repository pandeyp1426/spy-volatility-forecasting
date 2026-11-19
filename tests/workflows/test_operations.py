"""Deterministic operational integration; no network, refitting or reserved labels."""
from pathlib import Path
import json
import sqlite3
import tomllib

import numpy as np
import pandas as pd
import pytest

from test_pilot import prepared  # Reuse the artificial, no-fit/no-response fixture.
from spy_volatility.core import research
from spy_volatility.core import data
from spy_volatility.core.data import DownloadError
from spy_volatility.core.outcomes import forecast_errors, realized_volatility, study_for
from spy_volatility.infrastructure.forecast_store import ForecastStore
from spy_volatility.workflows import operations, pilot, prospective
from spy_volatility.workflows.operations_demo import SyntheticMarket


@pytest.fixture
def environment(prepared):
    config_path, bundle = prepared
    record = json.loads((bundle / "freeze_record.json").read_text())
    pilot.write_json(bundle / "inputs/run_record.json", {"config": {"data": {"start": "2014-11-01"}}})
    record["source_artifact_sha256"]["run_record.json"] = pilot.sha(bundle / "inputs/run_record.json")
    record["artifact_sha256"]["inputs/run_record.json"] = pilot.sha(bundle / "inputs/run_record.json")
    prospective.build_schedule(record["config"]).to_csv(bundle / "evaluation_schedule.csv", index=False)
    record["artifact_sha256"]["evaluation_schedule.csv"] = pilot.sha(bundle / "evaluation_schedule.csv")
    pilot.write_json(bundle / "freeze_record.json", record)
    config = config_path.with_name("operations.toml")
    config.write_text(f'''[prepared]
bundle = "artifacts/protocols/artificial"
freeze_record_sha256 = "{pilot.sha(bundle / 'freeze_record.json')}"
model_sha256 = "{record['model_sha256']}"
[collection]
store = "artifacts/operations"
pilot_start = "2026-11-12"
''')
    market = SyntheticMarket()
    worker = operations.Operations(config, clock=market.now, acquire=market.acquire,
                                   store_path=config.parent.parent / "artifacts/synthetic", evidence_mode="synthetic_demo")
    return worker, market, bundle


def emitted(results, kind):
    return [r for r in results if r.get("kind") == kind]


def test_end_to_end_duplicate_maturity_revision_and_replay(environment):
    worker, market, bundle = environment
    before = {str(p): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    first = worker.execute("forecast")[0]
    assert first["kind"] == "forecast", first
    assert first["role"] == "first_on_time_candidate"
    assert first["prospective_validity_claim"] is False
    assert market.calls == 1
    original = {str(p): p.read_bytes() for p in worker.store.evidence_path(first["evidence_dir"]).rglob("*") if p.is_file()}
    assert worker.execute("forecast")[0]["status"] == "already_recorded"
    assert worker.execute("outcomes")[0]["status"] == "not_mature"
    assert market.calls == 1
    market.instant = pd.Timestamp(first["context"]["target_close_utc"])
    assert worker.execute("outcomes")[0]["status"] == "not_mature"
    market.instant += pd.Timedelta(minutes=5)
    complete = worker.execute("outcomes")
    label, comparison = emitted(complete, "outcome")[0], emitted(complete, "comparison")[0]
    assert label["role"] == "first_timely_label_candidate"
    assert label["context"]["study"] == "pilot_2026"
    dates = market.prices.loc[:first["context"]["target_sessions"][-1]]
    research_target = research.build_features(dates).loc[first["context"]["origin"], "target"]
    assert label["outcome"]["observed_volatility"] == pytest.approx(research_target, rel=1e-9, abs=1e-12)
    for name in ("ridge", "baseline", "baseline_5"):
        expected = 100 * (first["forecast"]["predictions"][name] - research_target)
        assert comparison["comparison"]["errors"][name]["signed_error_pp"] == pytest.approx(expected)
        assert comparison["comparison"]["errors"][name]["absolute_error_pp"] == pytest.approx(abs(expected))
    worker.execute("outcomes")
    assert market.calls == 2
    market.instant += pd.Timedelta(minutes=5)
    market.revision = .003
    revised = worker.execute("outcomes", origin=first["context"]["origin"], reason="Artificial correction")
    correction = emitted(revised, "outcome")[0]
    assert correction["role"] == "revised_sensitivity" and correction["revision_of"] == label["attempt_id"]
    assert correction["outcome"]["observed_volatility"] != label["outcome"]["observed_volatility"]
    assert worker.execute("verify")[0]["status"] == "passed"
    assert before == {str(p): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    assert all(Path(name).read_bytes() == content for name, content in original.items())


def test_live_style_timestamp_resolution_survives_exact_archive_check(environment):
    worker, market, _ = environment
    original = market.acquire
    def provider_seconds(settings, directory):
        prices, metadata, audit = original(settings, directory)
        return prices.set_axis(prices.index.as_unit("s")), metadata, audit
    worker.acquire = provider_seconds
    forecast = worker.execute("forecast")[0]
    assert forecast["kind"] == "forecast", forecast
    market.instant = pd.Timestamp(forecast["context"]["target_close_utc"]) + pd.Timedelta(minutes=1)
    assert emitted(worker.execute("outcomes"), "outcome")[0]["status"] == "valid"
    assert worker.execute("verify")[0]["status"] == "passed"


def test_failed_download_retries_and_never_replaces_first_valid_forecast(environment):
    worker, market, _ = environment
    def failure(*args, **kwargs):
        raise DownloadError("Artificial offline connection")
    worker.acquire = failure
    failed = worker.execute("forecast")[0]
    assert failed["kind"] == "attempt_failed" and failed["status"] == "failed"
    worker.acquire = market.acquire
    market.instant += pd.Timedelta(minutes=5)
    first = worker.execute("forecast")[0]
    market.instant += pd.Timedelta(minutes=5)
    market.revision = .001
    revision = worker.execute("forecast", reason="Revised provider prices")[0]
    assert revision["role"] == "revision"
    assert revision["revision_of"] == first["attempt_id"]
    assert len(worker.rows("attempt_failed")) == 1
    assert len(worker.rows("forecast")) == 2
    assert worker.execute("verify")[0]["status"] == "passed"


@pytest.mark.parametrize("bad", ["missing", "nan", "zero", "stale_vintage", "after_origin", "inconsistent_return"])
def test_bad_forecast_inputs_are_retained_and_rejected(environment, bad):
    worker, market, _ = environment
    original = market.acquire
    def corrupt(settings, output):
        p, metadata, audit = original(settings, output)
        if bad == "inconsistent_return":
            p.iloc[-1] *= 2
            return p, metadata, audit
        if bad == "stale_vintage":
            metadata["retrieved_at_utc"] = "2026-11-11T22:00:00Z"
        else:
            raw = pd.read_csv(output / "raw.csv", index_col="Date", parse_dates=["Date"])
            if bad == "missing":
                raw = raw.iloc[:-1]
            elif bad == "after_origin":
                raw.loc[pd.Timestamp(settings["end"])] = 500
            else:
                raw.iloc[-1, 0] = np.nan if bad == "nan" else 0.
            raw.to_csv(output / "raw.csv")
            metadata.update(sha256=pilot.sha(output / "raw.csv"), row_count=len(raw),
                            actual_date_range={"start": raw.index.min().isoformat(), "end": raw.index.max().isoformat()})
        pilot.write_json(output / "metadata.json", metadata)
        return p, metadata, audit
    worker.acquire = corrupt
    result = worker.execute("forecast")[0]
    assert result["kind"] == "attempt_failed" and result["status"] == "invalid", result
    assert not worker.rows("forecast")
    assert (worker.store.evidence_path(result["evidence_dir"]) / "snapshot/raw.csv").exists()


def test_outcome_invalid_data_and_label_delay_are_not_promoted(environment):
    worker, market, _ = environment
    forecast = worker.execute("forecast")[0]
    close = pd.Timestamp(forecast["context"]["target_close_utc"])
    market.instant = close + pd.Timedelta(minutes=1)
    original = market.acquire
    market.prices.loc[forecast["context"]["target_sessions"][2]] = np.nan
    result = worker.execute("outcomes")
    assert emitted(result, "attempt_failed")[0]["status"] == "invalid"
    assert not worker.rows("outcome") and not worker.rows("comparison")
    market.prices.loc[forecast["context"]["target_sessions"][2]] = 501.
    market.instant = close + pd.Timedelta(hours=24, seconds=1)
    result = worker.execute("outcomes")
    assert emitted(result, "outcome_missing")
    assert emitted(result, "outcome")[0]["role"] == "late_sensitivity"
    assert emitted(result, "comparison")[0]["outcome_role"] == "late_sensitivity"


@pytest.mark.parametrize("instant,origin,timing", [
    ("2026-11-27T18:01:00Z", "2026-11-27", "local_on_time"),
    ("2026-11-27T20:00:00Z", "2026-11-27", "local_on_time"),
    ("2026-11-27T20:00:01Z", "2026-11-27", "late"),
    ("2026-11-26T21:00:00Z", "2026-11-25", "late"),
    ("2026-11-29T21:00:00Z", "2026-11-27", "late"),
    ("2027-03-15T20:05:00Z", "2027-03-15", "local_on_time"),
])
def test_calendar_origin_deadline_and_dst(environment, instant, origin, timing):
    worker, market, _ = environment
    market.instant = pd.Timestamp(instant)
    result = worker.execute("forecast")[0]
    assert result["kind"] == "forecast", result
    assert result["context"]["origin"] == origin and result["timing_status"] == timing


def test_deadline_is_checked_after_acquisition_and_clock_rollover(environment):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2026-11-12T22:59:00Z")
    original = market.acquire
    def delayed(settings, output):
        market.instant += pd.Timedelta(minutes=2)
        return original(settings, output)
    worker.acquire = delayed
    assert worker.execute("forecast")[0]["timing_status"] == "late"


def test_downtime_missing_records_are_idempotent_and_not_backfilled(environment):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2026-11-17T23:05:00Z")
    results = worker.execute("cycle")
    missing = emitted(results, "forecast_missing")
    assert {r["context"]["origin"] for r in missing} == {"2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"}
    assert len(worker.rows("forecast")) == 1
    assert worker.rows("forecast")[0]["role"] == "late_diagnostic"
    assert not emitted(worker.execute("cycle"), "forecast_missing")
    assert len(worker.rows("forecast")) == 1


def test_formal_outcomes_are_archived_but_not_scored_or_displayed_early(environment, monkeypatch):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2027-01-04T21:05:00Z")
    first = worker.execute("forecast")[0]
    assert first["context"]["study"] == "formal_2027"
    market.instant = pd.Timestamp(first["context"]["target_close_utc"]) + pd.Timedelta(minutes=5)
    original = operations.forecast_errors
    monkeypatch.setattr(operations, "forecast_errors", lambda *a: pytest.fail("Premature formal errors"))
    result = worker.execute("outcomes")
    label = emitted(result, "outcome")[0]
    assert "outcome" not in operations.public_result(label)
    assert not worker.rows("comparison")
    assert worker.execute("score")[0]["status"] == "embargoed"
    assert worker.execute("verify")[0]["status"] == "passed"
    monkeypatch.setattr(operations, "forecast_errors", original)
    market.instant = pd.Timestamp("2028-01-10T05:59:59Z")
    assert worker.execute("score")[0]["status"] == "embargoed"
    market.instant = pd.Timestamp("2028-01-10T06:00:00Z")
    assert emitted(worker.execute("score"), "comparison")


def test_no_2027_pilot_alias_or_cross_year_target():
    f = {"forecast_session": "2027-01-04", "target_sessions": ["2027-01-05", "2027-01-06", "2027-01-07", "2027-01-08", "2027-01-11"],
         "study": "pilot_2026", "predictions": {"ridge": .01, "baseline": .02, "baseline_5": .03}}
    with pytest.raises(ValueError, match="embargoed"):
        forecast_errors(f, .02, pd.Timestamp("2027-02-01T00:00Z"))
    with pytest.raises(ValueError, match="contained"):
        study_for("2026-12-31", ["2027-01-04"]*5)


def test_frozen_integrity_and_different_calendar_fail_before_download(environment, monkeypatch):
    worker, market, bundle = environment
    monkeypatch.setattr(operations.prospective, "build_schedule", lambda c: pd.DataFrame())
    result = worker.execute("forecast")[0]
    assert result["status"] == "failed" and "calendar" in result["error"]["message"]
    assert market.calls == 0
    (bundle / "model.json").write_text("{}")
    result = worker.execute("forecast")[0]
    assert result["status"] == "failed" and "SHA-256" in result["error"]["message"]
    assert market.calls == 0


def test_crash_recovery_retains_partial_evidence_and_lock_releases(environment):
    worker, market, _ = environment
    worker.execute("status")
    start, output = worker.start("forecast", worker.context("2026-11-12"))
    (output / "partial.txt").write_text("Preserve interrupted data")
    worker.execute("status")
    interrupted = worker.rows("attempt_failed")[0]
    assert interrupted["status"] == "interrupted" and interrupted["attempt_id"] == start["attempt_id"]
    assert (output / "partial.txt").read_text() == "Preserve interrupted data"
    with worker.store.exclusive():
        contender = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                          store_path=worker.store_path, evidence_mode="synthetic_demo")
        assert contender.execute("forecast")[0]["status"] == "busy"
    assert worker.execute("forecast")[0]["kind"] == "forecast"


def test_append_only_triggers_and_tamper_detection(environment):
    worker, _, _ = environment
    first = worker.execute("forecast")[0]
    with worker.store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE events SET payload='{}'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM events")
    raw = worker.store.evidence_path(first["evidence_dir"]) / "snapshot/raw.csv"
    raw.write_text(raw.read_text() + "\n")
    with pytest.raises(ValueError, match="SHA-256"):
        worker.execute("verify")


def test_modes_and_config_cannot_mix_in_existing_store(environment):
    worker, market, _ = environment
    worker.execute("forecast")
    count = len(worker.rows())
    live = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire, store_path=worker.store_path)
    with pytest.raises(ValueError, match="identity"):
        live.execute("forecast")
    assert len(worker.rows()) == count
    worker.config_path.write_text(worker.config_path.read_text() + "\n# changed\n")
    changed = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                    store_path=worker.store_path, evidence_mode="synthetic_demo")
    with pytest.raises(ValueError, match="identity"):
        changed.execute("forecast")


def test_ineligible_last_five_formal_origins_are_not_acquired(environment):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2027-12-27T21:05Z")
    assert worker.execute("forecast")[0]["status"] == "not_eligible"
    assert market.calls == 0


def test_original_manual_pilot_import_is_verified_and_preserved(environment, monkeypatch):
    worker, market, _ = environment
    pilot_config = worker.config_path.with_name("pilot.toml")
    config = tomllib.loads(pilot_config.read_text())
    old_hash = config["prepared"]["freeze_record_sha256"]
    pilot_config.write_text(pilot_config.read_text().replace(old_hash, worker.config["prepared"]["freeze_record_sha256"]))
    def download(**settings):
        p = market.prices.loc[(market.prices.index >= settings["start"]) & (market.prices.index < settings["end"])]
        return pd.DataFrame({"Adj Close": p, "Close": p * 1.002})
    monkeypatch.setattr(data.yf, "download", download)
    manual = pilot.run_pilot(pilot_config)
    assert manual["status"] == "success", manual
    path = Path(manual["output_dir"])
    before = {str(p): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    relative = path.relative_to(worker.root).as_posix()
    with worker.config_path.open("a") as stream:
        stream.write(f'\n[manual_pilot]\npath = "{relative}"\nrecord_sha256 = "{pilot.sha(path / "pilot_record.json")}"\n')
    worker = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                   store_path=worker.store_path, evidence_mode="synthetic_demo")
    first = worker.execute("import-pilot")[0]
    assert first["kind"] == "pilot_import" and first["role"] == "separate_manual_pilot"
    assert first["context"]["origin"] == "2026-11-11"
    assert first["issued_at_utc"] == manual["created_at_utc"]
    assert worker.execute("import-pilot")[0]["status"] == "already_imported"
    assert worker.execute("outcomes")[0]["status"] == "not_mature"
    market.instant = pd.Timestamp(first["context"]["target_close_utc"]) + pd.Timedelta(minutes=5)
    result = worker.execute("outcomes")
    assert emitted(result, "comparison")[0]["forecast_role"] == "separate_manual_pilot"
    assert all(Path(name).read_bytes() == content for name, content in before.items())


def test_live_store_rejects_synthetic_acquisition(environment):
    worker, market, _ = environment
    worker = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                   store_path=worker.store_path.with_name("live_test"))
    result = worker.execute("forecast")[0]
    assert result["status"] == "invalid" and "Synthetic/live" in result["error"]["message"]


def test_failed_manual_import_does_not_disappear(environment):
    worker, market, _ = environment
    with worker.config_path.open("a") as stream:
        stream.write('\n[manual_pilot]\npath = "unavailable"\nrecord_sha256 = "missing"\n')
    worker = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                   store_path=worker.store_path, evidence_mode="synthetic_demo")
    result = worker.execute("import-pilot")[0]
    assert result["kind"] == "operation_failed" and result["status"] == "failed"


def test_original_schedule_and_first_five_features_match_research(environment):
    worker, market, _ = environment
    forecast = worker.execute("forecast")[0]
    historical = research.build_features(market.prices)
    expected = historical.loc[forecast["context"]["origin"]]
    for name, value in forecast["forecast"]["features"].items():
        assert value == pytest.approx(expected[name], rel=1e-9, abs=1e-12)


def test_scheduler_proposal_is_disabled_unregistered_and_non_overwriting(tmp_path):
    import os
    import subprocess
    import xml.etree.ElementTree as ET
    if os.name != "nt":
        pytest.skip("Windows Task Scheduler proposal")
    script = Path(__file__).resolve().parents[2] / "scripts/prepare_forecast_task.ps1"
    output = tmp_path / "proposal.xml"
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(script), "-OutputPath", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    task = ET.parse(output)
    assert task.findtext("t:Settings/t:Enabled", namespaces=ns) == "false"
    assert task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns) == "PT5M"
    assert task.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert task.findtext("t:Settings/t:WakeToRun", namespaces=ns) == "true"
    assert task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    assert "-WindowStyle Hidden" in task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns)
    assert "Register-ScheduledTask" not in script.read_text()
    before = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == before


def test_known_notice_prevents_forecasting_from_assumed_close(environment):
    worker, market, _ = environment
    notice_dir = worker.root / "artifacts/market_notices"
    notice_dir.mkdir(parents=True)
    pilot.write_json(notice_dir / "artificial_notice.json", {
        "acquired_at_utc": "2026-11-12T20:00Z", "official_source_url": "https://www.nyse.com/example-test-notice",
        "affected_sessions": ["2026-11-12"], "reason": "Synthetic early-close change for guard test"})
    result = worker.execute("forecast")[0]
    assert result["status"] == "invalid" and "Known market interruption" in result["error"]["message"]
    assert market.calls == 0


def test_live_formal_collection_requires_external_retention(environment):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2027-01-04T21:05Z")
    worker = operations.Operations(worker.config_path, clock=market.now, acquire=market.acquire,
                                   store_path=worker.store_path.with_name("live_formal"))
    result = worker.execute("forecast")[0]
    assert result["status"] == "invalid" and "external retention" in result["error"]["message"]
    assert market.calls == 0


def test_persistence_failure_does_not_create_a_successful_forecast(environment, monkeypatch):
    worker, _, _ = environment
    original = ForecastStore.append
    def fail_on_forecast(store, payload):
        if payload["kind"] == "forecast":
            raise OSError("Artificial disk-full persistence failure")
        return original(store, payload)
    monkeypatch.setattr(ForecastStore, "append", fail_on_forecast)
    result = worker.execute("forecast")[0]
    assert result["kind"] == "attempt_failed" and result["status"] == "failed"
    assert not worker.rows("forecast")
    assert "disk-full" in result["error"]["message"]


def test_aggregate_metrics_use_one_pair_per_origin_and_verify(environment):
    worker, market, _ = environment
    first = worker.execute("forecast")[0]
    worker.execute("forecast", reason="Synthetic repeated issue")
    market.instant = pd.Timestamp(first["context"]["target_close_utc"]) + pd.Timedelta(minutes=5)
    worker.execute("outcomes")
    result = worker.execute("metrics", study="pilot_2026")[0]
    assert result["summary"]["metrics"]["ridge"]["n"] == 1
    assert len(result["selected_pairs"]) == 1
    assert worker.execute("verify")[0]["status"] == "passed"


def test_external_package_retry_is_deterministic_and_retained_separately(environment):
    worker, market, _ = environment
    original = market.acquire
    def source(settings, output):
        p, metadata, audit = original(settings, output)
        metadata["synthetic"] = False  # Test-only provider fixture for live-path code.
        metadata["actual_source"] = "Artificial integration test; no real provider call"
        pilot.write_json(output / "metadata.json", metadata)
        return p, metadata, audit
    worker = operations.Operations(worker.config_path, clock=market.now, acquire=source,
                                   store_path=worker.store_path.with_name("retention_test"))
    class Remote:
        enabled = True
        def __init__(self):
            self.hashes = []
        def retain(self, path, event_hash):
            digest = pilot.sha(path)
            self.hashes.append(digest)
            if len(self.hashes) == 1:
                raise OSError("Artificial remote outage")
            return {"status": "retained", "archive_sha256": digest, "server_timestamp_verified": True,
                    "server_last_modified_utc": market.instant.isoformat(), "version_id": "test-version"}
    remote = Remote()
    worker.retention = remote
    forecast = worker.execute("forecast")[0]
    assert forecast["external_retention_status"] == "failed"
    retry = worker.execute("retain")
    assert emitted(retry, "retention_receipt")
    # The attempt failure and first successful record remain, with two equal
    # packages for the same immutable record despite retry time advancing.
    assert remote.hashes[0] == remote.hashes[1]
    assert worker.execute("verify")[0]["status"] == "passed"


def test_original_november_11_pilot_remains_exactly_replayable():
    root = Path(__file__).resolve().parents[2]
    path = root / "artifacts/pilots/20261112T050827_pilot_76608a08"
    if not path.exists():
        pytest.skip("Local archived November 11 pilot is required for this regression check")
    before = pilot.sha(path / "pilot_record.json")
    result = pilot.replay(path)
    assert result["forecast"]["predictions"]["ridge"] == 0.016372786661413053
    assert result["forecast"]["predictions"]["baseline"] == 0.014239191914939334
    assert result["forecast"]["predictions"]["baseline_5"] == 0.026261164111068235
    assert pilot.sha(path / "pilot_record.json") == before == "efc37527c8043ab2a75fca08a99046a5b11fe93bdd0b3b1599d0f84529591124"


def test_formal_sample_uses_first_fully_qualified_record_not_unretained_attempt(environment):
    worker, market, _ = environment
    market.instant = pd.Timestamp("2027-01-04T21:05Z")
    first = worker.execute("forecast")[0]
    market.instant += pd.Timedelta(minutes=5)
    second = worker.execute("forecast", reason="Synthetic retry after retention failure")[0]
    # Synthetic external receipt: never presented as a real S3 interaction.
    worker.event("retention_receipt", status="retained", retained_event_hash=second["event_hash"],
                 retained_by_deadline=True, context=second["context"], receipt={"synthetic": True})
    market.instant = pd.Timestamp(first["context"]["target_close_utc"]) + pd.Timedelta(minutes=5)
    worker.execute("outcomes")
    market.instant = pd.Timestamp("2028-01-10T06:00Z")
    result = worker.execute("metrics", study="formal_2027")[0]
    assert result["summary"]["metrics"]["ridge"]["n"] == 1
    assert result["selected_pairs"][0]["forecast_id"] == second["attempt_id"]
    assert result["selected_pairs"][0]["forecast_id"] != first["attempt_id"]
