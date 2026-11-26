"""Manual/scheduler-invoked collection ticks; never registers a scheduler.

Run ``python -m spy_volatility.workflows.operations --help``. Production CLI
timestamps always come from the current UTC clock. Synthetic demonstrations use
a separate, permanently labelled store and cannot become real observations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import sys
import tomllib
from uuid import uuid4
import zipfile

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from spy_volatility.core.data import DataAuditError, DownloadError, get_snapshot
from spy_volatility.core.outcomes import SCORE_NOT_BEFORE, aggregate_errors, forecast_errors, realized_volatility, study_for
from spy_volatility.infrastructure.forecast_store import BusyError, ForecastStore
from spy_volatility.infrastructure.provenance import copy_source, source_hashes
from spy_volatility.infrastructure.retention import S3Retention
from spy_volatility.workflows import pilot, prospective


def utc_now():
    return datetime.now(timezone.utc)


def dates(index):
    return pd.DatetimeIndex(index).strftime("%Y-%m-%d").tolist()


class Operations:
    def __init__(self, config_path="configs/operations.toml", *, clock=utc_now,
                 acquire=get_snapshot, store_path=None, evidence_mode="live"):
        self.config_path = Path(config_path).resolve()
        self.root = self.config_path.parent.parent
        self.config = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        self.config_hash = pilot.sha(self.config_path)
        self.bundle = self.root / self.config["prepared"]["bundle"]
        self.store_path = Path(store_path or self.root / self.config["collection"]["store"]).resolve()
        self.clock, self.acquire, self.mode = clock, acquire, evidence_mode
        self.retention = S3Retention(self.config.get("retention", {}))
        if evidence_mode not in ("live", "synthetic_demo"):
            raise ValueError("Unknown evidence mode")
        if evidence_mode == "synthetic_demo" and store_path is None:
            raise ValueError("Synthetic data requires an explicit separate store")
        start = pd.Timestamp(self.config["collection"]["pilot_start"])
        if start.year != 2026 or start.tz is not None:
            raise ValueError("pilot_start must be a 2026 session date")

    def now(self):
        instant = pd.Timestamp(self.clock())
        if instant.tz is None:
            raise ValueError("Clock must be timezone-aware")
        return instant.tz_convert("UTC")

    def check(self):
        """Read-only readiness check: no store creation, acquisition or fitting."""
        self.model, self.identity = pilot.load_prepared(self.bundle, self.config["prepared"])
        self.protocol = tomllib.loads((self.bundle / "source/prospective.toml").read_text(encoding="utf-8"))
        time_columns = ["forecast_date", "market_open", "market_close", "issue_deadline_utc", "target_start",
                        "target_end", "target_close_utc", "label_deadline_utc"]
        self.frozen_calendar = pd.read_csv(self.bundle / "evaluation_schedule.csv", parse_dates=time_columns)
        current = prospective.build_schedule(self.protocol)
        try:
            pd.testing.assert_frame_equal(current, self.frozen_calendar, check_dtype=False, check_freq=False)
        except AssertionError as error:
            raise ValueError("NYSE calendar differs from frozen schedule; official documented amendment required") from error
        parent = json.loads((self.bundle / "inputs/run_record.json").read_text(encoding="utf-8"))
        self.grid_start = parent["config"]["data"]["start"]
        self.calendar = mcal.get_calendar("NYSE").schedule(self.grid_start, "2028-02-01")
        return {"status": "ready_for_review", "prepared": self.identity,
                "scheduler_enabled_by_this_command": False, "external_timestamp_retention": self.retention.enabled,
                "external_retention_connection_verified": False,
                "aws_cli_available": shutil.which("aws") is not None,
                "prospective_validity_claim": False, "calendar_version": version("pandas_market_calendars")}

    def context(self, origin):
        origin = pd.Timestamp(origin)
        pos = self.calendar.index.get_loc(origin)
        future = self.calendar.iloc[pos+1:pos+6]
        study = study_for(origin.date().isoformat(), dates(future.index))
        close = self.calendar.market_close.iloc[pos]
        target_close = future.market_close.iloc[-1]
        if study == "formal_2027":
            frozen = self.frozen_calendar.set_index("forecast_date").loc[origin]
            if not bool(frozen.eligible_forecast_origin):
                raise ValueError("Origin excluded by frozen 2027 containment rule")
            if close != frozen.market_close or future.index[-1] != frozen.target_end:
                raise ValueError("Forecast calendar differs from frozen 2027 origin")
            position = int(frozen.session_position)
        else:
            position = int(((self.calendar.index.year == 2026) & (self.calendar.index <= origin)).sum() - 1)
        return {"origin": origin.date().isoformat(), "study": study, "session_position": position,
                "global_session_number": int(pos), "global_session_grid_start": self.grid_start,
                "session_position_anchor": f"{origin.year}-01-01 NYSE session grid",
                "target_sessions": dates(future.index), "scheduled_close_utc": close.isoformat(),
                "target_start": dates(future.index)[0], "target_end": dates(future.index)[-1],
                "scheduled_close_eastern": close.tz_convert("America/New_York").isoformat(),
                "actual_close_utc": None, "close_basis": "versioned NYSE schedule; not independently observed",
                "issue_deadline_utc": (close + pd.Timedelta(minutes=120)).isoformat(),
                "target_close_utc": target_close.isoformat(),
                "label_deadline_utc": (target_close + pd.Timedelta(hours=24)).isoformat()}

    def event(self, kind, **values):
        return self.store.append({"kind": kind, "recorded_at_utc": self.now().isoformat(),
                                  "evidence_mode": self.mode, **values})

    def rows(self, kind=None):
        rows = self.store.records(verify_artifacts=False)
        return [r for r in rows if kind is None or r["kind"] == kind]

    def start(self, operation, context, reason=None):
        attempt = uuid4().hex
        relative = f"{context['study']}/{operation}s/{attempt}"
        record = self.event("attempt_started", attempt_id=attempt, operation=operation,
                            evidence_dir=relative, context=context, reason=reason)
        output = self.store.evidence_path(relative)
        output.mkdir(parents=True, exist_ok=False)
        return record, output

    def finish(self, start, output, kind, **values):
        if kind in ("forecast", "outcome"):
            if source_hashes() != values["source_sha256"] or pilot.sha(self.config_path) != self.config_hash:
                raise ValueError("Source/configuration changed before evidence persistence")
            pilot.verify_files(output, {"model.json": self.identity["model_sha256"],
                                        "source/operations.toml": self.config_hash,
                                        "snapshot/raw.csv": values["data"]["sha256"]})
            if json.loads((output / "snapshot/metadata.json").read_text(encoding="utf-8")) != values["data"]:
                raise ValueError("Snapshot provenance changed before evidence persistence")
        sealed = self.store.seal(start["evidence_dir"])
        if kind == "forecast":
            issued = self.now()
            if pilot.pilot_schedule(issued.to_pydatetime()).index[20].date().isoformat() != start["context"]["origin"]:
                raise ValueError("A newer session closed before forecast persistence")
            on_time = issued <= pd.Timestamp(start["context"]["issue_deadline_utc"])
            first = values.pop("first_on_time")
            values.update(issued_at_utc=issued.isoformat(), recorded_at_utc=issued.isoformat(),
                          issued_at_eastern=issued.tz_convert("America/New_York").isoformat(),
                          timing_status="local_on_time" if on_time else "late",
                          role="first_on_time_candidate" if on_time and first else
                               "revision" if values.get("revision_of") else "late_diagnostic")
        record = self.event(kind, attempt_id=start["attempt_id"], evidence_dir=start["evidence_dir"],
                          context=start["context"], reason=start.get("reason"),
                          artifact_sha256=sealed, **values)
        if kind in ("forecast", "outcome"):
            receipts = self.retain_records([record])
            return {**record, "external_retention_status": receipts[0]["status"]}
        return record

    def evidence(self, output):
        hashes = source_hashes()
        copy_source(output / "source", hashes)
        shutil.copy2(self.config_path, output / "source/operations.toml")
        shutil.copy2(self.bundle / "model.json", output / "model.json")
        return {"prepared": self.identity, "config": self.config, "config_sha256": self.config_hash,
                "source_sha256": hashes, "calendar_version": version("pandas_market_calendars"),
                "sklearn_version": version("scikit-learn"), "prospective_validity_claim": False,
                "timestamp_evidence": "Local clock/hash chain; any external timestamp receipt is a separately linked journal event"}

    def snapshot(self, output, first, last, earliest):
        settings = {"ticker": "SPY", "calendar": "NYSE", "start": first,
                    "end": (pd.Timestamp(last) + pd.Timedelta(days=1)).date().isoformat()}
        began = self.now()
        if began <= pd.Timestamp(earliest):
            raise ValueError("Acquisition cannot precede the required completed close")
        cache = self.store.root / "provider_cache"
        cache.mkdir(exist_ok=True)
        yf.set_tz_cache_location(str(cache))
        p, metadata, audit = self.acquire(settings, output / "snapshot")
        # Reload the actual archived vintage; metadata, settings, and price
        # audits must agree before calculations use it.
        archived, archived_metadata, archived_audit = get_snapshot(settings, output / "snapshot", offline=True)
        # yfinance may return second-resolution dates while CSV parsing uses
        # microseconds. Compare exact dates/prices at a common index precision;
        # do not reject an unchanged vintage for its datetime storage unit.
        pd.testing.assert_series_equal(
            p.set_axis(p.index.as_unit("ns")),
            archived.set_axis(archived.index.as_unit("ns")), check_exact=True)
        if metadata != archived_metadata or audit != archived_audit:
            raise ValueError("Acquisition result differs from archived vintage")
        if bool(metadata.get("synthetic")) != (self.mode == "synthetic_demo"):
            raise ValueError("Synthetic/live acquisition evidence must not be mixed")
        fetched = pd.Timestamp(metadata["retrieved_at_utc"])
        if fetched.tz is None or not began <= fetched <= self.now():
            raise ValueError("Invalid acquisition timestamps or reused stale vintage")
        pilot.write_json(output / "data_audit.json", audit)
        return archived, {"data": metadata, "data_config": settings, "acquisition_started_at_utc": began.isoformat(),
                          "acquired_at_eastern": fetched.tz_convert("America/New_York").isoformat()}

    def guard_notices(self, context, output):
        """Known disruptions block affected work pending an explicit amendment.

        Notices are append-only files supplied after reviewing official NYSE
        announcements. The collector never silently rewrites the frozen calendar.
        """
        relevant = set(dates(pilot.pilot_schedule(pd.Timestamp(context["scheduled_close_utc"]) + pd.Timedelta(seconds=1)).index))
        for path in sorted((self.root / "artifacts/market_notices").glob("*.json")):
            notice = json.loads(path.read_text(encoding="utf-8"))
            acquired = pd.Timestamp(notice["acquired_at_utc"])
            if acquired.tz is None or acquired > self.now() or not notice.get("official_source_url") or not notice.get("reason"):
                raise ValueError(f"Invalid official market notice: {path.name}")
            if relevant.intersection(notice["affected_sessions"]):
                shutil.copy2(path, output / ("market_notice_" + path.name))
                raise ValueError("Known market interruption/schedule change: " + notice["reason"] + "; explicit reviewed calendar amendment required")

    def fail(self, start, output, error):
        if isinstance(error, DataAuditError):
            pilot.write_json(output / "data_audit.json", error.report)
        return self.finish(start, output, "attempt_failed",
                           status="failed" if isinstance(error, (DownloadError, OSError)) else "invalid",
                           error={"type": type(error).__name__, "message": str(error)})

    def forecast(self, reason=None):
        selected = self.now()
        schedule = pilot.pilot_schedule(selected.to_pydatetime())
        origin = schedule.index[20]
        if origin < pd.Timestamp(self.config["collection"]["pilot_start"]):
            return {"status": "not_due", "reason": "Latest origin precedes configured pilot collection start"}
        try:
            context = self.context(origin)
        except ValueError as error:
            return {"status": "not_eligible", "reason": str(error)}
        earlier = [r for r in self.rows("forecast") if r["context"]["origin"] == context["origin"]]
        if earlier and not reason:
            return {"status": "already_recorded", "attempt_id": earlier[0]["attempt_id"], "context": context}
        start, output = self.start("forecast", context, reason)
        try:
            self.guard_notices(context, output)
            if context["study"] == "formal_2027" and self.mode == "live" and not self.retention.enabled:
                raise ValueError("Formal collection requires configured external retention; no 2027 issuance while retention is disabled")
            evidence = self.evidence(output)
            schedule.to_csv(output / "calendar.csv")
            prices, acquisition = self.snapshot(output, dates(schedule.index)[0], context["origin"], context["scheduled_close_utc"])
            forecast, verification, returns = pilot.calculate(prices, self.model, schedule)
            pilot.write_json(output / "verification.json", verification)
            returns.to_csv(output / "returns.csv", index_label="session")
            self.store.seal(start["evidence_dir"])
            issued = self.now()
            if pilot.pilot_schedule(issued.to_pydatetime()).index[20] != origin:
                raise ValueError("A newer session closed during acquisition; origin is now stale")
            if source_hashes() != evidence["source_sha256"] or pilot.sha(self.config_path) != self.config_hash:
                raise ValueError("Execution source/configuration changed during acquisition")
            pilot.load_prepared(self.bundle, self.config["prepared"])
            first = not any(r["timing_status"] == "local_on_time" for r in earlier)
            return self.finish(start, output, "forecast", status="valid", forecast=forecast,
                               numerical_verification_passed=True,
                               selection_time_utc=selected.isoformat(), first_on_time=first,
                               revision_of=earlier[0]["attempt_id"] if earlier else None,
                               **evidence, **acquisition)
        except Exception as error:
            return self.fail(start, output, error)

    def import_pilot(self):
        item = self.config.get("manual_pilot")
        if not item:
            return {"status": "not_configured"}
        earlier = [r for r in self.rows("pilot_import") if r["original_record_sha256"] == item["record_sha256"]]
        if earlier:
            return {"status": "already_imported", "attempt_id": earlier[0]["attempt_id"]}
        path = (self.root / item["path"]).resolve()
        if pilot.sha(path / "pilot_record.json") != item["record_sha256"]:
            raise ValueError("Original manual pilot record hash mismatch")
        checked = pilot.replay(path, bundle=self.bundle)
        original = json.loads((path / "pilot_record.json").read_text(encoding="utf-8"))
        forecast = checked["forecast"]
        context = self.context(forecast["forecast_session"])
        if context["study"] != "pilot_2026" or original["prepared"]["model_sha256"] != self.identity["model_sha256"]:
            raise ValueError("Only the designated separate 2026 manual pilot may be imported")
        start, output = self.start("import", context)
        shutil.copy2(path / "pilot_record.json", output / "original_pilot_record.json")
        return self.finish(start, output, "pilot_import", status="valid", forecast=forecast,
                           issued_at_utc=original["created_at_utc"], timing_status="separate_manual_pilot",
                           role="separate_manual_pilot", original_path=str(path),
                           original_record_sha256=item["record_sha256"], prepared=self.identity,
                           prospective_validity_claim=False)

    def forecasts(self):
        return [r for r in self.rows() if r["kind"] in ("forecast", "pilot_import")]

    def missing(self):
        existing = {(r["kind"], r.get("context", {}).get("origin")) for r in self.rows()}
        retained = {r["retained_event_hash"] for r in self.rows("retention_receipt") if r["retained_by_deadline"]}
        candidates = {r["context"]["origin"] for r in self.rows("forecast")
                      if r["timing_status"] == "local_on_time" and
                      (r["context"]["study"] != "formal_2027" or r["event_hash"] in retained)}
        now = self.now()
        added = []
        for origin in self.calendar.index:
            if origin < pd.Timestamp(self.config["collection"]["pilot_start"]) or origin > now.tz_localize(None).normalize():
                continue
            try:
                context = self.context(origin)
            except ValueError:
                continue
            if now > pd.Timestamp(context["issue_deadline_utc"]) and context["origin"] not in candidates:
                if ("forecast_missing", context["origin"]) not in existing:
                    added.append(self.event("forecast_missing", context=context, status="missing",
                                            reason="No complete qualifying on-time forecast evidence by deadline; no retrospective backfill"))
        return added

    def outcome(self, forecast_record, reason=None):
        context = forecast_record["context"]
        now = self.now()
        if now <= pd.Timestamp(context["target_close_utc"]):
            return {"status": "not_mature", "context": context}
        earlier = [r for r in self.rows("outcome") if r["context"]["origin"] == context["origin"]]
        if earlier and not reason:
            return {"status": "already_recorded", "attempt_id": earlier[0]["attempt_id"], "context": context}
        start, output = self.start("outcome", context, reason)
        try:
            self.guard_notices(context, output)
            evidence = self.evidence(output)
            sessions = pd.DatetimeIndex([context["origin"], *context["target_sessions"]])
            prices, acquisition = self.snapshot(output, context["origin"], context["target_sessions"][-1], context["target_close_utc"])
            observed_at = self.now()
            outcome = realized_volatility(prices, sessions, pd.Timestamp(context["target_close_utc"]), observed_at)
            pilot.write_json(output / "verification.json", outcome["verification"])
            fetched = pd.Timestamp(acquisition["data"]["retrieved_at_utc"])
            timely = fetched <= pd.Timestamp(context["label_deadline_utc"])
            # A revised or delayed vintage can never replace the first timely label.
            role = "first_timely_label_candidate" if timely and not earlier else "revised_sensitivity" if earlier else "late_sensitivity"
            return self.finish(start, output, "outcome", status="valid", outcome=outcome,
                               numerical_verification_passed=True,
                               role=role, observed_at_utc=observed_at.isoformat(),
                               timing_status="local_on_time" if timely else "late",
                               revision_of=earlier[0]["attempt_id"] if earlier else None,
                               forecast_attempt_id=forecast_record["attempt_id"], **evidence, **acquisition)
        except Exception as error:
            return self.fail(start, output, error)

    def outcomes(self, origin=None, reason=None):
        selected = {}
        for forecast in self.forecasts():
            date = forecast["context"]["origin"]
            if origin is None or date == origin:
                selected.setdefault(date, forecast)
        if origin and not selected:
            raise ValueError("No preserved forecast for the requested origin")
        result = []
        # Protect current 24-hour label deadlines before investigating old gaps.
        for forecast in sorted(selected.values(), key=lambda r: r["context"]["target_close_utc"], reverse=True):
            context = forecast["context"]
            rows = self.rows()
            timely = any(r["kind"] == "outcome" and r["context"]["origin"] == context["origin"]
                         and r["role"] == "first_timely_label_candidate" for r in rows)
            missed = any(r["kind"] == "outcome_missing" and r["context"]["origin"] == context["origin"] for r in rows)
            if self.now() > pd.Timestamp(context["label_deadline_utc"]) and not timely and not missed:
                result.append(self.event("outcome_missing", context=context, status="missing",
                                         reason="No complete valid archived label within 24 hours; late vintages are sensitivity only"))
            result.append(self.outcome(forecast, reason))
        return result

    def scores(self, *, pilots_only=False):
        results = []
        labels = self.rows("outcome")
        existing = {(r["forecast_attempt_id"], r["outcome_attempt_id"]) for r in self.rows("comparison")}
        for forecast in self.forecasts():
            context = forecast["context"]
            if context["study"] == "formal_2027" and (pilots_only or self.now() < SCORE_NOT_BEFORE):
                if not pilots_only:
                    results.append({"status": "embargoed", "context": context,
                                    "reason": "No formal 2027 error calculation before 2028-01-10 America/Chicago"})
                continue
            for label in labels:
                key = (forecast["attempt_id"], label["attempt_id"])
                if label["context"]["origin"] != context["origin"] or key in existing:
                    continue
                comparison = forecast_errors(forecast["forecast"], label["outcome"]["observed_volatility"], self.now())
                results.append(self.event("comparison", context=context, status="valid", comparison=comparison,
                                          forecast_attempt_id=key[0], outcome_attempt_id=key[1],
                                          outcome_role=label["role"], forecast_role=forecast["role"],
                                          formal_primary_eligibility_certified=False))
        return results

    def recover(self):
        rows = self.rows()
        finished = {r["attempt_id"] for r in rows if "attempt_id" in r and r["kind"] != "attempt_started"}
        for start in rows:
            if start["kind"] == "attempt_started" and start["attempt_id"] not in finished:
                output = self.store.evidence_path(start["evidence_dir"])
                output.mkdir(parents=True, exist_ok=True)
                self.finish(start, output, "attempt_failed", status="interrupted",
                            error={"type": "InterruptedAttempt", "message": "Previous process ended before a final journal record; partial evidence retained"})

    def retain_records(self, records=None):
        if self.mode != "live" or not self.retention.enabled:
            return [{"status": "synthetic_not_uploaded" if self.mode != "live" else "not_configured"}]
        rows = self.rows()
        retained = {r["retained_event_hash"] for r in rows if r["kind"] == "retention_receipt"}
        records = records if records is not None else [r for r in reversed(rows)
                   if r["kind"] in ("forecast", "outcome", "attempt_failed", "forecast_missing", "outcome_missing", "pilot_import")
                   and r["event_hash"] not in retained][:10]
        results = []
        for record in records:
            if record["event_hash"] in retained:
                continue
            try:
                directory = self.store.root / "retention_packages"
                directory.mkdir(exist_ok=True)
                # Keep local paths short on Windows; the remote key and
                # receipt retain the full event hash.
                path = directory / (uuid4().hex + ".zip")
                with zipfile.ZipFile(path, "x") as archive:
                    def add(name, content):
                        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, content)
                    add("record.json", json.dumps(record, sort_keys=True))
                    add("journal_prefix.json", json.dumps([r for r in rows if r["sequence"] <= record["sequence"]], sort_keys=True))
                    if record.get("artifact_sha256"):
                        base = self.store.evidence_path(record["evidence_dir"])
                        pilot.verify_files(base, record["artifact_sha256"])
                        for name in sorted(record["artifact_sha256"]):
                            add("evidence/" + name, (base / name).read_bytes())
                    for name in ("freeze_record.json", "source/prospective.toml", "source/prospective_protocol.md"):
                        add("prepared/" + name, (self.bundle / name).read_bytes())
                # Partial packages left by a crash are retained, never uploaded
                # as valid evidence. Validate every member against the journal.
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None or json.loads(archive.read("record.json")) != record:
                        raise ValueError("Incomplete or changed retention package")
                    import hashlib
                    if any(hashlib.sha256(archive.read("evidence/" + name)).hexdigest() != digest
                           for name, digest in record.get("artifact_sha256", {}).items()):
                        raise ValueError("Retention evidence hash mismatch")
                receipt = self.retention.retain(path, record["event_hash"])
                server_time = pd.Timestamp(receipt["server_last_modified_utc"])
                context = record.get("context", {})
                deadline = context.get("issue_deadline_utc" if record["kind"] == "forecast" else "label_deadline_utc")
                lower = context.get("scheduled_close_utc" if record["kind"] == "forecast" else "target_close_utc")
                results.append(self.event("retention_receipt", status="retained", retained_event_hash=record["event_hash"],
                                          archive_path=path.relative_to(self.store.root).as_posix(), receipt=receipt,
                                          retained_by_deadline=bool(deadline and lower and pd.Timestamp(lower) < server_time <= pd.Timestamp(deadline)),
                                          context=context))
            except Exception as error:
                results.append(self.event("retention_failed", status="failed", retained_event_hash=record["event_hash"],
                                          error={"type": type(error).__name__, "message": str(error)}))
        return results or [{"status": "already_retained"}]

    def metrics(self, study):
        if study == "formal_2027" and self.now() < SCORE_NOT_BEFORE:
            raise ValueError("Formal 2027 aggregate scoring is embargoed until 2028-01-10 America/Chicago")
        selected, cases, excluded = {}, [], []
        receipts = {r["retained_event_hash"]: r for r in self.rows("retention_receipt")}
        for record in self.forecasts():
            context = record["context"]
            actual = "manual_pilot_2026" if record["kind"] == "pilot_import" else context["study"]
            if actual == study:
                selected.setdefault(context["origin"], []).append(record)
        labels = self.rows("outcome")
        for origin, candidates in selected.items():
            matching = [r for r in labels if r["context"]["origin"] == origin]
            if study == "formal_2027":
                candidates = [r for r in candidates if r["timing_status"] == "local_on_time"
                              and receipts.get(r["event_hash"], {}).get("retained_by_deadline")]
                matching = [r for r in matching if r["role"] == "first_timely_label_candidate"]
                if not candidates:
                    excluded.append({"origin": origin, "reason": "No valid on-time forecast with timely external retention"})
                    continue
            record = candidates[0]
            if not matching:
                excluded.append({"origin": origin, "reason": "No eligible completed label"})
                continue
            label = matching[0]
            cases.append({"forecast": record["forecast"], "observed": label["outcome"]["observed_volatility"],
                          "forecast_id": record["attempt_id"], "outcome_id": label["attempt_id"]})
        summary = aggregate_errors(cases, study, self.now())
        return self.event("metrics", status="valid", study=study, summary=summary, excluded=excluded,
                          selected_pairs=[{k: c[k] for k in ("forecast_id", "outcome_id")} for c in cases],
                          scope="Descriptive metrics only; frozen final bootstrap/coverage analysis remains a separate evaluation")

    def verify(self):
        rows = self.store.records()
        for row in rows:
            if row["kind"] == "pilot_import":
                manual = self.config["manual_pilot"]
                path = self.root / manual["path"]
                if not (pilot.sha(path / "pilot_record.json") == row["original_record_sha256"] == manual["record_sha256"]):
                    raise ValueError("Imported manual pilot changed")
                pilot.replay(path, bundle=self.bundle)
            elif row["kind"] in ("forecast", "outcome"):
                output = self.store.evidence_path(row["evidence_dir"])
                if row["prepared"]["model_sha256"] != self.identity["model_sha256"] or pilot.sha(output / "model.json") != self.identity["model_sha256"]:
                    raise ValueError("Stored model differs from designated model")
                prices, metadata, _ = get_snapshot(row["data_config"], output / "snapshot", offline=True)
                if metadata != row["data"]:
                    raise ValueError("Stored vintage metadata differs")
                if row["kind"] == "forecast":
                    schedule = pd.read_csv(output / "calendar.csv", index_col="session", parse_dates=["session", "market_open", "market_close"])
                    result, _, _ = pilot.calculate(prices, self.model, schedule)
                    if result != row["forecast"]:
                        raise ValueError("Forecast replay mismatch")
                else:
                    c = row["context"]
                    sessions = pd.DatetimeIndex([c["origin"], *c["target_sessions"]])
                    result = realized_volatility(prices, sessions, pd.Timestamp(c["target_close_utc"]), pd.Timestamp(row["observed_at_utc"]))
                    if result != row["outcome"]:
                        raise ValueError("Outcome replay mismatch")
            elif row["kind"] == "comparison":
                f = next(r for r in rows if r.get("attempt_id") == row["forecast_attempt_id"] and r["kind"] in ("forecast", "pilot_import"))
                y = next(r for r in rows if r.get("attempt_id") == row["outcome_attempt_id"] and r["kind"] == "outcome")
                result = forecast_errors(f["forecast"], y["outcome"]["observed_volatility"], pd.Timestamp(row["recorded_at_utc"]))
                if result != row["comparison"]:
                    raise ValueError("Error replay mismatch")
            elif row["kind"] == "retention_receipt":
                if pilot.sha(self.store.evidence_path(row["archive_path"])) != row["receipt"]["archive_sha256"]:
                    raise ValueError("Retained local archive hash mismatch")
            elif row["kind"] == "metrics":
                cases = []
                for pair in row["selected_pairs"]:
                    f = next(r for r in rows if r.get("attempt_id") == pair["forecast_id"] and r["kind"] in ("forecast", "pilot_import"))
                    y = next(r for r in rows if r.get("attempt_id") == pair["outcome_id"] and r["kind"] == "outcome")
                    cases.append({"forecast": f["forecast"], "observed": y["outcome"]["observed_volatility"]})
                if aggregate_errors(cases, row["study"], pd.Timestamp(row["recorded_at_utc"])) != row["summary"]:
                    raise ValueError("Aggregate metric replay mismatch")
        return {"status": "passed", "events_checked": len(rows), "chain_head": rows[-1]["event_hash"] if rows else None,
                "evidence_mode": self.mode, "recorded_external_receipts": len(self.rows("retention_receipt")),
                "external_connection_rechecked": False}

    def execute(self, action="cycle", *, origin=None, reason=None, study=None):
        if action == "check":
            return [self.check()]
        self.store = ForecastStore(self.store_path)
        identity_checked = False
        try:
            with self.store.exclusive():
                rows = self.store.records()
                identity = {"config_sha256": self.config_hash, "evidence_mode": self.mode}
                if rows:
                    baseline_config = {k: v for k, v in rows[0].get("config", {}).items() if k != "retention"}
                    current_config = {k: v for k, v in self.config.items() if k != "retention"}
                    retention_change = (baseline_config == current_config and rows[0].get("config", {}).get("retention") != self.config.get("retention"))
                    if (rows[0]["kind"] != "store_created" or rows[0].get("evidence_mode") != self.mode
                            or (rows[0].get("config_sha256") != self.config_hash and not retention_change)):
                        raise ValueError("Store identity/config differs; preserve it and use a separate store for changes")
                    if retention_change and not any(r.get("config_sha256") == self.config_hash for r in rows):
                        self.event("retention_configuration_changed", config_sha256=self.config_hash,
                                   retention=self.config.get("retention"), reason="External storage configuration; scientific rules unchanged")
                else:
                    self.event("store_created", config_sha256=self.config_hash, config=self.config,
                               prospective_validity_claim=False)
                identity_checked = True
                if rows and self.now() < max(pd.Timestamp(r["recorded_at_utc"]) for r in rows):
                    raise ValueError("Local clock moved backwards relative to the journal")
                self.recover()
                self.check()
                if action == "verify":
                    return [self.verify()]
                if action == "status":
                    from collections import Counter
                    return [{"status": "ok", "counts": dict(Counter(r["kind"] for r in self.rows())),
                             "pending_outcomes": len({r["context"]["origin"] for r in self.forecasts()} -
                                 {r["context"]["origin"] for r in self.rows("outcome")}),
                             "retention_configured": self.retention.enabled,
                             "recorded_external_receipts": len(self.rows("retention_receipt")),
                             "prospective_validity_claim": False, "evidence_mode": self.mode}]
                if action == "import-pilot":
                    return [self.import_pilot()]
                if action == "forecast":
                    return [self.forecast(reason)]
                if action == "outcomes":
                    return [*self.outcomes(origin, reason), *self.scores(pilots_only=True)]
                if action == "score":
                    return self.scores()
                if action == "metrics":
                    return [self.metrics(study)]
                if action == "retain":
                    return self.retain_records()
                if action != "cycle":
                    raise ValueError("Unknown operation")
                try:
                    imported = self.import_pilot()
                except Exception as error:
                    imported = self.event("operation_failed", status="failed", action="import-pilot",
                                          error={"type": type(error).__name__, "message": str(error)})
                return [imported, self.forecast(), *self.missing(), *self.outcomes(), *self.scores(pilots_only=True), *self.retain_records()]
        except BusyError as error:
            return [self.event("worker_busy", status="busy", reason=str(error))]
        except Exception as error:
            # Do not append to a damaged chain, whose evidence must be preserved.
            self.store.records()
            if not identity_checked:
                raise
            return [self.event("operation_failed", status="failed", action=action,
                               error={"type": type(error).__name__, "message": str(error)})]


def public_result(row):
    keys = ("kind", "status", "attempt_id", "context", "timing_status", "role", "reason", "error",
            "forecast", "events_checked", "chain_head", "counts", "pending_outcomes", "evidence_mode",
            "external_timestamp_retention", "prepared", "scheduler_enabled_by_this_command", "prospective_validity_claim")
    result = {k: row[k] for k in keys if k in row}
    result.update({k: row[k] for k in ("external_retention_status", "summary", "excluded", "study") if k in row})
    result.update({k: row[k] for k in ("retention_configured", "recorded_external_receipts", "external_connection_rechecked",
                                      "external_retention_connection_verified", "aws_cli_available") if k in row})
    if "forecast" in row:
        result["daily_volatility_percent"] = {k: 100*v for k, v in row["forecast"]["predictions"].items()}
    if row.get("context", {}).get("study") == "pilot_2026":
        result.update({k: row[k] for k in ("outcome", "comparison") if k in row})
    elif row.get("kind") == "comparison":  # Created only after the scoring gate.
        result["comparison"] = row["comparison"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "cycle", "forecast", "outcomes", "import-pilot", "status", "verify", "score", "metrics", "retain", "demo"])
    parser.add_argument("--config", default="configs/operations.toml")
    parser.add_argument("--origin", help="Existing forecast origin, for outcome acquisition only")
    parser.add_argument("--reason", help="Explicit revision reason; preserves all previous records")
    parser.add_argument("--study", choices=["pilot_2026", "manual_pilot_2026", "formal_2027"])
    args = parser.parse_args()
    if (args.action == "metrics") != bool(args.study):
        parser.error("--study is required only for metrics")
    if args.origin and args.action != "outcomes":
        parser.error("--origin is only allowed for outcomes; forecasts cannot be backdated")
    if args.reason and (not args.reason.strip() or args.action not in ("forecast", "outcomes")):
        parser.error("A nonempty revision reason is only valid with forecast/outcomes")
    try:
        if args.action == "demo":
            from spy_volatility.workflows.operations_demo import demonstrate
            print(json.dumps(demonstrate(args.config), indent=2))
            return 0
        results = Operations(args.config).execute(args.action, origin=args.origin, reason=args.reason, study=args.study)
        print(json.dumps([public_result(row) for row in results], indent=2))
        return 1 if any(r.get("status") in ("failed", "invalid", "busy", "interrupted", "embargoed") or
                       r.get("external_retention_status") == "failed" for r in results) else 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
