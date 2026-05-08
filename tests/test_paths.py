from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pr_reviewer.paths import run_dir_name, prepare_run_dir, write_latest_pointer


class TestRunDirName:
    def test_iso_with_colons_replaced_by_dashes(self):
        ts = datetime(2026, 5, 7, 14, 32, 19, tzinfo=timezone.utc)
        assert run_dir_name(ts) == "2026-05-07T14-32-19Z"

    def test_strips_microseconds(self):
        ts = datetime(2026, 5, 7, 14, 32, 19, 123456, tzinfo=timezone.utc)
        assert run_dir_name(ts) == "2026-05-07T14-32-19Z"

    def test_naive_datetime_rejected(self):
        ts = datetime(2026, 5, 7, 14, 32, 19)
        with pytest.raises(ValueError, match="UTC-aware"):
            run_dir_name(ts)

    def test_non_utc_offset_rejected(self):
        ts = datetime(2026, 5, 7, 14, 32, 19, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        with pytest.raises(ValueError, match="UTC"):
            run_dir_name(ts)


class TestPrepareRunDir:
    def test_creates_default_path_under_ai_review_runs(self, tmp_path: Path):
        ts = datetime(2026, 5, 7, 14, 32, 19, tzinfo=timezone.utc)
        run_dir = prepare_run_dir(repo_root=tmp_path, started_at=ts, override=None)
        assert run_dir == tmp_path / ".ai-review" / "runs" / "2026-05-07T14-32-19Z"
        assert run_dir.is_dir()

    def test_uses_override_when_set(self, tmp_path: Path):
        out = tmp_path / "custom-out"
        run_dir = prepare_run_dir(repo_root=tmp_path, started_at=datetime.now(timezone.utc), override=out)
        assert run_dir == out
        assert run_dir.is_dir()


class TestLatestPointer:
    def test_writes_run_dir_basename(self, tmp_path: Path):
        runs_dir = tmp_path / ".ai-review" / "runs"
        runs_dir.mkdir(parents=True)
        run_dir = runs_dir / "2026-05-07T14-32-19Z"
        run_dir.mkdir()

        write_latest_pointer(runs_dir, run_dir)

        pointer = runs_dir / "latest.txt"
        assert pointer.read_text(encoding="utf-8").strip() == "2026-05-07T14-32-19Z"
