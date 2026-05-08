from datetime import datetime
from pathlib import Path


def run_dir_name(started_at: datetime) -> str:
    """ISO 8601 UTC, no microseconds, Windows-safe (`:` -> `-`)."""
    iso = started_at.replace(microsecond=0).isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso.replace(":", "-")


def prepare_run_dir(repo_root: Path, started_at: datetime, override: Path | None) -> Path:
    """Resolve, create, and return the run directory."""
    if override is not None:
        run_dir = override
    else:
        run_dir = repo_root / ".ai-review" / "runs" / run_dir_name(started_at)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_latest_pointer(runs_dir: Path, run_dir: Path) -> None:
    """Write `runs_dir/latest.txt` with the run dir's basename."""
    pointer = runs_dir / "latest.txt"
    pointer.write_text(run_dir.name + "\n", encoding="utf-8")
