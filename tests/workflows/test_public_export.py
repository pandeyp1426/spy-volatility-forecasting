"""Protect the public release boundary independently of browser rendering."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from spy_volatility.workflows import public_export as exporter, public_forecasts as forecasts

ROOT = Path(__file__).resolve().parents[2]
TIME = datetime(2026, 11, 19, 15, tzinfo=timezone.utc)


def approvals(root, extra):
    config = root / "configs"
    config.mkdir()
    (config / "public_forecasts.toml").write_text("schema_version = 1\n" + extra)


def test_pilot_replay_allows_ridge_roundoff_and_preserves_issued_values():
    stored = {"predictions": {"ridge": .0224, "ridge_raw": .0224, "baseline": .01},
              "floor_applied": False, "feature_order": ["log_return"]}
    rounded = math.nextafter(.0224, 0)
    verified = {**stored, "predictions": {**stored["predictions"], "ridge": rounded, "ridge_raw": rounded}}
    assert forecasts._pilot_replay_matches(verified, stored)
    assert stored["predictions"]["ridge"] == .0224
    assert verified["predictions"]["ridge"] == rounded
    for key, value in (("ridge", .0225), ("ridge_raw", float("nan")),
                       ("baseline", math.nextafter(.01, 0))):
        changed = {**verified, "predictions": {**verified["predictions"], key: value}}
        assert not forecasts._pilot_replay_matches(changed, stored)
    assert not forecasts._pilot_replay_matches({**verified, "floor_applied": True}, stored)
    assert not forecasts._pilot_replay_matches({**verified, "feature_order": []}, stored)


def test_formal_outcome_approval_rejected_even_without_database(tmp_path):
    approvals(tmp_path, '[[forecasts]]\norigin="2027-01-04"\nforecast_sha256="' + "1"*64 +
              '"\noutcome_sha256="' + "2"*64 + '"')
    with pytest.raises(ValueError, match="separately reviewed"):
        forecasts.read_forecasts(tmp_path)


def test_formal_record_before_projection_cannot_be_scored(monkeypatch):
    approval = {"origin": "2027-01-04", "forecast_sha256": "1"*64}
    f = {"forecast_session": approval["origin"], "target_sessions": [
        "2027-01-05", "2027-01-06", "2027-01-07", "2027-01-08", "2027-01-11"],
        "scheduled_close_utc": "2027-01-04T21:00:00Z", "features":dict.fromkeys(forecasts.FEATURE_COLUMNS, .01),
        "predictions":dict.fromkeys(forecasts.METHODS.values(), .01)}
    event = {"kind":"forecast", "context":{"study":"formal_2027","issue_deadline_utc":"2027-01-04T23:00:00Z"},
             "issued_at_utc":"2027-01-04T21:30:00Z","timing_status":"local_on_time",
             "private":"DO_NOT_PUBLISH", "outcome":{"observed_volatility":999}, "metrics":{"rmse_pp":555}}
    monkeypatch.setattr(forecasts,"_event",lambda *a:event)
    monkeypatch.setattr(forecasts,"_replay_forecast",lambda *a:(f,"2027-01-04T21:29:00Z"))
    monkeypatch.setattr(forecasts,"_formal_receipt",lambda *a:None)
    monkeypatch.setattr(forecasts,"forecast_errors",lambda *a:pytest.fail("Formal error calculation"))
    monkeypatch.setattr(forecasts,"_pilot_outcome",lambda *a:pytest.fail("Formal label read"))
    row = forecasts._release(None, None, None, {}, {}, {"bundle_id":"test"}, approval)
    assert row["study"] == "formal_2027" and row["outcome_status"] == "withheld"
    assert {"metrics","private","outcome"}.isdisjoint(row)
    assert row["predictions_pct"]["ridge"] == 1.

    # A pilot forecast can be published ahead of its separately approved
    # outcome. Its public row carries no zero, placeholder or private label.
    f.update(forecast_session="2026-11-12", target_sessions=[
        "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"])
    event["context"].update(study="pilot_2026", issue_deadline_utc="2026-11-12T23:00:00Z")
    event["issued_at_utc"] = "2026-11-12T21:30:00Z"
    pending = forecasts._release(None, None, None, {}, {}, {"bundle_id":"test"},
                                 {**approval, "origin":f["forecast_session"]})
    assert pending["study"] == "pilot_2026" and pending["outcome_status"] == "pending"
    assert "outcome" not in pending


def test_invalid_and_tampered_journal_events_rejected():
    db = sqlite3.connect(":memory:")
    db.execute("create table events(sequence,previous_hash,payload,event_hash)")
    digest = "1"*64
    payload = {"kind":"forecast","status":"failed","evidence_mode":"live","context":{"study":"pilot_2026","origin":"2026-11-12"}}
    db.execute("insert into events values (1,'0',?,?)",(json.dumps(payload),digest))
    with pytest.raises(ValueError,match="missing, invalid"):
        forecasts._event(db,digest,"2026-11-12",("forecast",))
    payload["status"]="valid"
    db.execute("update events set payload=?",(json.dumps(payload),))
    with pytest.raises(ValueError,match="hash mismatch"):
        forecasts._event(db,digest,"2026-11-12",("forecast",))
    db.close()


def test_explicit_outcome_must_link_to_same_forecast(monkeypatch):
    f = {"forecast_session":"2026-11-11","target_sessions":["2026-11-12","2026-11-13","2026-11-16","2026-11-17","2026-11-18"]}
    monkeypatch.setattr(forecasts,"_event",lambda *a:{"forecast_attempt_id":"other"})
    with pytest.raises(ValueError,match="does not match"):
        forecasts._pilot_outcome(None,None,{"origin":f["forecast_session"],"outcome_sha256":"x"},{"attempt_id":"approved"},f)


def test_absent_approval_and_missing_sources(tmp_path):
    approvals(tmp_path,"")
    assert forecasts.read_forecasts(tmp_path) == []
    path=tmp_path/"dashboard/public/data/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("previous")
    with pytest.raises((ValueError,FileNotFoundError)):
        exporter.export(tmp_path,now=TIME)
    assert path.read_text()=="previous"


def test_automatic_2026_release_selects_only_verified_original_forecasts():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY, payload, event_hash)")
        origin = "2026-11-20"
        record = {"context": {"origin": origin, "study": "pilot_2026"}, "kind": "forecast",
                  "status": "valid", "evidence_mode": "live", "numerical_verification_passed": True}

        def insert(digest, **overrides):
            db.execute("INSERT INTO events(payload,event_hash) VALUES (?,?)",
                       (json.dumps({**record, **overrides}), digest))

        insert("original")
        insert("demo", evidence_mode="synthetic_demo")
        insert("failed", status="failed")
        insert("invalid", numerical_verification_passed=False)
        insert("outcome", kind="outcome")
        insert("revision", revision_of="original")
        insert("formal", context={"origin": "2027-01-04", "study": "formal_2027"})
        insert("cross-year", context={"origin": "2027-01-04", "study": "pilot_2026"})
        assert list(forecasts.automatic_pilot_approvals(db, set())) == [
            {"origin": origin, "forecast_sha256": "original"}]
        insert("ambiguous")
        with pytest.raises(ValueError, match="Multiple original"):
            list(forecasts.automatic_pilot_approvals(db, set()))
        assert list(forecasts.automatic_pilot_approvals(db, {origin})) == []


def test_automatic_policy_rejects_non_boolean(tmp_path):
    approvals(tmp_path, 'automatic_2026_pilots = "false"')
    with pytest.raises(ValueError, match="schema"):
        forecasts.read_forecasts(tmp_path)


def test_consistent_release_with_fixed_timestamp(tmp_path,monkeypatch):
    (tmp_path/"configs").mkdir()
    (tmp_path/"configs/public_status.toml").write_bytes((ROOT/"configs/public_status.toml").read_bytes())
    monkeypatch.setattr(exporter,"market_history",lambda root:{"rows":[{"date":"2025-12-31"}],"acquired_at":TIME.isoformat()})
    monkeypatch.setattr(exporter,"load_history",lambda root:{"observations":[],"sources":[{"run_id":"test"}],"coverage":{"start":None,"end":None}})
    monkeypatch.setattr(exporter,"read_forecasts",lambda root:[])
    first=exporter.export(tmp_path,now=TIME)
    assert first==exporter.export(tmp_path,now=TIME)
    for entry in first["datasets"].values():
        raw=(tmp_path/"dashboard/public/data"/entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==entry["sha256"]
        assert json.loads(raw)["generated_at"]==TIME.isoformat()


def test_real_pilot_and_market_read_only_if_present():
    db=ROOT/"artifacts/operations/journal.sqlite3"
    if not db.is_file():
        pytest.skip("Designated private evidence available only on research host")
    original=hashlib.sha256(db.read_bytes()).digest()
    rows=forecasts.read_forecasts(ROOT)
    pilot=next(f for f in rows if f["study"]=="manual_pilot_2026")
    assert pilot["origin"]=="2026-11-11" and pilot["timing"]=="historical_manual_pilot"
    assert pilot["predictions_pct"]==pytest.approx({"ridge":1.6372786661,"hv5":2.6261164111,"hv20":1.4239191915})
    assert pilot["outcome"]["observed_pct"]==pytest.approx(.6995661397)
    assert pilot["outcome"]["signed_error_pp"]["ridge"]==pytest.approx(.9377125265)
    assert hashlib.sha256(db.read_bytes()).digest()==original
    market=exporter.market_history(ROOT)
    assert len(market["rows"])==2807 and market["rows"][-1]["date"]=="2025-12-31"
    assert market["rows"][0]["log_return"] is None and market["rows"][19]["volatility_20"] is None
    assert market["rows"][20]["volatility_20"]>0
