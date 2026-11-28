from pathlib import Path

import pytest

from spy_volatility.workflows import pilot_service as service


@pytest.mark.parametrize("failure", [None, "collect", "checkpoint", "replay", "writer", "diverged"])
def test_publication_requires_private_checkpoint_and_replay(tmp_path, monkeypatch, failure):
    (tmp_path / ".git").mkdir()
    (tmp_path / "artifacts").mkdir()
    order = []
    def command(*args):
        if "get-url" in args:
            return service.PRIVATE
        if "--show-current" in args:
            return "main"
        if "variable" in args:
            return "github" if failure == "writer" else "windows"
        if "rev-list" in args:
            return "1 1" if failure == "diverged" else "0 1"
        if "merge" in args:
            order.append("fast_forward")
        if "push" in args:
            order.append("checkpoint")
            if failure == "checkpoint" and "collect" in order:
                raise OSError("private checkpoint unavailable")
        if "workflow" in args:
            order.append("dispatch")
        if "rev-parse" in args:
            return "private-head"
        return ""
    def collect(root):
        order.append("collect")
        if failure == "collect":
            raise OSError("failed collector")
        return {"status": "no_forecast"}
    def verify(root):
        order.append("replay")
        if failure == "replay":
            raise ValueError("bad replay")
        return {"status": "passed"}
    monkeypatch.setattr(service.hosted_pilot, "collect", collect)
    monkeypatch.setattr(service.hosted_pilot, "verify", verify)
    monkeypatch.setattr(service.hosted_pilot, "release", lambda *a, **kw: True)
    if failure:
        with pytest.raises((OSError, ValueError)):
            service.run(tmp_path, tmp_path, "gh", command)
        assert "dispatch" not in order
        if failure == "collect":
            assert order[-1] == "checkpoint"
    else:
        result = service.run(tmp_path, tmp_path, "gh", command)
        assert order == ["fast_forward", "checkpoint", "collect", "checkpoint", "replay", "dispatch"]
        assert result["checkpoint"] == "private-head"


def test_publication_lock_excludes_overlapping_invocations(tmp_path):
    lock = tmp_path / "worker.lock"
    with service.exclusive(lock):
        with pytest.raises(OSError):
            with service.exclusive(lock):
                pytest.fail("overlapping worker acquired lock")
    with service.exclusive(lock):
        assert lock.is_file()
