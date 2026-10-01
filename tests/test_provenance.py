"""Source provenance must describe executing code, not a nearby config tree."""

import hashlib
from pathlib import Path

from spy_volatility import provenance, research


def test_source_hashes_identify_executing_package_from_an_external_directory(tmp_path, monkeypatch):
    unrelated_source = tmp_path / "src" / "spy_volatility"
    unrelated_source.mkdir(parents=True)
    unrelated_source.joinpath("research.py").write_text("# Unrelated code\n", encoding="utf-8")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_dir.joinpath("phase1.toml").write_text("# External configuration\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    hashes = provenance.source_hashes()

    assert "spy_volatility/pipeline.py" in hashes
    assert hashes["spy_volatility/research.py"] == hashlib.sha256(
        Path(research.__file__).read_bytes()
    ).hexdigest()
    assert hashes["spy_volatility/provenance.py"] == hashlib.sha256(
        Path(provenance.__file__).read_bytes()
    ).hexdigest()
    assert hashes["spy_volatility/research.py"] != hashlib.sha256(
        unrelated_source.joinpath("research.py").read_bytes()
    ).hexdigest()
    assert all(name.startswith("spy_volatility/") and "\\" not in name for name in hashes)
