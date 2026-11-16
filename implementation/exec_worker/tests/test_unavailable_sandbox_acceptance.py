"""Current runtime must refuse sandbox acceptance before any cloud access."""
import pytest

from exec_worker.vercel_sandbox import live_acceptance


def test_cli_fails_closed_before_transport_or_database(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(sys, 'argv', ['live_acceptance', '--output', str(tmp_path / 'evidence.json'), '--confirmed-free-hobby'])
    monkeypatch.setattr(live_acceptance, 'VercelSandboxTransport', lambda *a, **k: pytest.fail('transport must not be created'))
    with pytest.raises(SystemExit, match='Sandbox acceptance is unavailable'):
        live_acceptance.main()
    assert not (tmp_path / 'evidence.json').exists()
