"""Daily backup job — snapshot SQLite DB and clips directory."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path


def run_backup(
    db_path: str = "base_live.db",
    clips_dir: str = "output/clips",
    backup_root: str = "backups",
    retain_days: int = 7,
) -> str:
    """Create a dated backup with DB copy, clips copy, and manifest.

    Returns the path to the created backup directory.
    """
    today = date.today().isoformat()
    backup_dir = Path(backup_root) / today
    backup_dir.mkdir(parents=True, exist_ok=True)

    db_src = Path(db_path)
    if db_src.exists():
        shutil.copy2(db_src, backup_dir / db_src.name)

    clips_src = Path(clips_dir)
    clips_dest = backup_dir / clips_src.name
    clip_count = 0
    if clips_src.exists():
        shutil.copytree(clips_src, clips_dest, dirs_exist_ok=True)
        clip_count = sum(1 for p in clips_dest.rglob("*") if p.is_file())

    db_size = (backup_dir / db_src.name).stat().st_size if db_src.exists() else 0
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "db_size": db_size,
        "clip_count": clip_count,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    _prune_old_backups(Path(backup_root), retain_days)
    return str(backup_dir)


def _prune_old_backups(backup_root: Path, retain_days: int) -> None:
    if retain_days < 1 or not backup_root.exists():
        return

    cutoff = date.today() - timedelta(days=retain_days)
    for entry in backup_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            backup_date = date.fromisoformat(entry.name)
        except ValueError:
            continue
        if backup_date < cutoff:
            shutil.rmtree(entry)


def main() -> None:
    out = run_backup()
    print(f"backup_created={out}")


if __name__ == "__main__":
    main()
