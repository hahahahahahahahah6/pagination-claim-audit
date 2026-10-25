"""Static documentation and pagination evidence analysis; no target code is run."""
import ast
import fnmatch
import re
from pathlib import Path

PAGINATED = (
    'paginated', 'paginated results', 'paginated output', 'supports pagination',
    'with pagination', 'page through results', 'fetches results page by page',
    'fetches page by page', 'results are paginated', 'output is paginated',
    'pages through results',
)
SINGLE = (
    'returns all results at once', 'fetches all results at once',
    'all results in one request', 'in a single request', 'no pagination',
    'without pagination', 'unpaginated', 'single-page results',
    'returns everything at once',
)
PARAMETERS = frozenset(('page', 'page_number', 'page_size', 'per_page', 'limit',
                        'offset', 'cursor', 'next_page_token',
                        'continuation_token', 'start_after', 'page_token'))
NEXT_NAMES = frozenset(('next_page', 'next_page_token', 'next'))
NEXT_CALLS = frozenset(('next_page', 'fetch_next_page', 'get_next_page'))
NEGATION = re.compile(r"\b(?:no|not|never|without|doesn't|don't|isn't)\b", re.I)
# The explicit negative example in the contract is a single-shot promise.
NEGATIVE_PAGINATED = re.compile(r'\bresults are not paginated\b', re.I)


def contains(text, phrase):
    return re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', re.sub(r'\s+', ' ', text), re.I) is not None


def extract_claims(text, path='README.md'):
    """Return one claim per family per prose sentence, excluding fenced code."""
    prose = []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            prose.append((number, line))
    # Preserve sentence continuity across wrapped lines and blank paragraphs.
    joined = '\n'.join(line for _, line in prose)
    claims = []
    for match in re.finditer(r'(?:(?!\n[ \t]*\n)[^.!?])+(?:[.!?]|\n[ \t]*\n|$)', joined):
        sentence = match.group().strip()
        if not sentence:
            continue
        offset = match.start() + len(match.group()) - len(match.group().lstrip())
        index = joined[:offset].count('\n')
        line = prose[index][0] if index < len(prose) else 1
        negated = NEGATION.search(sentence)
        families = []
        if not negated and any(contains(sentence, p) for p in PAGINATED):
            families.append('paginated')
        if (any(contains(sentence, p) for p in ('no pagination', 'without pagination'))
                or NEGATIVE_PAGINATED.search(re.sub(r'\s+', ' ', sentence))
                or (not negated and any(contains(sentence, p) for p in SINGLE))):
            families.append('single-shot')
        for family in families:
            claims.append(dict(family=family, path=path, line=line, text=sentence))
    return claims


def extract_evidence(text, path='main.py'):
    tree = ast.parse(text, filename=path)
    found = {}

    def add(node, kind):
        found[(node.lineno, kind)] = dict(path=path, line=node.lineno, kind=kind)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            args += [a for a in (node.args.vararg, node.args.kwarg) if a is not None]
            if any(arg.arg in PARAMETERS for arg in args):
                add(node, 'pagination-parameter')
        if isinstance(node, ast.Call):
            if any(kw.arg in PARAMETERS for kw in node.keywords):
                add(node, 'pagination-keyword')
            if isinstance(node.func, ast.Attribute) and node.func.attr in NEXT_CALLS:
                add(node, 'next-page-call')
        if isinstance(node, ast.Attribute) and node.attr in NEXT_NAMES:
            add(node, 'next-page-access')
        if isinstance(node, ast.Subscript):
            value = node.slice
            if isinstance(value, ast.Constant) and value.value in NEXT_NAMES:
                add(node, 'next-page-access')
    # Only the body (not merely a condition) establishes an additional loop item.
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            body_lines = {child.lineno for statement in node.body
                          for child in ast.walk(statement) if hasattr(child, 'lineno')}
            if any(line in body_lines for line, _ in found) and not any(
                    line == node.lineno for line, _ in found):
                add(node, 'paging-loop')
    return sorted(found.values(), key=lambda item: (item['line'], item['kind']))


def audit(root, ignores=()):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('audit path must be a directory')
    claims, production, testonly, errors = [], [], [], []
    source_count = 0

    def ignored(rel):
        return any(fnmatch.fnmatchcase(rel, pattern) for pattern in ignores)

    # os.walk does not follow directory symlinks; also reject symlinked files.
    import os
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink()
                         and not ignored((Path(directory) / d).relative_to(root).as_posix())
                         and d not in ('.git', '__pycache__', '.venv', 'venv', 'build', 'dist'))
        for name in sorted(files):
            file = Path(directory) / name
            rel = file.relative_to(root).as_posix()
            if file.is_symlink() or name == '.env' or name.startswith('.env.') or ignored(rel):
                continue
            parts = file.relative_to(root).parts
            is_doc = rel == 'README.md' or (parts[0] == 'docs' and name.endswith('.md'))
            is_source = name.endswith('.py') and not any(p in ('docs', 'examples') for p in parts[:-1])
            if not is_doc and not is_source:
                continue
            try:
                text = file.read_text(encoding='utf-8')
                if is_doc:
                    claims.extend(extract_claims(text, rel))
                if is_source:
                    test = any(p in ('tests', 'fixtures') for p in parts[:-1]) or name.startswith('test_') or name.endswith('_test.py')
                    if not test:
                        source_count += 1
                    evidence = extract_evidence(text, rel)
                    (testonly if test else production).extend(evidence)
            except (OSError, UnicodeError, SyntaxError) as exc:
                errors.append(dict(path=rel, message=str(exc)))
    if errors:
        raise ValueError('static analysis failed: ' + '; '.join(e['path'] + ': ' + e['message'] for e in errors))
    findings, verified = [], []
    for family in ('paginated', 'single-shot'):
        family_claims = [c for c in claims if c['family'] == family]
        if not family_claims:
            continue
        severity, evidence, suffix = None, [], ''
        if source_count == 0:
            severity, evidence = 'HIGH', [dict(kind='no-source')]
        elif family == 'paginated' and not production:
            severity = 'MEDIUM' if testonly else 'HIGH'
            evidence = testonly
            suffix = '-test-only' if testonly else ''
        elif family == 'single-shot' and (production or testonly):
            severity = 'HIGH' if production else 'MEDIUM'
            evidence = production if production else testonly
            suffix = '-test-only' if not production else ''
        if severity:
            findings.append(dict(rule='documented-' + family + '-claim-false' + suffix,
                                 severity=severity, claims=family_claims, evidence=evidence))
        else:
            verified.append(dict(family=family, claims=family_claims,
                                 evidence=production if family == 'paginated' else []))
    return dict(version='0.1.0', findings=findings, verified_claims=verified)
