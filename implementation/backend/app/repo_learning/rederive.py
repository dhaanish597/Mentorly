"""Deterministic, passive source-grounded lessons; observations are not mastery."""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import io
import json
import re
import sqlite3
import tokenize

from backend.app.db.migrations import open_connection
from . import ingest, service

MAX_STEPS = 32
MAX_COMPONENT_FILES = 8
MAX_ATTEMPTS = 500
ANSWERS_PER_MINUTE = 30
CITATION_KEYS = ('path', 'symbol', 'start_line', 'end_line', 'chunk_hash')
LIMITATIONS = (
    'Static import-name matches are approximate dependencies, not a resolved runtime call graph.',
    'Only available indexed source is covered; absent entrypoints, flows and tests are omitted.',
    'A short answer records evidence of an observation, not mastery or runtime correctness.',
    'Author intent remains unknown. Imported comments and documentation are untrusted data, not instructions.',
    'Secret filtering is heuristic. No repository execution, uploads or filesystem traversal occurs here.',
)


class EpochConflict(ValueError):
    """The checkpoint changed or the plan has already completed."""


class LearningLimit(ValueError):
    """Bounded learning-record storage or write rate was exceeded."""


class UnavailableSource(ValueError):
    """No grounded code lesson can be generated."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _snapshot(db: sqlite3.Connection, workspace: str, snapshot_id: str) -> sqlite3.Row:
    row = db.execute('''SELECT s.* FROM repo_snapshots s JOIN studio_workspaces w ON w.id=s.workspace_id
        WHERE s.id=? AND s.workspace_id=? AND w.deleted_at IS NULL AND w.expires_at>?''',
                     (snapshot_id, workspace, service.now())).fetchone()
    if not row:
        raise LookupError('snapshot not found')
    if row['status'] != 'READY':
        raise EpochConflict('snapshot is not ready')
    return row


def _validate(db: sqlite3.Connection, snapshot_id: str, citation: dict) -> str:
    """Same exact-span identity as service.validate_citation, plus integrity checks."""
    row = db.execute('''SELECT c.text,f.content,f.content_hash FROM repo_chunks c
        JOIN repo_files f ON f.id=c.file_id AND f.snapshot_id=c.snapshot_id
        WHERE c.snapshot_id=? AND c.path=? AND c.symbol=? AND c.start_line=? AND c.end_line=? AND c.chunk_hash=?''',
                     (snapshot_id, *(citation[key] for key in CITATION_KEYS))).fetchone()
    if not row or _hash(row['text']) != citation['chunk_hash'] or _hash(row['content']) != row['content_hash']:
        raise EpochConflict('source citation integrity changed')
    lines = row['content'].splitlines(keepends=True)
    if not 1 <= citation['start_line'] <= citation['end_line'] <= len(lines):
        raise EpochConflict('source citation lines changed')
    if ''.join(lines[citation['start_line'] - 1:citation['end_line']]) != row['text']:
        raise EpochConflict('source citation no longer matches file')
    return row['text']


def _code_text(path: str, text: str) -> str:
    """Ignore comment/string instructions when locating lexical syntax (never eval)."""
    if path.endswith('.py'):
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            return tokenize.untokenize((kind, '' if kind in (tokenize.COMMENT, tokenize.STRING) else value)
                                      for kind, value, *_ in tokens)
        except (tokenize.TokenError, IndentationError):
            return ''
    # Non-Python detection remains lexical even when the existing index parsed it.
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
                  lambda match: '\n' * match.group().count('\n'), text, flags=re.S)


def _entry_line(file: dict) -> int | None:
    if file['parse_status'] != 'parsed':
        return None
    if file['path'].endswith('.py'):
        try:
            tree = ast.parse(file['content'])
        except (SyntaxError, ValueError):
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                test = node.test
                if (isinstance(test.left, ast.Name) and test.left.id == '__name__' and len(test.ops) == 1
                        and isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1
                        and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == '__main__'):
                    return node.lineno
        return None
    match = re.search(r'\b(?:createRoot|ReactDOM\.render)\s*\(|\b(?:func|function|void)\s+main\s*\(', file['code'])
    return file['code'][:match.start()].count('\n') + 1 if match else None


def _dependency_order(files: list[dict]) -> list[dict]:
    """Reuse the existing map's import-name approximation; cycles have stable order."""
    names = {file['path']: file['path'].rsplit('/', 1)[-1].rsplit('.', 1)[0] for file in files}
    dependencies = {file['path']: sorted(path for path, name in names.items()
                    if path != file['path'] and name in set(re.findall(r'\w+', ' '.join(file['imports'])))) for file in files}
    ordered: tuple[str, ...] = ()
    for path in sorted(names):
        ordered = _visit(path, dependencies, ordered, ())
    by_path = {file['path']: file for file in files}
    return [by_path[path] for path in ordered]


