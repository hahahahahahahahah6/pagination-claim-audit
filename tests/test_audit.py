import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pagination_claim_audit.audit import audit, extract_claims, extract_evidence, PAGINATED, SINGLE, PARAMETERS
from pagination_claim_audit.__main__ import main

FIXTURES = Path(__file__).parent / 'fixtures'


class Claims(unittest.TestCase):
    def families(self, text):
        return {c['family'] for c in extract_claims(text)}

    def test_bare_page(self):
        self.assertEqual(self.families('the page size parameter'), set())

    def test_bare_noun(self):
        self.assertEqual(self.families('pagination support'), set())

    def test_adjective(self):
        self.assertEqual(self.families('a paginated listing'), {'paginated'})

    def test_negative_example(self):
        self.assertEqual(self.families('results are not paginated'), {'single-shot'})

    def test_negated_single(self):
        self.assertEqual(self.families('does not return all results at once'), set())

    def test_negative_phrase(self):
        self.assertEqual(self.families('no pagination'), {'single-shot'})

    def test_without_phrase(self):
        self.assertEqual(self.families('without pagination'), {'single-shot'})

    def test_inline(self):
        self.assertEqual(self.families('Use `paginated` output.'), {'paginated'})

    def test_fenced(self):
        self.assertEqual(self.families('```text\nresults are paginated\n```'), set())

    def test_tilde_fence(self):
        self.assertEqual(self.families('~~~\npaginated\n~~~'), set())

    def test_boundary(self):
        self.assertEqual(self.families('unpaginated'), {'single-shot'})

    def test_sentence_negation(self):
        self.assertEqual(self.families('Never paginated. Returns everything at once.'), {'single-shot'})

    def test_optional_word_not_allowed(self):
        self.assertEqual(self.families('fetches results gradually page by page'), set())

    def test_hyphen_exact(self):
        self.assertEqual(self.families('single page results'), set())

    def test_line_number(self):
        self.assertEqual(extract_claims('# Header\n\nResults are paginated.')[0]['line'], 3)

    def test_wrapped(self):
        self.assertEqual(self.families('results are\npaginated'), {'paginated'})


class Evidence(unittest.TestCase):
    def evidence(self, code):
        return extract_evidence(code)

    def test_keywords(self):
        self.assertEqual(len(self.evidence('fetch(limit=100, offset=200)')), 1)

    def test_next_subscript(self):
        self.assertEqual(self.evidence('resp["next_page_token"]')[0]['kind'], 'next-page-access')

    def test_dict_key(self):
        self.assertEqual(self.evidence('{"page": 1, "limit": 2}'), [])

    def test_local(self):
        self.assertEqual(self.evidence('page = 1'), [])

    def test_ordinary_attribute(self):
        self.assertEqual(self.evidence('resp.page'), [])

    def test_for_loop(self):
        self.assertEqual(self.evidence('for page in pages:\n    print(page)'), [])

    def test_loop(self):
        self.assertEqual({e['kind'] for e in self.evidence('while more:\n    fetch(page=1)')}, {'paging-loop', 'pagination-keyword'})

    def test_loop_same_line(self):
        self.assertEqual(len(self.evidence('while more: fetch(page=1)')), 1)

    def test_condition_only(self):
        self.assertEqual(len(self.evidence('while resp["next_page_token"]:\n    pass')), 1)

    def test_dead_code(self):
        self.assertTrue(self.evidence('if False:\n    fetch(page=1)'))

    def test_nonfetch_limit(self):
        self.assertTrue(self.evidence('display(limit=2)'))

    def test_async(self):
        self.assertTrue(self.evidence('async def f(cursor=None):\n    pass'))

    def test_positional_keyword_only(self):
        self.assertTrue(self.evidence('def f(page, /, *, cursor=None):\n    pass'))

    def test_expanded_dict_not_evidence(self):
        self.assertEqual(self.evidence('fetch(**{"page": 1})'), [])

    def test_dedupe_access(self):
        self.assertEqual(len(self.evidence('resp.next; resp.next')), 1)

    def test_two_lines(self):
        self.assertEqual(len(self.evidence('fetch(page=1)\nfetch(page=2)')), 2)


