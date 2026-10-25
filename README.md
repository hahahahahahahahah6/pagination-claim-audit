# pagination-claim-audit

Offline audit of documented pagination claims against Python source.

Version 0.1.0. Requires Python 3.9 or newer. Runtime uses only the standard
library. Analysis runs offline and never executes or imports target code.

## Usage

```sh
python3 -m pip install .
pagination-claim-audit /path/to/project
python3 -m pagination_claim_audit /path/to/project --json
pagination-claim-audit . --verbose --ignore 'vendor/*' --ignore 'generated/*'
pagination-claim-audit . --fail-on HIGH
pagination-claim-audit --version
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

The path defaults to the current directory. `--ignore` is repeatable and
matches case-sensitive relative path globs. `--json` emits an object with
`version`, `findings`, and `verified_claims`; each finding carries `rule`,
`severity`, `claims`, and `evidence`. `--verbose` shows claim and evidence
locations in text mode. Usage, unreadable input, and syntax errors exit 1.
A clean audit exits 0; findings at the selected threshold exit 2. The default
threshold is MEDIUM. HIGH allows MEDIUM findings to remain visible with exit 0.

## Claims

Only root README.md and docs/**/*.md supply claims. Fenced code is excluded;
inline code spans count as prose. Exact phrases are matched case-insensitively
with word boundaries. There are two independent claim families. The complete
phrase inventory is shown here, within a fence to keep self-audits clean:

```text
PAGINATED:
paginated
paginated results
paginated output
supports pagination
with pagination
page through results
fetches results page by page
fetches page by page
results are paginated
output is paginated
pages through results

SINGLE-SHOT:
returns all results at once
fetches all results at once
all results in one request
in a single request
no pagination
without pagination
unpaginated
single-page results
returns everything at once

Explicit negative example interpreted as SINGLE-SHOT:
results are not paginated
```

Negation is asymmetric: a sentence containing no, not, never, without,
doesn't, don't, or isn't suppresses the affirmative paging family. Negative
phrases in the second family still count as promises of a single response.
Other second-family phrases are suppressed in negated sentences. The explicit
negative example above also belongs to the second family. A bare `page` noun
and the noun phrase `pagination support` are not claims. The adjective in the
first line of the inventory is sufficient by itself. Spelling and hyphenation
must match the inventory; arbitrary wording variants are not inferred.

## Rules

One finding is emitted per contradicted family; repeated prose is retained
within its claims list. A tree with both families is evaluated independently.

| Rule | Severity | Condition |
| --- | --- | --- |
| documented-paginated-claim-false | HIGH | Affirmative paging claim without production or test evidence |
| documented-paginated-claim-false-test-only | MEDIUM | Affirmative paging claim supported only by test evidence |
| documented-single-shot-claim-false | HIGH | Single-response claim with production paging evidence |
| documented-single-shot-claim-false-test-only | MEDIUM | Single-response claim with only test paging evidence |

With no production Python source, each present family gets its HIGH rule and
`no-source` evidence. Affirmative paging claims with production evidence are
verified. Single-response claims without any evidence are verified. With no
claims, the audit passes regardless of evidence.

## Named evidence

| Kind | Static signal |
| --- | --- |
| pagination-parameter | Function or async function with a listed parameter |
| pagination-keyword | Call using a listed keyword argument |
| next-page-call | Attribute call to next_page, fetch_next_page, get_next_page |
| next-page-access | Attribute or literal subscript access to next_page, next_page_token, next |
| paging-loop | While body contains one of those signals; extra item only on a distinct line |

The parameter/keyword set is `page`, `page_number`, `page_size`, `per_page`,
`limit`, `offset`, `cursor`, `next_page_token`, `continuation_token`,
`start_after`, and `page_token`. Each definition or call site contributes one
item per kind, deduplicated by file, line, and kind. All relevant evidence
appears in a contradiction finding. A loop condition can supply access
evidence, but an additional loop item requires a signal in its body.

Production excludes tests/ and fixtures/ directories, test_*.py and *_test.py;
these contribute only test evidence. docs/ and examples/ source is excluded.
Symlinked files and directories are skipped. Environment files are never
opened. Only Markdown claim sources and eligible .py files are read. The
scanner also skips .git, virtual environments, build artifacts and caches.

## Differentiation

| Neighbour | Its question | This tool's question |
| --- | --- | --- |
| streaming-claim-audit | Local read chunking | Result paging promises |
| retry-claim-audit | Attempt counts | Result splitting promises |
| api-claim-audit | Symbols and signatures | Paging behaviour |
| schema-claim-audit | Field names | Page structure promises |
| bandit / ruff | Code issues | Documentation versus source |
| requests / httpx pagination helpers | Paging primitives | Documentation versus source |

## Honest limitations

This is static evidence, not a proof that a fetch reaches a remote service.
Dead code counts. A `limit` keyword on a non-fetch call still counts, an
intentional over-approximation. A local variable or ordinary attribute named
`page` alone does not count; a function parameter by that name does. Dict keys
such as `page` or `limit` alone do not establish a fetch. Iterating
`for page in pages` alone does not establish fetch-time paging either.
Third-party helpers such as Django Paginator, SQLAlchemy paginate, and
requests wrappers are out of scope unless they expose the recognized names.
Response-like next-field access is recognized syntactically without type
inference. Dynamic keywords, aliases, computed keys and runtime control flow
are not resolved. Exact-phrase matching misses paraphrases and can mistake
quoted prose for a promise; use a fenced block for illustrative phrases.
There is no reachability analysis or network access. Source must parse and
text files must be UTF-8; analysis errors are reported as usage errors.

Fixtures and unittest tests ship in the source distribution via MANIFEST.in.
The wheel exposes both the console command and module entry point.
MIT licensed; see LICENSE.
