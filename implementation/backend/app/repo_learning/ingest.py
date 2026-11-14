"""Bounded passive archive parsing and structural indexing, never execution."""
from __future__ import annotations
import ast
import hashlib
import heapq
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile
import zlib

MAX_COMPRESSED = 50 * 1024 * 1024
MAX_TOTAL = 150 * 1024 * 1024
MAX_FILE = 512 * 1024
MAX_FILES = 2500
MAX_RATIO = 40
EXCLUDED = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build', '.next', 'vendor'}
LOCKS = {'package-lock.json', 'pnpm-lock.yaml', 'poetry.lock', 'Cargo.lock', 'yarn.lock'}
SECRET_FILE = re.compile(r'(?i)(^\.env|\.pem$|\.key$|^id_rsa|^credentials\.json$|\.sqlite|\.db$)')
TOKEN = re.compile(r'(?i)(?:AKIA[0-9A-Z]{16}|(?:gh[pousr]_|gsk_|sk-)[a-zA-Z0-9_\-]{12,}|bearer\s+[a-zA-Z0-9._~+/\-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)')
ASSIGNMENT = re.compile(r'''(?ix)\b(?:api[_-]?key|secret|password|passwd|token|credential|private[_-]?key)\s*[:=]\s*(["'])([^"'\r\n]{4,})\1''')
ENTROPY_ASSIGNMENT = re.compile(r'''(?x)(\b[A-Za-z_][A-Za-z0-9_]*\s*[:=]\s*)(["'])([A-Za-z0-9+/=_-]{24,})\2''')

CONFIG_SECRET = re.compile(r"(?im)^(?P<prefix>[ \t]*[\"']?[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|connection[_-]?(?:string|url)|database[_-]?url|credentials?)[A-Za-z0-9_.-]*[\"']?[ \t]*[:=][ \t]*)(?P<value>[^\r\n]+)")
CONNECTION_URI = re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql)://[^\s\"'<>]+")

class ImportFailure(ValueError):
    pass

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

SENSITIVE_NAME = re.compile(r'(?i)[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|connection[_-]?(?:string|url)|database[_-]?url|credentials?)[A-Za-z0-9_.-]*')
JSON_KEY = re.compile(r'(?P<key>"(?:\\.|[^"\\\r\n])*")[ \t]*:[ \t\r\n]*')
SINGLE_KEY = re.compile(r"(?P<key>'(?:\\.|[^'\\\r\n])*')[ \t]*:[ \t\r\n]*")
SINGLE_VALUE = re.compile(r"'(?:\\.|[^'\\])*'")
YAML_SECRET = re.compile(rf'(?i)^(?P<indent>[ \t]*(?:-[ \t]+)?)(?P<key>["\']?{SENSITIVE_NAME.pattern.removeprefix("(?i)")}["\']?)[ \t]*:[ \t]*(?P<value>[^\r\n]*)(?P<ending>\r?\n)?$')
REDACTED = '<REDACTED_SECRET_LITERAL>'


def _fail_closed_text(text: str) -> str:
    return REDACTED + '\n' * text.count('\n')


def _redact_quoted_keys(text: str) -> str:
    replacements = []
    decoder = json.JSONDecoder()
    for pattern in (JSON_KEY, SINGLE_KEY):
        covered_until = 0
        for match in pattern.finditer(text):
            if match.start() < covered_until:
                continue
            try:
                key = json.loads(match['key']) if pattern is JSON_KEY else ast.literal_eval(match['key'])
            except (ValueError, SyntaxError):
                continue
            if not isinstance(key, str) or not SENSITIVE_NAME.fullmatch(key):
                continue
            line_start = text.rfind('\n', 0, match.start()) + 1
            value_start = match.end()
            try:
                if text.startswith("'", value_start) and not text.startswith("'''", value_start):
                    literal = SINGLE_VALUE.match(text, value_start)
                    if literal is None:
                        return _fail_closed_text(text)
                    end = literal.end()
                else:
                    _, end = decoder.raw_decode(text, value_start)
            except (ValueError, RecursionError):
                # Only defer a non-JSON scalar if the YAML pass actually
                # recognizes this raw key. Escaped JSON keys must never skip.
                line_end = text.find('\n', match.start())
                line = text[line_start:line_end + 1 if line_end >= 0 else len(text)]
                if YAML_SECRET.fullmatch(line):
                    continue
                # Unknown formats with a known sensitive key fail closed.
                return _fail_closed_text(text)
            replacements.append((value_start, end))
            covered_until = end
    cursor = 0
    pieces = []
    for start, end in sorted(replacements):
        if start < cursor:
            continue
        pieces.extend((text[cursor:start], '"' + REDACTED + '"' + '\n' * text[start:end].count('\n')))
        cursor = end
    return ''.join(pieces) + text[cursor:]