class Tree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
        return file

    def test_no_claim(self):
        self.write('main.py', 'fetch(page=2)')
        self.assertEqual(audit(self.root)['findings'], [])

    def test_no_source_both(self):
        self.write('README.md', 'Results are paginated. Returns all results at once.')
        result = audit(self.root)
        self.assertEqual(len(result['findings']), 2)
        self.assertTrue(all(f['severity'] == 'HIGH' and f['evidence'] == [{'kind': 'no-source'}] for f in result['findings']))

    def test_ignore(self):
        self.write('README.md', 'Returns all results at once.')
        self.write('main.py', 'pass')
        self.write('paging.py', 'fetch(page=1)')
        self.assertEqual(audit(self.root, ['paging.py'])['findings'], [])

    def test_docs_source(self):
        self.write('docs/nested/guide.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        self.assertEqual(len(audit(self.root)['findings']), 1)

    def test_other_markdown_excluded(self):
        self.write('guide.md', 'Results are paginated.')
        self.assertEqual(audit(self.root)['findings'], [])

    def test_examples_excluded(self):
        self.write('README.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        self.write('examples/demo.py', 'fetch(page=1)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_testonly_single(self):
        self.write('README.md', 'Returns all results at once.')
        self.write('main.py', 'pass')
        self.write('tests/test_x.py', 'fetch(page=1)\nfetch(cursor="x")')
        finding = audit(self.root)['findings'][0]
        self.assertEqual(finding['rule'], 'documented-single-shot-claim-false-test-only')
        self.assertEqual(len(finding['evidence']), 2)

    def test_all_production_evidence(self):
        self.write('README.md', 'Returns all results at once.')
        self.write('main.py', 'fetch(page=1)\nfetch(cursor="x")')
        self.assertEqual(len(audit(self.root)['findings'][0]['evidence']), 2)

    def test_env_never_opened(self):
        self.write('README.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        self.write('.env', 'PRIVATE_MARKER_8275')
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env':
                raise AssertionError('environment file opened')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            result = audit(self.root)
        self.assertNotIn('PRIVATE_MARKER_8275', json.dumps(result))

    def test_symlink_file(self):
        self.write('README.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        outside = self.root.parent / (self.root.name + '-external.py')
        outside.write_text('fetch(page=1)')
        self.addCleanup(outside.unlink)
        (self.root / 'linked.py').symlink_to(outside)
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_symlink_directory(self):
        self.write('README.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        self.write('examples/code.py', 'fetch(page=1)')
        (self.root / 'linked').symlink_to(self.root / 'examples', target_is_directory=True)
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_parse_error(self):
        self.write('main.py', 'def broken(')
        with self.assertRaises(ValueError):
            audit(self.root)

    def test_test_filename(self):
        self.write('README.md', 'Results are paginated.')
        self.write('main.py', 'pass')
        self.write('work_test.py', 'fetch(page=1)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')

    def test_repeat_one_family(self):
        self.write('README.md', 'Results are paginated. A paginated listing.')
        self.write('main.py', 'pass')
        self.assertEqual(len(audit(self.root)['findings']), 1)

    def test_self_audit(self):
        report = audit(Path(__file__).resolve().parents[1])
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['verified_claims'], [])


class CLI(unittest.TestCase):
    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(list(args))
        return result, output.getvalue()

    def test_good_paginated(self):
        code, output = self.run_cli(str(FIXTURES / 'good/paginated'), '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['verified_claims'][0]['family'], 'paginated')

    def test_good_single(self):
        code, output = self.run_cli(str(FIXTURES / 'good/single'), '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['verified_claims'][0]['family'], 'single-shot')

    def test_bad_paginated(self):
        code, output = self.run_cli(str(FIXTURES / 'bad/paginated'), '--json')
        self.assertEqual(code, 2)
        findings = json.loads(output)['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'documented-paginated-claim-false')
        self.assertEqual(findings[0]['severity'], 'HIGH')

    def test_bad_single(self):
        code, output = self.run_cli(str(FIXTURES / 'bad/single'), '--json')
        self.assertEqual(code, 2)
        findings = json.loads(output)['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'documented-single-shot-claim-false')
        self.assertTrue(findings[0]['evidence'])

    def test_medium_default(self):
        code, output = self.run_cli(str(FIXTURES / 'testonly'), '--json')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)['findings'][0]['severity'], 'MEDIUM')

    def test_medium_high(self):
        code, output = self.run_cli(str(FIXTURES / 'testonly'), '--fail-on', 'HIGH', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)['findings']), 1)

    def test_json_shape(self):
        _, output = self.run_cli(str(FIXTURES / 'good/single'), '--json')
        self.assertEqual(set(json.loads(output)), {'version', 'findings', 'verified_claims'})

    def test_version(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(['--version'])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), '0.1.0')

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(['--unknown'])
        self.assertEqual(raised.exception.code, 1)

    def test_invalid_path(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(['/nonexistent-pagination-audit-target'])
        self.assertEqual(raised.exception.code, 1)

    def test_verbose(self):
        code, output = self.run_cli(str(FIXTURES / 'bad/single'), '--verbose')
        self.assertEqual(code, 2)
        self.assertIn('main.py', output)
        self.assertIn('README.md', output)


def claim_test(phrase, family):
    def test(self):
        self.assertIn(family, self.families(phrase.upper()))
    return test


for index, phrase in enumerate(PAGINATED):
    setattr(Claims, 'test_paginated_phrase_' + str(index), claim_test(phrase, 'paginated'))
for index, phrase in enumerate(SINGLE):
    setattr(Claims, 'test_single_phrase_' + str(index), claim_test(phrase, 'single-shot'))


def parameter_test(parameter):
    def test(self):
        self.assertEqual(self.evidence('def f(' + parameter + '=None):\n    pass')[0]['kind'], 'pagination-parameter')
    return test


for parameter in sorted(PARAMETERS):
    setattr(Evidence, 'test_parameter_' + parameter, parameter_test(parameter))


def access_test(name):
    def test(self):
        self.assertTrue(self.evidence('resp.' + name))
    return test


for name in ('next_page', 'next_page_token', 'next'):
    setattr(Evidence, 'test_access_' + name, access_test(name))


if __name__ == '__main__':
    unittest.main()
