"""Source provenance must describe executing code, not a nearby config tree."""

import hashlib
from pathlib import Path
import pytest

import spy_volatility.infrastructure.provenance as provenance
import spy_volatility.core.research as research


def test_source_hashes_identify_executing_package_from_an_external_directory(tmp_path, monkeypatch):
    unrelated_source = tmp_path / "src" / "spy_volatility"
    unrelated_source.mkdir(parents=True)
    unrelated_source.joinpath("research.py").write_text("# Unrelated code\n", encoding="utf-8")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_dir.joinpath("phase1.toml").write_text("# External configuration\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    hashes = provenance.source_hashes()

    assert "spy_volatility/workflows/baseline.py" in hashes
    assert hashes["spy_volatility/core/research.py"] == hashlib.sha256(
        Path(research.__file__).read_bytes()
    ).hexdigest()
    assert hashes["spy_volatility/infrastructure/provenance.py"] == hashlib.sha256(
        Path(provenance.__file__).read_bytes()
    ).hexdigest()
    assert hashes["spy_volatility/core/research.py"] != hashlib.sha256(
        unrelated_source.joinpath("research.py").read_bytes()
    ).hexdigest()
    assert all(name.startswith("spy_volatility/") and "\\" not in name for name in hashes)


def test_source_snapshot_preserves_complete_nested_package(tmp_path):
    hashes = provenance.source_hashes()
    destination = tmp_path / "source"
    provenance.copy_source(destination, hashes)
    copied = {f"spy_volatility/{p.relative_to(destination).as_posix()}":
              hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob("*.py")}
    assert copied == hashes
    assert (destination / "core/research.py").is_file()
    assert (destination / "workflows/temporal.py").is_file()
    assert (destination / "verification/temporal.py").is_file()
    assert (destination / "infrastructure/provenance.py").is_file()


def test_source_snapshot_rejects_changed_or_incomplete_manifest(tmp_path):
    hashes = provenance.source_hashes()
    hashes.pop("spy_volatility/core/research.py")
    with pytest.raises(ValueError, match="source changed"):
        provenance.copy_source(tmp_path / "source", hashes)
    assert not (tmp_path / "source").exists()
