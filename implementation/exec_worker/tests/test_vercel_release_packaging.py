"""Build disposable repositories; never upload or access cloud credentials."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/build_vercel_release.py'
spec = importlib.util.spec_from_file_location('release_builder', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source, text=True).strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    templates = root / 'implementation/deployment/vercel/templates'
    templates.mkdir(parents=True)
    (templates/'config').mkdir()
    (templates/'config/supabase-prod-ca-2021.crt').write_text('public certificate fixture')
    (templates/'api').mkdir()
    (templates/'api/index.py').write_text('app = object()')
    for path,content in {
        'implementation/frontend/dist/index.html': '<html>synthetic</html>',
        'implementation/frontend/dist/assets/app.js': 'console.log("public")',
        'implementation/frontend/src/App.tsx': 'export const App = 1',
        'implementation/backend/app/main.py': 'app = object()',
        'implementation/backend/app/db/postgres/runtime_migrations/0100_schema.sql': 'SELECT 1;',
        'implementation/exec_worker/vercel_sandbox/native/guard.c': 'int guard(void) {return 1;}',
        'implementation/exec_worker/tests/test_private.py': 'DO_NOT_UPLOAD = 1',
        'implementation/config/branding.json': '{}',
        'implementation/config/local-development.json': json.dumps({'backend_host': '127.0.0.1', 'backend_port': 8020, 'frontend_port': 5173, 'cors_hosts': ['localhost', '127.0.0.1']}),
    }.items():
        p=root/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content)
    git(root,'init','-q')
    git(root,'add','.')
    git(root,'-c','user.name=Packaging Test','-c','user.email=packaging@example.invalid','commit','-qm','synthetic source')
    return root


def test_reproducible_inventory_ca_and_native_source_completeness(source,tmp_path):
    out=tmp_path/'artifact'
    builder.build(source,out)
    identity=json.loads((tmp_path/'artifact.manifest.json').read_text())
    assert identity['exact_commit'] is True and identity['git_dirty'] is False
    assert (out/'config/supabase-prod-ca-2021.crt').is_file()
    assert (out/'exec_worker/vercel_sandbox/native/guard.c').is_file()
    assert (out/'backend/app/db/postgres/runtime_migrations/0100_schema.sql').is_file()
    assert not (out/'exec_worker/tests').exists()
    assert identity['frontend_sources']['src/App.tsx']
    assert all(hashlib.sha256((out/path).read_bytes()).hexdigest()==digest for path,digest in identity['files'].items())
    builder.build(source,tmp_path/'second')
    assert (tmp_path/'artifact.manifest.json').read_bytes()==(tmp_path/'second.manifest.json').read_bytes()


def test_dirty_candidate_cannot_masquerade_as_exact_commit(source,tmp_path):
    (source/'implementation/backend/app/main.py').write_text('uncommitted = True')
    with pytest.raises(ValueError,match='Commit the exact'):
        builder.build(source,tmp_path/'denied')
    builder.build(source,tmp_path/'preview',allow_dirty=True)
    identity=json.loads((tmp_path/'preview.manifest.json').read_text())
    assert identity['git_dirty'] is True and identity['exact_commit'] is False


@pytest.mark.parametrize('relative', ['implementation/frontend/dist/.env', 'implementation/frontend/dist/app.js.map', 'implementation/deployment/vercel/templates/.env'])
def test_private_or_unexpected_upload_inputs_fail_closed(source,tmp_path,relative):
    p=source/relative; p.write_text('synthetic-private-content')
    with pytest.raises(ValueError,match='Unexpected'):
        builder.build(source,tmp_path/'artifact',allow_dirty=True)
    assert not (tmp_path/'artifact').exists()


def test_symlinked_source_root_and_leaf_are_rejected(source,tmp_path):
    runtime=source/'implementation/backend/app'
    outside=tmp_path/'external';shutil.move(runtime,outside)
    runtime.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='Symbolic'):
        builder.build(source,tmp_path/'root-link',allow_dirty=True)
    runtime.unlink();shutil.move(outside,runtime)
    leaf=runtime/'leak.py';leaf.symlink_to(runtime/'main.py')
    with pytest.raises(ValueError,match='Symbolic'):
        builder.build(source,tmp_path/'leaf-link',allow_dirty=True)


def test_existing_manifest_or_source_nested_output_is_refused(source,tmp_path):
    (tmp_path/'artifact.manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='immutable'):
        builder.build(source,tmp_path/'artifact')
    with pytest.raises(ValueError,match='outside'):
        builder.build(source,source/'release')


def test_checked_in_templates_are_accepted(source, tmp_path):
    templates = source / 'implementation/deployment/vercel/templates'
    shutil.copytree(SCRIPT.parents[1] / 'deployment/vercel/templates', templates, dirs_exist_ok=True)
    builder.build(source, tmp_path / 'artifact', allow_dirty=True)
    assert (tmp_path / 'artifact/.vercelignore').is_file()
    assert (tmp_path / 'artifact/.python-version').read_text().strip() == '3.12'
    config = json.loads((tmp_path / 'artifact/vercel.json').read_text())
    # Vercel rejects longer includeFiles expressions before starting a build.
    assert len(config['functions']['api/index.py']['includeFiles']) <= 256


@pytest.mark.parametrize('relative', [
    'implementation/frontend/dist/credentials.json',
    'implementation/frontend/dist/assets/secrets.json',
    'implementation/frontend/dist/passwords.txt',
    'implementation/frontend/dist/assets/credentials.txt',
    'implementation/backend/app/credentials.json',
    'implementation/deployment/vercel/templates/credentials.json',
])
def test_extension_allowlist_does_not_admit_private_files(source, tmp_path, relative):
    path = source / relative
    path.write_text('{"secret": "synthetic"}')
    with pytest.raises(ValueError, match='Unexpected'):
        builder.build(source, tmp_path / 'artifact', allow_dirty=True)


@pytest.mark.parametrize('relative', [
    'implementation/frontend/dist',
    'implementation/deployment/vercel/templates',
    'implementation/backend',
])
def test_symlinked_input_ancestors_are_rejected(source, tmp_path, relative):
    root = source / relative
    external = tmp_path / 'external'
    shutil.move(root, external)
    root.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='regular|Symbolic'):
        builder.build(source, tmp_path / 'artifact', allow_dirty=True)


def test_symlinked_checkout_is_rejected(source, tmp_path):
    link = tmp_path / 'linked-checkout'
    link.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match='Symbolic source'):
        builder.build(link, tmp_path / 'artifact')


def test_ignored_runtime_inputs_cannot_claim_exact_commit(source, tmp_path):
    (source / '.git/info/exclude').write_text('ignored.py\n')
    (source / 'implementation/backend/app/ignored.py').write_text('ignored = True')
    assert not git(source, 'status', '--porcelain', '--untracked-files=all')
    with pytest.raises(ValueError, match='ignored release inputs'):
        builder.build(source, tmp_path / 'denied')
    builder.build(source, tmp_path / 'artifact', allow_dirty=True)
    identity = json.loads((tmp_path / 'artifact.manifest.json').read_text())
    assert identity['exact_commit'] is False
    assert 'implementation/backend/app/ignored.py' in identity['untracked_release_inputs']


def test_packaged_config_loader_reads_bundled_defaults(source, tmp_path):
    import sys
    loader = source / 'implementation/backend/app/core/local_config.py'
    loader.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT.parents[1] / 'backend/app/core/local_config.py', loader)
    out = tmp_path / 'artifact'
    builder.build(source, out, allow_dirty=True)
    result = subprocess.run([sys.executable, '-I', '-c',
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from backend.app.core.local_config import local_development; "
        "assert local_development().cors_origins == 'http://localhost:5173,http://127.0.0.1:5173'",
        str(out)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_missing_local_defaults_are_rejected(source, tmp_path):
    (source / 'implementation/config/local-development.json').unlink()
    with pytest.raises(ValueError, match='regular release inputs'):
        builder.build(source, tmp_path / 'artifact', allow_dirty=True)


@pytest.mark.parametrize('change', [{'api_key': 'synthetic-secret'}, {'backend_host': 'external.invalid'}, {'backend_port': True}])
def test_local_defaults_cannot_smuggle_credentials_or_external_hosts(source, tmp_path, change):
    path = source / 'implementation/config/local-development.json'
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))
    with pytest.raises(ValueError, match='validated loopback defaults'):
        builder.build(source, tmp_path / 'artifact', allow_dirty=True)
