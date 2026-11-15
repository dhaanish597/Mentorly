"""Explicit CA configuration preserves verified TLS and is independent of cwd."""
from pathlib import Path

import pytest

from backend.app.core import config


def test_bundled_database_certificate_resolves_relative_to_application(tmp_path, monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    monkeypatch.chdir(tmp_path)
    settings = config.Settings(database_url='host=db.example.com user=postgres password=private-test dbname=postgres sslmode=verify-full',
        database_sslrootcert=Path('config/supabase-prod-ca-2021.crt'))
    options = psycopg.conninfo.conninfo_to_dict(settings.database_target.dsn)
    assert options['sslrootcert'] == str(config._REPO_ROOT / 'config/supabase-prod-ca-2021.crt')
    assert options['sslmode'] == 'verify-full'
    assert 'private-test' not in repr(settings.database_target)


def test_custom_certificate_never_allows_unverified_remote_tls():
    pytest.importorskip('psycopg')
    settings = config.Settings(database_url='host=db.example.com user=postgres password=private-test dbname=postgres sslmode=require',
        database_sslrootcert=Path('/trusted/test-ca.crt'))
    with pytest.raises(ValueError, match='verified TLS'):
        _ = settings.database_target
