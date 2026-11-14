"""Pre-upgrade online backup preserves a populated legacy installation."""
from pathlib import Path
import shutil
import sqlite3

import pytest

from backend.app.db.migrations import MigrationError, apply_migrations


def migration_set(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    source = Path(__file__).parents[2] / "app/db/migrations"
    for path in source.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 6:
            shutil.copyfile(path, directory / path.name)
    return directory


@pytest.mark.parametrize("broken", [False, True])
def test_online_backup_retains_pre_upgrade_rows_and_migrations(tmp_path, broken):
    migrations = migration_set(tmp_path)
    database = tmp_path / "existing.sqlite3"
    apply_migrations(database, migrations)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE private_sentinel(value TEXT)")
        conn.execute("INSERT INTO private_sentinel VALUES ('retained historical record')")
    sql = "INVALID SQL;" if broken else "CREATE TABLE studio_probe(id TEXT);"
    (migrations / "0007_studio_probe.sql").write_text(sql)
    if broken:
        with pytest.raises(MigrationError):
            apply_migrations(database, migrations)
    else:
        assert apply_migrations(database, migrations) == ["0007"]
    backups = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT value FROM private_sentinel").fetchone()[0] == "retained historical record"
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == "0006"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='studio_probe'").fetchone() is None
    if not broken:
        assert apply_migrations(database, migrations) == []
        assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_turn_revision_upgrade_preserves_old_turns_and_backup(tmp_path):
    source = Path(__file__).parents[2] / 'app/db/migrations'
    migrations = migration_set(tmp_path)
    for path in source.glob('*.sql'):
        if 7 <= int(path.name.split('_', 1)[0]) <= 10:
            shutil.copyfile(path, migrations / path.name)
    database = tmp_path / 'populated.sqlite3'
    apply_migrations(database, migrations)
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO studio_workspaces VALUES('workspace','hash','2026-11-14T00:00:00+00:00','2027-11-14T00:00:00+00:00',NULL)")
        conn.execute("INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at) VALUES('session','workspace','hash','dsa_to_system_bridge','teaching','SD-BR-01','1.0.0','2026-11-14T00:00:00+00:00','2027-11-14T00:00:00+00:00')")
        conn.execute("INSERT INTO studio_turns VALUES('turn','session',1,0,'answer','original','2026-11-14T00:00:00+00:00')")
    shutil.copyfile(source / '0011_studio_turn_revisions.sql', migrations / '0011_studio_turn_revisions.sql')
    assert apply_migrations(database, migrations) == ['0011']
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT content,transcript_revision,superseded_by FROM studio_turns').fetchone() == ('original',1,None)
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    backups = list((tmp_path / 'backups').glob('*.sqlite3'))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute('SELECT content FROM studio_turns').fetchone()[0] == 'original'
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == '0010'
    assert apply_migrations(database, migrations) == []
    with (migrations / '0011_studio_turn_revisions.sql').open('a') as file:
        file.write('\n-- checksum drift\n')
    with pytest.raises(MigrationError, match='Checksum mismatch'):
        apply_migrations(database, migrations)


def test_fresh_database_has_no_historical_backup(tmp_path):
    migrations = migration_set(tmp_path)
    (migrations / "0007_studio_probe.sql").write_text("CREATE TABLE studio_probe(id TEXT);")
    apply_migrations(tmp_path / "fresh.sqlite3", migrations)
    assert not (tmp_path / "backups").exists()