def _redact_yaml_values(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result = []
    index = 0
    while index < len(lines):
        match = YAML_SECRET.fullmatch(lines[index])
        if not match:
            result.append(lines[index]); index += 1
            continue
        indent = len(match['indent'].expandtabs(8))
        ending = match['ending'] or ''
        result.append(match['indent'] + match['key'] + ': ' + REDACTED + ending)
        index += 1
        while index < len(lines):
            line = lines[index]
            prefix = re.match(r'[ \t]*', line).group(0)
            sequence = not match['value'].strip() and len(prefix.expandtabs(8)) == indent and line[len(prefix):].startswith('- ')
            if line.strip() and len(prefix.expandtabs(8)) <= indent and not sequence:
                break
            result.append(prefix + ('- ' if sequence else '') + (REDACTED if line.strip() else '') + ('\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''))
            index += 1
    return ''.join(result)


def sanitize(text: str) -> str:
    text = _redact_yaml_values(_redact_quoted_keys(text))
    text = TOKEN.sub(lambda m: '<REDACTED_SECRET_LITERAL>' + '\n' * m.group(0).count('\n'), text)
    text = CONFIG_SECRET.sub(lambda m: m.group('prefix') + '<REDACTED_SECRET_LITERAL>', text)
    text = CONNECTION_URI.sub('<REDACTED_SECRET_LITERAL>', text)
    text = ASSIGNMENT.sub(lambda m: m.group(0).replace(m.group(2), '<REDACTED_SECRET_LITERAL>'), text)
    def redact_entropy(m):
        value = m.group(3)
        entropy = -sum((value.count(c)/len(value))*math.log2(value.count(c)/len(value)) for c in set(value))
        return m.group(1) + m.group(2) + ('<REDACTED_SECRET_LITERAL>' if entropy >= 3.5 else value) + m.group(2)
    return ENTROPY_ASSIGNMENT.sub(redact_entropy, text)

def allowed(path: PurePosixPath) -> bool:
    return not any(part in EXCLUDED or part.startswith('.venv') for part in path.parts) and path.name not in LOCKS and not SECRET_FILE.search(path.name)

def validate_path(name: str) -> PurePosixPath:
    if not name or '\\' in name or '\x00' in name or name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        raise ImportFailure('invalid archive path')
    path = PurePosixPath(name)
    if '..' in path.parts or not path.parts or len(name) > 512:
        raise ImportFailure('invalid archive path')
    return path

COMPRESSED_BLOCK = 64 * 1024


def _member_range(data: bytes, info: zipfile.ZipInfo, central_offset: int) -> tuple[int, int]:
    offset = info.header_offset
    if offset < 0 or offset + 30 > central_offset or data[offset:offset + 4] != b'PK\x03\x04':
        raise ImportFailure('invalid local archive header')
    _, _, flags, method, _, _, crc, compressed, size, name_len, extra_len = struct.unpack_from('<4s5H3I2H', data, offset)
    start = offset + 30 + name_len + extra_len
    end = start + info.compress_size
    if start > central_offset or end > central_offset or method != info.compress_type or flags != info.flag_bits:
        raise ImportFailure('archive local metadata mismatch')
    try:
        name = data[offset + 30:offset + 30 + name_len].decode('utf-8' if flags & 0x800 else 'cp437')
    except UnicodeDecodeError as exc:
        raise ImportFailure('invalid local archive name') from exc
    validate_path(name)
    if name != info.orig_filename or (not flags & 8 and (crc, compressed, size) != (info.CRC, info.compress_size, info.file_size)):
        raise ImportFailure('archive local metadata mismatch')
    if method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ImportFailure('unsupported compression method')
    return start, end


def _decode_member(data: bytes, info: zipfile.ZipInfo, bounds: tuple[int, int], budget: int) -> bytes:
    start, end = bounds
    limit = min(info.file_size, MAX_FILE, budget)
    if info.compress_type == zipfile.ZIP_STORED:
        if end - start > limit:
            raise ImportFailure('archive decoded size exceeded')
        raw = data[start:end]
    else:
        decoder = zlib.decompressobj(-zlib.MAX_WBITS)
        output = bytearray()
        try:
            for offset in range(start, end, COMPRESSED_BLOCK):
                part = decoder.decompress(data[offset:min(offset + COMPRESSED_BLOCK, end)], limit + 1 - len(output))
                output.extend(part)
                if len(output) > limit or decoder.unconsumed_tail or decoder.unused_data:
                    raise ImportFailure('archive decoded size exceeded')
            if not decoder.eof:
                raise ImportFailure('incomplete compressed archive member')
        except zlib.error as exc:
            raise ImportFailure('invalid compressed archive member') from exc
        raw = bytes(output)
    if len(raw) != info.file_size or zlib.crc32(raw) != info.CRC:
        raise ImportFailure('archive size or checksum mismatch')
    return raw


def _directory_offset(data: bytes) -> int:
    if len(data) > MAX_COMPRESSED:
        raise ImportFailure('archive exceeds compressed limit')
    # Validate the classic EOCD before ZipFile allocates its central-directory entries.
    end = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    if end < 0 or end + 22 > len(data): raise ImportFailure('invalid archive')
    _, disk, start_disk, on_disk, entries, central_size, central_offset, comment = struct.unpack_from('<4s4H2IH', data, end)
    if disk or start_disk or on_disk != entries or entries > MAX_FILES or entries == 0xffff or central_size == 0xffffffff or central_offset == 0xffffffff or end + 22 + comment != len(data) or central_offset + central_size != end:
        raise ImportFailure('unsupported archive directory')
    cursor=central_offset; seen_entries=0
    while cursor < end:
        if cursor + 46 > end or data[cursor:cursor+4] != b'PK\x01\x02': raise ImportFailure('invalid archive directory')
        name_len, extra_len, comment_len = struct.unpack_from('<HHH',data,cursor+28)
        cursor += 46 + name_len + extra_len + comment_len
        seen_entries += 1
        if cursor > end or seen_entries > MAX_FILES: raise ImportFailure('archive entry limit exceeded')
    if cursor != end or seen_entries != entries: raise ImportFailure('invalid archive directory')
    return central_offset


def _member_ranges(data: bytes, infos: list[zipfile.ZipInfo], central_offset: int) -> dict:
    if len(infos) > MAX_FILES:
        raise ImportFailure('archive entry limit exceeded')
    bounds = {info: _member_range(data, info, central_offset) for info in infos}
    previous_end = 0
    for info in sorted(infos, key=lambda item: item.header_offset):
        if info.header_offset < previous_end:
            raise ImportFailure('overlapping archive members')
        previous_end = bounds[info][1]
    return bounds


def unpack(data: bytes) -> tuple[dict[str, str], dict[str, int]]:
    central_offset = _directory_offset(data)
    files = {}; coverage = {'total': 0, 'skipped': 0, 'skipped_secret': 0, 'skipped_filtered': 0, 'skipped_oversize': 0, 'skipped_binary': 0, 'redaction_count': 0}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            bounds = _member_ranges(data, infos, central_offset)
            total = decoded_total = 0; seen = set()
            for info in infos:
                p = validate_path(info.filename)
                if str(p) in seen:
                    raise ImportFailure('duplicate archive path')
                seen.add(str(p))
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ImportFailure('unsupported archive entry')
                if info.flag_bits & 1:
                    raise ImportFailure('encrypted archive entry')
                if info.is_dir():
                    continue
                coverage['total'] += 1
                total += info.file_size
                if total > MAX_TOTAL:
                    raise ImportFailure('archive size limit exceeded')
                if info.file_size and (not info.compress_size or info.file_size > MAX_RATIO * info.compress_size):
                    raise ImportFailure('archive compression ratio exceeded')
                if info.file_size > MAX_FILE:
                    coverage['skipped'] += 1; coverage['skipped_oversize'] += 1; continue
                if not allowed(p):
                    coverage['skipped'] += 1
                    coverage['skipped_secret' if SECRET_FILE.search(p.name) else 'skipped_filtered'] += 1
                    continue
                raw = _decode_member(data, info, bounds[info], MAX_TOTAL - decoded_total)
                decoded_total += len(raw)
                if decoded_total > MAX_TOTAL:
                    raise ImportFailure('archive decoded work limit exceeded')
                if b'\0' in raw:
                    coverage['skipped'] += 1; coverage['skipped_binary'] += 1; continue
                try: text = raw.decode('utf-8')
                except UnicodeDecodeError:
                    coverage['skipped'] += 1; coverage['skipped_binary'] += 1; continue
                clean = sanitize(text)
                coverage['redaction_count'] += max(0, clean.count('<REDACTED_SECRET_LITERAL>') - text.count('<REDACTED_SECRET_LITERAL>'))
                files[str(p)] = clean
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ImportFailure('invalid archive') from exc
    return files, coverage

def golden(name: str) -> tuple[dict[str, str], dict[str, int]]:
    choices = {'REPO-EXP-01': 'viva', 'REPO-EXP-02': 'webhookref'}
    if name not in choices: raise ImportFailure('unknown golden repository')
    root = Path(__file__).parent / 'golden' / (choices[name] + '.json')
    data = json.loads(root.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or len(data) > MAX_FILES: raise ImportFailure('invalid golden snapshot')
    files = {}
    for path, text in data.items():
        p = validate_path(path)
        if not allowed(p) or not isinstance(text, str) or len(text.encode()) > MAX_FILE: raise ImportFailure('invalid golden snapshot')
        files[path] = sanitize(text)
    return files, {'total': len(files), 'skipped': 0}

def _tree_symbol(node, scope: tuple[str, ...], raw: bytes) -> tuple[dict, str] | None:
    value = node.child_by_field_name('value')
    is_bound_function = node.type in {'variable_declarator','public_field_definition','field_definition'} and value is not None and value.type in {'arrow_function','function_expression','generator_function'}
    if not is_bound_function and node.type not in {'function_declaration','method_declaration','method_definition','class_declaration','interface_declaration','type_declaration'}:
        return None
    name = node.child_by_field_name('name')
    if name is None:
        return None
    local = raw[name.start_byte:name.end_byte].decode()
    qualname = '.'.join((*scope,local))[:256]
    end_line = max(node.start_point.row+1, node.end_point.row + (1 if node.end_point.column else 0))
    return {'name':qualname,'start_line':node.start_point.row+1,'end_line':end_line}, local


def structure(path: str, text: str) -> dict:
    ext = Path(path).suffix.lower(); imports = []; calls = []; symbols = []
    language = {'.py':'python', '.js':'javascript', '.jsx':'javascript', '.ts':'typescript', '.tsx':'tsx', '.go':'go', '.java':'java'}.get(ext, 'text')
    status = 'lexical'
    if language == 'python':
        try:
            tree = ast.parse(text); status = 'parsed'
            class Visitor(ast.NodeVisitor):
                def __init__(self): self.scope = []
                def visit_FunctionDef(self, node):
                    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
                    symbols.append({'name': '.'.join(self.scope + [node.name])[:256], 'start_line': start, 'end_line': node.end_lineno or node.lineno})
                    self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
                visit_AsyncFunctionDef = visit_FunctionDef
                def visit_ClassDef(self, node):
                    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
                    symbols.append({'name': '.'.join(self.scope + [node.name])[:256], 'start_line': start, 'end_line': node.end_lineno or node.lineno})
                    self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
                def visit_Import(self, node): imports.extend(a.name for a in node.names)
                def visit_ImportFrom(self, node): imports.append(node.module or '')
                def visit_Call(self, node):
                    if isinstance(node.func, ast.Name): calls.append(node.func.id)
                    elif isinstance(node.func, ast.Attribute): calls.append(node.func.attr)
                    self.generic_visit(node)
            Visitor().visit(tree)
        except (SyntaxError, ValueError, RecursionError): status = 'parse_error'
    elif language != 'text':
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_javascript as js, tree_sitter_typescript as ts, tree_sitter_go as go, tree_sitter_java as java
            factory = {'javascript': js.language, 'typescript': ts.language_typescript, 'tsx': ts.language_tsx, 'go': go.language, 'java': java.language}[language]
            raw = text.encode(); tree = Parser(Language(factory())).parse(raw)
            status = 'parse_error' if tree.root_node.has_error else 'parsed'
            stack = [(tree.root_node, ())]
            while stack:
                n, scope = stack.pop()
                child_scope = scope
                found = _tree_symbol(n, scope, raw)
                if found:
                    symbol, local = found
                    symbols.append(symbol)
                    child_scope=(*scope,local)
                if n.type in {'import_statement','import_declaration','import_spec'}:
                    imports.append(raw[n.start_byte:n.end_byte].decode()[:256])
                if n.type in {'call_expression','method_invocation'}:
                    name = n.child_by_field_name('function') or n.child_by_field_name('name')
                    if name: calls.append(raw[name.start_byte:name.end_byte].decode()[:128])
                stack.extend((child,child_scope) for child in reversed(n.children))
        except (ImportError, ValueError, RecursionError): status = 'parser_unavailable'
    return {'language':language,'status':status,'imports':sorted(set(imports))[:2000], 'calls':sorted(set(calls))[:2000], 'symbols':symbols[:2000]}


CHUNK_LINES = 80


def chunk_spans(text: str, info: dict) -> list[tuple[str, int, int]]:
    """Partition source once at symbol boundaries, keeping the innermost label.

    Nested symbols never duplicate source text. Long bodies retain their symbol
    on every continuation. Equal-line symbols use the most specific static name;
    source ranges and hashes, not runtime execution, remain the evidence basis.
    """
    line_count = len(text.splitlines())
    if not line_count:
        return []
    starts: dict[int, list[tuple[int, dict]]] = {}
    ends: dict[int, list[int]] = {}
    for index, symbol in enumerate(info['symbols']):
        start, end = symbol['start_line'], symbol['end_line']
        if not 1 <= start <= end <= line_count:
            continue
        starts.setdefault(start, []).append((index, symbol))
        ends.setdefault(end + 1, []).append(index)
    boundaries = sorted({1, line_count + 1, *starts, *ends})
    active: set[int] = set()
    heap: list[tuple[int, int, str, int]] = []
    spans = []
    for start, stop in zip(boundaries, boundaries[1:]):
        for index in ends.get(start, ()):
            active.discard(index)
        for index, symbol in starts.get(start, ()):
            active.add(index)
            heapq.heappush(heap, (symbol['end_line'] - start, -symbol['name'].count('.'), symbol['name'], index))
        while heap and heap[0][3] not in active:
            heapq.heappop(heap)
        name = heap[0][2] if heap else ''
        spans.extend((name, line, min(line + CHUNK_LINES, stop) - 1) for line in range(start, stop, CHUNK_LINES))
    return spans
