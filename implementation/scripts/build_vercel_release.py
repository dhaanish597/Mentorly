"""Build an allowlisted Vercel upload and reproducible SHA256 inventory.

Run frontend clean install/test/build first. Dirty trees require --allow-dirty and
are explicitly marked unsuitable for exact-commit production promotion.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

PUBLIC_EXTENSIONS = {'.html', '.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.webmanifest', '.txt'}
TEMPLATE_FILES = {'vercel.json', 'requirements.txt', 'pyproject.toml', 'deployment_spa.py', '.python-version', 'api/index.py', '.vercelignore', 'config/supabase-prod-ca-2021.crt'}
EXCLUDED = {'tests', '__pycache__', 'node_modules', 'data', '.git', '.env', '.vercel'}


def _git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source, text=True).strip()


def _regular(source, path):
    relative = path.relative_to(source)
    if any((source / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)) or not path.is_file():
        raise ValueError('Only regular release inputs without symbolic links are accepted.')


def build(source: Path, destination: Path, *, allow_dirty=False):
    source = source.absolute()
    for ancestor in (source, *source.parents):
        if ancestor.is_symlink():
            raise ValueError('Symbolic source ancestors are forbidden.')
    source = source.resolve(strict=True)
    destination = destination.absolute()
    manifest_path = destination.with_name(destination.name + '.manifest.json')
    if destination.exists() or manifest_path.exists():
        raise ValueError('Use a new output directory; existing artifacts are immutable.')
    if destination.resolve().is_relative_to(source):
        raise ValueError('Release output must be outside the source checkout.')
    commit = _git(source, 'rev-parse', 'HEAD')
    status = _git(source, 'status', '--porcelain', '--untracked-files=all')
    if status and not allow_dirty:
        raise ValueError('Commit the exact verified candidate first, or explicitly use --allow-dirty for a non-production artifact.')
    templates = source / 'implementation/deployment/vercel/templates'
    frontend = source / 'implementation/frontend/dist'
    if not (frontend / 'index.html').is_file():
        raise ValueError('A verified frontend production build is required.')
    inputs = {}
    def include(path, relative):
        _regular(source, path)
        relative = str(relative)
        if relative in inputs:
            raise ValueError('Release input path collision.')
        inputs[relative] = path
    _regular(source, templates / 'api/index.py')
    _regular(source, frontend / 'index.html')
    for p in sorted(templates.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symbolic links are forbidden in release templates.')
        if p.is_file():
            rel = p.relative_to(templates)
            if rel.as_posix() not in TEMPLATE_FILES:
                raise ValueError('Unexpected release template input.')
            include(p, rel)
    if not (templates / 'config/supabase-prod-ca-2021.crt').is_file():
        raise ValueError('Verified public database CA is required in release templates.')
    for directory, prefix in [('implementation/backend/app', 'backend/app'), ('implementation/exec_worker', 'exec_worker')]:
        root = source / directory
        if root.is_symlink():
            raise ValueError('Symbolic runtime source roots are forbidden.')
        for p in sorted(root.rglob('*')):
            rel = p.relative_to(root)
            if any(part in EXCLUDED for part in rel.parts):
                continue
            if p.is_symlink():
                raise ValueError('Symbolic runtime inputs are forbidden.')
            json_allowed = (prefix == 'backend/app' and (
                rel == Path('exercises/case_manifest.json') or
                rel.parent == Path('studio/scenarios/catalog') or
                rel.parent == Path('repo_learning/golden')
            )) or (prefix == 'exec_worker' and rel in {
                Path('vercel_sandbox/package.json'), Path('vercel_sandbox/package-lock.json'),
                Path('vercel_sandbox/accepted-runtime.json'),
            })
            allowed = p.suffix in {'.py', '.sql'} or (p.suffix == '.json' and json_allowed) or (
                prefix == 'exec_worker' and rel.parent == Path('vercel_sandbox/native') and p.suffix in {'.c', '.h'}
            )
            if p.suffix == '.json' and not json_allowed and p.name not in {'native-capability-probe.json', 'supported-reference-probe.json'}:
                raise ValueError('Unexpected runtime JSON input.')
            if not allowed or not p.is_file():
                continue
            if any(part.startswith('.') for part in rel.parts):
                raise ValueError('Hidden runtime inputs are forbidden.')
            if p.name in {'native-capability-probe.json', 'supported-reference-probe.json'}:
                continue
            include(p, Path(prefix) / rel)
    include(source / 'implementation/config/branding.json', 'config/branding.json')
    local_config = source / 'implementation/config/local-development.json'
    _regular(source, local_config)
    local_values = json.loads(local_config.read_text())
    if (not isinstance(local_values, dict) or
            set(local_values) != {'backend_host', 'backend_port', 'frontend_port', 'cors_hosts'} or
            local_values['backend_host'] not in {'localhost', '127.0.0.1'} or
            local_values['cors_hosts'] not in [['localhost', '127.0.0.1'], ['127.0.0.1', 'localhost']] or
            any(type(local_values[key]) is not int or not 1024 <= local_values[key] <= 65535
                for key in ('backend_port', 'frontend_port'))):
        raise ValueError('Local development release config must contain only validated loopback defaults.')
    include(local_config, 'config/local-development.json')
    for p in sorted(frontend.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symbolic frontend inputs are forbidden.')
        if p.is_file():
            rel = p.relative_to(frontend)
            allowed_location = rel == Path('index.html') or (len(rel.parts) > 1 and rel.parts[0] in {'assets', 'mentor', 'fonts'}) or rel.name in {'favicon.ico', 'favicon.svg', 'robots.txt', 'manifest.webmanifest'}
            if p.suffix.lower() == '.txt' and not (rel == Path('robots.txt') or (rel.parent == Path('fonts') and p.name.endswith('-OFL.txt'))):
                allowed_location = False
            if not allowed_location or any(part.startswith('.') or part in EXCLUDED for part in rel.parts) or p.suffix.lower() not in PUBLIC_EXTENSIONS:
                raise ValueError('Unexpected public build input; remove private files and source maps.')
            include(p, Path('public') / rel)
    include(frontend / 'index.html', 'frontend-index.html')
    manifest = {name: hashlib.sha256(p.read_bytes()).hexdigest() for name,p in sorted(inputs.items())}
    # Pin the actual frontend sources alongside the output identity. This records
    # provenance; clean build/test evidence is still a separate release gate.
    frontend_sources = {}
    for p in sorted((source / 'implementation/frontend').rglob('*')):
        rel = p.relative_to(source / 'implementation/frontend')
        if any(part in {'dist', 'node_modules', '.git'} for part in rel.parts):
            continue
        if p.is_file() and p.suffix in {'.ts', '.tsx', '.js', '.json', '.css', '.html'}:
            _regular(source, p)
            frontend_sources[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    tracked = set(_git(source, 'ls-files').splitlines())
    untracked_inputs = sorted(str(p.relative_to(source)) for p in inputs.values()
                              if not p.is_relative_to(frontend) and str(p.relative_to(source)) not in tracked)
    if untracked_inputs and not allow_dirty:
        raise ValueError('Untracked or ignored release inputs require --allow-dirty.')
    identity = {'git_commit': commit, 'git_dirty': bool(status) or bool(untracked_inputs),
                'exact_commit': not bool(status) and not bool(untracked_inputs),
                'untracked_release_inputs': untracked_inputs,
                'git_status_sha256': hashlib.sha256(status.encode()).hexdigest(),
                'frontend_sources': frontend_sources, 'files': manifest}
    destination.mkdir(parents=True)
    try:
        for name,p in sorted(inputs.items()):
            dst = destination / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            if hashlib.sha256(dst.read_bytes()).hexdigest() != manifest[name] or hashlib.sha256(p.read_bytes()).hexdigest() != manifest[name]:
                raise ValueError('Release input changed during packaging.')
        if _git(source, 'rev-parse', 'HEAD') != commit or _git(source, 'status', '--porcelain', '--untracked-files=all') != status:
            raise ValueError('Source checkout changed during packaging.')
        manifest_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + '\n')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return len(manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='Non-production artifact explicitly marked dirty')
    args = parser.parse_args()
    print(f'Packaged {build(args.source, args.output, allow_dirty=args.allow_dirty)} files; no deployment performed.')
