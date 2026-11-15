"""Configuration, attested capacity and trusted public archive providers."""
import asyncio

import pytest

from backend.app.core.config import Settings, validate_env_file
from backend.app.repo_learning.ingest import ImportFailure
from backend.app.repo_learning.network import ARCHIVE_HOSTS, public_archive_url
from backend.app.speech.gatekeeper import SpeechGatekeeper


def test_requested_gnani_upgrade_does_not_invent_entitlement():
    settings = Settings(_env_file=None, gnani_max_concurrency=4)
    assert settings.gnani_effective_concurrency == 1
    assert Settings(_env_file=None,gnani_max_concurrency=4,gnani_verified_concurrency=2).gnani_effective_concurrency == 2


def test_empty_database_secret_keeps_preview_on_sqlite(monkeypatch):
    monkeypatch.setenv('VCC_DATABASE_URL','')
    settings=Settings(_env_file=None)
    assert settings.database_url is None and settings.database_target==settings.database_path


def test_selected_file_does_not_inherit_ambient_database_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv('VCC_DATABASE_URL','postgresql://user:ambient-secret@localhost/viva')
    selected=tmp_path/'private.env'; selected.write_text('VCC_ENV=development\n')
    assert Settings(_env_file=selected).database_url is None


def test_invalid_database_protocol_is_secret_redacted():
    with pytest.raises(ValueError) as caught:
        Settings(_env_file=None,database_url='mysql://user:private-database-secret@localhost/viva')
    assert 'private-database-secret' not in str(caught.value)


def test_gatekeeper_upgraded_slots_require_verified_cap():
    async def run():
        gate = SpeechGatekeeper(object(),max_concurrency=3,verified_concurrency=2)
        try:
            await asyncio.gather(gate._acquire_single_slot(),gate._acquire_single_slot())
            assert gate.get_capacity_status().active_requests == 2
            waiting = asyncio.create_task(gate._acquire_single_slot())
            await asyncio.sleep(0)
            assert not waiting.done()
            gate._release_single_slot()
            await waiting
            assert gate.get_capacity_status().active_requests == 2
            gate._release_single_slot(); gate._release_single_slot()
        finally: gate._conn.close()
        gate = SpeechGatekeeper(object(),max_concurrency=3)
        assert gate.max_concurrency == 1
        gate._conn.close()
    asyncio.run(run())


@pytest.mark.parametrize('cap',[0,33,True,1.5])
def test_invalid_capacity_rejected(cap):
    with pytest.raises(ValueError): SpeechGatekeeper(object(),max_concurrency=cap)


def test_explicit_file_validation_rejects_mutable_and_symlink_files(tmp_path):
    path=tmp_path/'private.env'; path.write_text('VCC_GROQ_API_KEY=do-not-disclose\n'); path.chmod(0o600)
    assert validate_env_file(path) == path
    path.chmod(0o666)
    with pytest.raises(ValueError,match='not writable'): validate_env_file(path)
    path.chmod(0o600); alias=tmp_path/'alias.env'; alias.symlink_to(path)
    with pytest.raises(ValueError,match='non-symlink'): validate_env_file(alias)
    with pytest.raises(ValueError,match='absolute'): validate_env_file('private.env')


@pytest.mark.parametrize('url,expected',[
    ('https://github.com/owner/repo.git','https://codeload.github.com/owner/repo/zip/HEAD'),
    ('https://gitlab.com/group/subgroup/repo','https://gitlab.com/group/subgroup/repo/-/archive/HEAD/repo-HEAD.zip'),
])
def test_registry_resolves_reviewed_archive_patterns(url,expected):
    assert public_archive_url(url) == expected
    assert ARCHIVE_HOSTS == {'codeload.github.com','gitlab.com'}


@pytest.mark.parametrize('url',[
    'https://github.com:443/a/b','https://a:password@github.com/a/b','https://github.com/a/%2e%2e',
    'https://github.com/a/b#fragment','https://gitlab.com/a/b?token=secret','https://github.com/a/b/c',
    'http://github.com/a/b','https://127.0.0.1/a/b','https://github.com./a/b',
    'https://gıthub.com/a/b','https://bitbucket.org/a/b','https://github.com/a/..',
    'https://github.com/a/b\\evil','https://github.com/a/..git',
    'https://git\nhub.com/a/b','https://github.com/a/b#','https://github.com/a/b?',
])
def test_unknown_or_unsafe_repository_locator_offers_zip_fallback(url):
    with pytest.raises(ImportFailure,match='ZIP'): public_archive_url(url)
