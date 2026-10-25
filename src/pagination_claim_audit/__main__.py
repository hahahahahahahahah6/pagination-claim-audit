"""Command line entry point."""
import argparse
import json
import sys
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='pagination-claim-audit', description='Offline audit of documented pagination claims against Python source.')
    parser.add_argument('path', nargs='?', default='.', help='tree to audit (default: current directory)')
    parser.add_argument('--json', action='store_true', help='emit a JSON report')
    parser.add_argument('--verbose', action='store_true', help='show claim and evidence locations')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB', help='ignore a relative path glob; repeatable')
    parser.add_argument('--fail-on', choices=('MEDIUM', 'HIGH'), default='MEDIUM')
    parser.add_argument('--version', action='version', version='0.1.0')
    args = parser.parse_args(argv)
    try:
        report = audit(args.path, args.ignore)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in report['findings'])
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('FAIL' if failed else 'PASS')
        for finding in report['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            if args.verbose:
                for claim in finding['claims']:
                    print('  {path}:{line}: {text}'.format(**claim))
                for evidence in finding['evidence']:
                    print('  ' + json.dumps(evidence, sort_keys=True))
        if args.verbose:
            for claim in report['verified_claims']:
                print('verified: ' + claim['family'])
                for evidence in claim['evidence']:
                    print('  ' + json.dumps(evidence, sort_keys=True))
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