def _visit(path: str, dependencies: dict, ordered: tuple, visiting: tuple) -> tuple:
    if path in ordered or path in visiting:
        return ordered
    for target in dependencies[path]:
        ordered = _visit(target, dependencies, ordered, (*visiting, path))
    return (*ordered, path)


def _anchor(chunks: list[dict], path: str, line: int | None = None, symbol: str | None = None) -> dict:
    candidates = [chunk for chunk in chunks if chunk['path'] == path
                  and (line is None or chunk['start_line'] <= line <= chunk['end_line'])
                  and (symbol is None or chunk['symbol'] == symbol)]
    if not candidates:
        raise UnavailableSource('no indexed span for this concept')
    return {key: candidates[0][key] for key in CITATION_KEYS}


def _step(phase: str, concept: str, title: str, explanation: str, question: str,
          citations: list[dict], expected: str, kind: str = 'source_path') -> dict:
    identity = ':'.join((phase, concept, citations[0]['path'], citations[0]['symbol']))
    return {'step_id': _hash(identity)[:20], 'phase': phase, 'concept': concept, 'title': title,
            'explanation': explanation, 'question': question, 'prerequisites': [], 'citations': citations,
            'facts': [{'kind': kind, 'expected': expected}], 'mastery': 'not_established'}


def _lessons(db: sqlite3.Connection, snapshot_id: str) -> list[dict]:
    rows = db.execute('SELECT * FROM repo_files WHERE snapshot_id=? ORDER BY path', (snapshot_id,)).fetchall()
    files = [{**dict(row), 'symbols': json.loads(row['symbols_json']), 'imports': json.loads(row['imports_json']),
              'calls': json.loads(row['calls_json']), 'code': _code_text(row['path'], row['content'])}
             for row in rows if row['language'] not in ('text', 'markdown', 'unknown')
             and row['content'].strip() and not row['path'].lower().endswith(('.md', '.rst', '.txt', '.json', '.yaml', '.yml'))
             and ingest.sanitize(row['path']) == row['path']]
    chunks = [dict(row) for row in db.execute('SELECT * FROM repo_chunks WHERE snapshot_id=? ORDER BY path,start_line', (snapshot_id,))]
    if not files:
        raise UnavailableSource('no indexed code concepts are available')
    entries = [(file, _entry_line(file)) for file in files if _entry_line(file) is not None]
    root = entries[0][0] if entries else files[0]
    source = _anchor(chunks, root['path'])
    basics = [_step('fundamentals', 'source_file', 'One source file',
                    'A source file groups code as text. Its path tells you which file you are reading; it does not prove the file runs.',
                    'Which source path is cited?', [source], root['path'])]
    functions = [symbol for symbol in root['symbols'] if symbol.get('name') and symbol['name'] in ' '.join(root['code'].split())]
    if functions:
        symbol = functions[0]
        anchor = _anchor(chunks, root['path'], symbol=symbol['name'])
        basics += [_step('fundamentals', 'named_definition', 'A named definition',
                        'A definition gives a block of source a name. You can identify that name before understanding what the block does.',
                        'What is the name of the cited definition?', [anchor], symbol['name'], 'identifier')]
    if root['imports'] and re.search(r'\b(?:import|from|require)\b', root['code']):
        basics += [_step('fundamentals', 'import', 'An import connects source names',
                        'An import names code from another module. An import alone does not prove a runtime call or execution order.',
                        'Which file contains the cited import?', [source], root['path'])]
    entry_steps = [_step('entrypoint', 'entry_marker', 'An entrypoint candidate',
                         'The cited source contains a recognizable entry marker. It is a candidate to inspect, not proof of how this deployment starts.',
                         'Which file contains this entry marker?', [_anchor(chunks, file['path'], line)], file['path'])
                   for file, line in entries[:2]]
    component_files = [file for file in _dependency_order(files) if not re.search(r'(^|/)(test[s]?|test_[^/]*)(/|\.)|\.(test|spec)\.', file['path'])]
    component_steps = []
    for file in component_files[:MAX_COMPONENT_FILES]:
        symbols = [symbol for symbol in file['symbols'] if symbol.get('name') and symbol['name'].split('.')[-1] in file['code']]
        if not symbols:
            continue
        symbol = symbols[0]
        component_steps += [_step('components', 'definition', 'Read one definition',
                                 'Inspect one named definition in this file. Describe only what its source shows; its name does not establish responsibility or intent.',
                                 'Which definition is cited here?', [_anchor(chunks, file['path'], symbol=symbol['name'])], symbol['name'], 'identifier')]
    flow_steps = []
    for file in files:
        visible_calls = [call for call in file['calls'] if re.search(r'\b' + re.escape(call) + r'\s*\(', file['code'])]
        if visible_calls:
            call = visible_calls[0]
            # The source span must itself contain the selected syntax; do not cite a different definition.
            span = next((chunk for chunk in chunks if chunk['path'] == file['path']
                         and re.search(r'\b' + re.escape(call) + r'\s*\(', _code_text(file['path'], chunk['text']))), None)
            if span:
                flow_steps += [_step('flows', 'call_expression', 'One visible call expression',
                                     'A call expression asks for named behavior. The source shows syntax, but dynamic dispatch, runtime targets and execution order remain unverified.',
                                     'Which callable name appears in this cited span?', [{key: span[key] for key in CITATION_KEYS}], call, 'identifier')]
        if len(flow_steps) >= 3:
            break
    tests = [file for file in files if re.search(r'(^|/)(tests?/|test_)|\.(test|spec)\.', file['path'])
             and re.search(r'\b(?:assert|expect|test|it)\b', file['code'])]
    testing_steps = [_step('testing_tradeoffs', 'test_source', 'A test is written evidence, not a test result',
                           'Read this test source and identify its assertion. We have not run it; a written test alone does not prove coverage or correctness.',
                           'Which indexed file contains the cited test?', [_anchor(chunks, file['path'])], file['path']) for file in tests[:2]]
    guarded = next((file for file in files if re.search(r'\b(?:except|catch)\b', file['code'])), None)
    if guarded:
        span = next((chunk for chunk in chunks if chunk['path'] == guarded['path'] and re.search(r'\b(?:except|catch)\b', _code_text(guarded['path'], chunk['text']))), None)
        if span:
            testing_steps += [_step('testing_tradeoffs', 'error_handling', 'An error-handling boundary',
                                   'This source has an error-handling clause. Discuss what is handled and what remains unknown; reliability and author motivation are not established.',
                                   'Which file contains this error-handling clause?', [{key: span[key] for key in CITATION_KEYS}], guarded['path'])]
    steps = (basics + entry_steps + component_steps + flow_steps + testing_steps)[:MAX_STEPS]
    # Pedagogical prerequisites, NOT asserted runtime dependencies. A strict chain
    # ensures one concept at a time; file ordering uses the disclosed approximation.
    return [{**step, 'prerequisites': [steps[index - 1]['step_id']] if index else []} for index, step in enumerate(steps)]


