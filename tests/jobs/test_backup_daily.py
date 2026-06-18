import json
from datetime import date, timedelta
from pathlib import Path

from src.jobs.backup_daily import run_backup


def test_backup_creates_manifest(tmp_path):
    db = tmp_path / "base_live.db"
    db.write_bytes(b"sqlite")
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "a.mp4").write_bytes(b"vid")

    out = run_backup(
        db_path=str(db),
        clips_dir=str(clips),
        backup_root=str(tmp_path / "backups"),
        retain_days=7,
    )

    backup_dir = Path(out)
    assert backup_dir.exists()
    assert (backup_dir / "base_live.db").read_bytes() == b"sqlite"
    assert (backup_dir / "clips" / "a.mp4").read_bytes() == b"vid"

    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["db_size"] == len(b"sqlite")
    assert manifest["clip_count"] == 1
    assert "timestamp" in manifest


def test_backup_retention_prunes_old(tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    old_date = (date.today() - timedelta(days=3)).isoformat()
    recent_date = (date.today() - timedelta(days=1)).isoformat()

    old_dir = backup_root / old_date
    old_dir.mkdir()
    (old_dir / "manifest.json").write_text("{}", encoding="utf-8")

    recent_dir = backup_root / recent_date
    recent_dir.mkdir()
    (recent_dir / "manifest.json").write_text("{}", encoding="utf-8")

    db = tmp_path / "base_live.db"
    db.write_bytes(b"sqlite")
    clips = tmp_path / "clips"
    clips.mkdir()

    run_backup(
        db_path=str(db),
        clips_dir=str(clips),
        backup_root=str(backup_root),
        retain_days=1,
    )

    assert not old_dir.exists()
    assert recent_dir.exists()
