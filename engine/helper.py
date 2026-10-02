"""Bundled entrypoint; the frozen executable dispatches roles, never Python scripts."""
from __future__ import annotations
import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys


def configure_bundle() -> None:
    if getattr(sys, 'frozen', False):
        # Contents/Helpers/DiscPorterHelper/disc-porter-helper
        contents = Path(sys.executable).resolve().parents[2]
        tools = contents / 'Tools'
        os.environ['DISC_PORTER_BUNDLE_TOOLS'] = str(tools)
        os.environ['DISC_PORTER_TOOLS_DIR'] = str(tools)
        os.environ['DISC_PORTER_HELPER_EXECUTABLE'] = str(Path(sys.executable).resolve())
        # The privately extracted PSF interpreter has no system-install certificate
        # setup. Use the bundled trust roots without weakening certificate checks.
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
        # PATH for external MakeMKV subprocess helpers only; tools are also discovered explicitly.
        os.environ['PATH'] = str(tools) + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin')




def main() -> int:
    configure_bundle()
    parser = argparse.ArgumentParser(prog='disc-porter-helper')
    sub = parser.add_subparsers(dest='role', required=True)
    serve = sub.add_parser('serve', help='Start the authenticated local engine')
    serve.add_argument('--state-dir', required=True)
    sub.add_parser('mcp', help='Run the packaged MCP stdio control plane')
    ssl_check = sub.add_parser('selftest-ssl', help='Check bundled TLS trust and verification without a network request')
    ssl_check.add_argument('--expected-cert-file')
    supervisor = sub.add_parser('supervise', help='Supervise an owned tool until completion or parent exit')
    supervisor.add_argument('parent_pid', type=int)
    supervisor.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.role == 'selftest-ssl':
        import ssl
        context = ssl.create_default_context()
        result = {'ca_count': len(context.get_ca_certs()),
                  'certificate_verification_required': context.verify_mode == ssl.CERT_REQUIRED,
                  'hostname_verification_enabled': context.check_hostname,
                  'expected_override_preserved': args.expected_cert_file is None or os.environ.get('SSL_CERT_FILE') == args.expected_cert_file}
        print(json.dumps(result, separators=(',', ':')))
        return 0 if result['ca_count'] > 0 and all(value for key, value in result.items() if key != 'ca_count') else 1
    if args.role == 'serve':
        from engine.server import serve as serve_engine
        serve_engine(args.state_dir)
        return 0
    if args.role == 'supervise':
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        from engine.runner import supervise
        return supervise(args.parent_pid, command)
    from disc_porter_control.server import main as mcp_main
    result = mcp_main()
    if inspect.isawaitable(result):
        asyncio.run(result)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