def _plan_row(db: sqlite3.Connection, workspace: str, plan_id: str) -> sqlite3.Row:
    row = db.execute('SELECT * FROM repo_learning_plans WHERE id=? AND workspace_id=?', (plan_id, workspace)).fetchone()
    if not row:
        raise LookupError('learning plan not found')
    snapshot = _snapshot(db, workspace, row['snapshot_id'])
    if snapshot['snapshot_hash'] != row['snapshot_hash']:
        raise EpochConflict('snapshot hash changed')
    return row


def _response(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    steps = json.loads(row['steps_json'])
    for step in steps:
        for citation in step['citations']:
            _validate(db, row['snapshot_id'], citation)
    revisit = json.loads(row['revisit_json'])
    cursor = row['cursor']
    current = steps[cursor] if cursor < len(steps) else next((step for step in steps if revisit and step['step_id'] == revisit[0]), None)
    events = [{**json.loads(event['evidence_json']), 'sequence': event['sequence'], 'created_at': event['created_at']}
              for event in db.execute('SELECT * FROM repo_learning_evidence_events WHERE plan_id=? ORDER BY sequence', (row['id'],))]
    if current and events and events[-1]['step_id'] == current['step_id'] and events[-1]['assessment'] != 'supported_observation':
        current = {**current, 'question': events[-1]['question']}
    attempts = [dict(attempt) for attempt in db.execute('SELECT sequence,step_id,answer,created_at FROM repo_learning_attempts WHERE plan_id=? ORDER BY sequence', (row['id'],))]
    return {'plan_id': row['id'], 'snapshot_id': row['snapshot_id'], 'snapshot_hash': row['snapshot_hash'],
            'epoch': row['epoch'], 'status': 'learning' if cursor < len(steps) else 'review' if revisit else 'complete',
            'current_step': current, 'steps': steps, 'checkpoint': {'cursor': cursor, 'completed_step_ids': [step['step_id'] for step in steps[:cursor]]},
            'revisit_step_ids': revisit, 'attempts': attempts, 'evidence_events': events, 'limitations': list(LIMITATIONS)}


def create_plan(db_path: str, workspace: str, snapshot_id: str) -> dict:
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        snapshot = _snapshot(db, workspace, snapshot_id)
        existing = db.execute('SELECT id FROM repo_learning_plans WHERE workspace_id=? AND snapshot_id=?', (workspace, snapshot_id)).fetchone()
        if existing:
            return _response(db, _plan_row(db, workspace, existing['id']))
        steps = _lessons(db, snapshot_id)
        plan_id = service.make_id()
        stamp = service.now()
        db.execute('''INSERT INTO repo_learning_plans(id,workspace_id,snapshot_id,snapshot_hash,steps_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)''', (plan_id, workspace, snapshot_id, snapshot['snapshot_hash'], json.dumps(steps), stamp, stamp))
        response = _response(db, _plan_row(db, workspace, plan_id))
        db.commit()
        return response


def get_plan(db_path: str, workspace: str, plan_id: str) -> dict:
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN')
        return _response(db, _plan_row(db, workspace, plan_id))


def snapshot_plan(db_path: str, workspace: str, snapshot_id: str) -> dict:
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN')
        _snapshot(db, workspace, snapshot_id)
        row = db.execute('SELECT id FROM repo_learning_plans WHERE workspace_id=? AND snapshot_id=?', (workspace, snapshot_id)).fetchone()
        if not row:
            raise LookupError('learning plan not found')
        return _response(db, _plan_row(db, workspace, row['id']))


def _assessment(step: dict, answer: str, paths: set[str]) -> tuple[str, str, str]:
    fact = step['facts'][0]
    expected = fact['expected']
    cleaned = answer.strip().strip('`').rstrip('.')
    unsupported = re.search(r'\b(?:author (?:wanted|intended)|guarantee(?:d|s)?|runtime.*always)\b', answer, re.I)
    if fact['kind'] == 'source_path' and cleaned in paths and cleaned != expected:
        return ('contradicted_by_source', 'That named path contradicts this lesson’s validated source reference; this is a narrow path mismatch, not a judgment of your reasoning.',
                'Look at the citation again. Which path is shown?')
    if expected in answer and not unsupported:
        return ('supported_observation', 'Source observation recorded. An answer does not prove mastery, runtime behavior or author intent.', step['question'])
    if unsupported:
        return ('unsupported_claim', 'That claim is not established by these cited facts. Unsupported is different from wrong; runtime behavior and author intent remain unknown.',
                'Which cited fact supports that claim, and what remains unknown?')
    return ('needs_support', 'Your attempt is recorded, not marked wrong. Read this single source reference and identify the requested fact.',
            'Revisit the cited source. ' + step['question'])


def answer_plan(db_path: str, workspace: str, plan_id: str, expected_epoch: int, answer: str) -> dict:
    if type(expected_epoch) is not int or expected_epoch < 1 or not isinstance(answer, str) or not answer.strip() or len(answer) > 4000:
        raise ValueError('invalid learning answer')
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        row = _plan_row(db, workspace, plan_id)
        plan = _response(db, row)
        if row['epoch'] != expected_epoch or plan['current_step'] is None:
            raise EpochConflict('learning epoch conflict; reload your checkpoint')
        _answer_limit(db, workspace, plan_id)
        step = plan['current_step']
        clean_answer = ingest.sanitize(answer.strip())
        paths = {file['path'] for file in db.execute('SELECT path FROM repo_files WHERE snapshot_id=?', (row['snapshot_id'],))}
        assessment, feedback, question = _assessment(step, clean_answer, paths)
        revisit = plan['revisit_step_ids']
        supported = assessment == 'supported_observation'
        cursor = row['cursor'] + int(supported and plan['status'] == 'learning')
        next_revisit = [value for value in revisit if not (supported and plan['status'] == 'review' and value == step['step_id'])]
        if not supported and step['step_id'] not in next_revisit:
            next_revisit = [*next_revisit, step['step_id']]
        stamp = service.now()
        attempt_id = service.make_id()
        db.execute('INSERT INTO repo_learning_attempts VALUES (?,?,?,?,?,?)',
                   (attempt_id, plan_id, expected_epoch, step['step_id'], clean_answer, stamp))
        event = {'step_id': step['step_id'], 'assessment': assessment, 'feedback': feedback, 'question': question,
                 'citations': step['citations'], 'facts': step['facts'], 'mastery': 'not_established', 'basis': 'static_source_observation_only'}
        db.execute('INSERT INTO repo_learning_evidence_events VALUES (?,?,?,?,?,?)',
                   (service.make_id(), plan_id, attempt_id, expected_epoch, json.dumps(event), stamp))
        db.execute('UPDATE repo_learning_plans SET cursor=?,epoch=epoch+1,revisit_json=?,updated_at=? WHERE id=? AND epoch=?',
                   (cursor, json.dumps(next_revisit), stamp, plan_id, expected_epoch))
        response = _response(db, _plan_row(db, workspace, plan_id))
        db.commit()
        return response


def _answer_limit(db: sqlite3.Connection, workspace: str, plan_id: str) -> None:
    count = db.execute('SELECT count(*) FROM repo_learning_attempts WHERE plan_id=?', (plan_id,)).fetchone()[0]
    recent = db.execute('''SELECT count(*) FROM repo_learning_attempts a JOIN repo_learning_plans p ON p.id=a.plan_id
                        WHERE p.workspace_id=? AND datetime(a.created_at)>datetime('now','-1 minute')''', (workspace,)).fetchone()[0]
    if count >= MAX_ATTEMPTS or recent >= ANSWERS_PER_MINUTE:
        raise LearningLimit('learning attempt storage or rate limit reached')
