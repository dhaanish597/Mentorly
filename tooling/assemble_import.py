"""Materialize imported bytes using explicit, validated Drive ID mappings."""
from pathlib import Path, PurePosixPath
import hashlib
import json
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
IMPORTED = ROOT / 'imports/drive-20261113'
ACTIVE = ROOT / 'implementation'
rows = json.loads((IMPORTED / 'downloads.json').read_text())
by_id = {r['id']: r for r in rows}
assert len(by_id) == len(rows), 'duplicate IDs require manual resolution'
selected = {}
conflicts = []

def select(fid, target, reason):
    path = PurePosixPath(target)
    if path.is_absolute() or '..' in path.parts or '\\' in target:
        raise ValueError(f'Unsafe target: {target}')
    if any(x in path.parts for x in ('.git', '.venv', 'node_modules', '__pycache__')):
        raise ValueError(f'Forbidden target: {target}')
    if path.name.startswith('.env') and path.name != '.env.example':
        raise ValueError('Secret target')
    r = by_id[fid]
    raw = (IMPORTED / r['raw_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == r['sha256']
    old = selected.get(target)
    if old and old['drive_file_id'] != fid:
        conflicts.append({'target': target, 'previous_id': old['drive_file_id'], 'selected_id': fid, 'reason': reason})
    selected[target] = {'drive_file_id': fid, 'import_path': r['root']+'/'+r['logical_path'], 'sha256': r['sha256'], 'bytes': len(raw), 'reason': reason}

# Canonical base: duplicate logical names never choose by timestamp.
base = defaultdict(list)
for r in rows:
    if r['root'] == 'main' and r['logical_path'].startswith('implementation/'):
        base[r['logical_path'][15:]].append(r)
for target, versions in base.items():
    if len(versions) != 1:
        raise RuntimeError(f'Ambiguous base: {target}')
    select(versions[0]['id'], target, 'canonical main base')

manifest = json.loads((IMPORTED / by_id['1V1QbCveVYAbn6oVfmpmBsth3ZMWrCi_-']['raw_path']).read_text())
bundle = json.loads((IMPORTED / by_id['1mRQch2vyqGuNzgjaf1_imMFJKvAcHkJ0']['raw_path']).read_text())
claims = []
for target, entry in manifest['reconciled_overlays_by_logical_path'].items():
    select(entry['drive_file_id'], target, 'canonical manifest explicit overlay')
    if entry.get('bytes') != selected[target]['bytes']:
        claims.append({'target':target,'claimed_bytes':entry.get('bytes'),'actual_bytes':selected[target]['bytes']})
# The bundle supplies the frontend/evaluation/deployment files omitted from canonical manifest.
# For two conflicting destinations the canonical manifest and corrected plan own the path.
for entry in bundle['p3_to_p9_deliverables']['files']:
    fid = entry['id']
    # Verified unique raw source; bundle contains a one-character ID typo.
    if fid == '1f2hse9H7IOucGs_dvrvjTAvhx_da2Tmd':
        fid = '1f2hse9H7IOucGs_dvrvjTAvhx8da2Tmd'
    existing = [p for p,r in selected.items() if r['drive_file_id']==fid]
    if existing:
        continue
    select(fid, entry['target'], 'bundle unique P3-P9 mapping omitted from canonical manifest')
# Unique predecessor configuration still required by the selected overlays.
legacy = {'ci.yml':'.github/workflows/ci.yml','exec_worker_README.md':'exec_worker/README.md','README.md':'README.md','.env.example':'.env.example','Makefile':'Makefile'}
for r in rows:
    if r['root']=='secondary' and r['logical_path'].count('/')==1 and r['logical_path'].startswith('implementation_updates/'):
        if r['name'] in legacy:
            select(r['id'], legacy[r['name']], 'unique continuation configuration')
# Preserve every duplicate document; handoff-selected documents get explicit IDs.
docs_ids = {
 'RECONCILIATION_AND_HANDOFF_BUNDLE.json':'1mRQch2vyqGuNzgjaf1_imMFJKvAcHkJ0',
 'CANONICAL_SOURCE_MANIFEST.json':'1V1QbCveVYAbn6oVfmpmBsth3ZMWrCi_-',
 'PHASE_2_REPAIR_STATUS.md':'1IUW49Wo8ziarEqmM8w1g8fKoa_Y90TEWx5y0q0WDmVg',
 'CODEX_TAKEOVER_AUDIT.md':'1jP1tw_7DJRZ9lJusnCN6UI83Dk4mq6qlNdUxBhH6jnU',
 'ACCOUNT_HANDOFF.md':'1hPo4dj7T4EZJtWecHrwR4f2x97hfMRtKxNeHW1M007k',
 'ACTIVE_WORK.md':'1PkoUOG4gHu3bPmduZygeS9oCa0x8bLeMhgpLKtQFqcI',
 'DRIVE_RECONCILIATION.md':'1ipdBfMZEdvsRCeBYh4SkgzOKgFbqh9WvkkT9y0WlAEg',
 'DECISIONS.md':'1xpvGrEPf0U7uruXMp43_sl6Wg_xK0Isf',
 'IMPLEMENTATION_STATUS.md':'1IPVctnJMtqPoJX2G7BUcSi3zrmZWbnhQ',
 'FEATURE_COVERAGE.md':'1nCe1TP1wiOla-etBHdEH0wHSuKLuk3Bg',
 'GNANI_CAPABILITIES.md':'1AFfrMR6-4JppmkMNitJMOufweR-ahxSV',
}
for name,fid in docs_ids.items():
    select(fid,'docs/'+name,'explicit newest handoff record; all originals retained by ID')
select('1XwOvOJ6VaoKm-D9XLgfwQK9XrzU1iQRp','cloud/FULL_PROJECT_COLAB.ipynb','latest full-project notebook')
if ACTIVE.exists():
    raise RuntimeError('Active tree exists; refuse to overwrite local work')
for target,r in selected.items():
    dest=ACTIVE/target
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes((IMPORTED/by_id[r['drive_file_id']]['raw_path']).read_bytes())
report={'selected':selected,'overlays':conflicts,'manifest_claim_discrepancies':claims,'unselected_import_ids':[r['id'] for r in rows if r['id'] not in {e['drive_file_id'] for e in selected.values()}]}
(IMPORTED/'resolved_source_map.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'active_files':len(selected),'overlay_conflicts':len(conflicts),'size_claim_discrepancies':claims},indent=2))
