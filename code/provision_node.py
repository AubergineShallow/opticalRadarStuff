#!/usr/bin/env python
"""
provision_node.py
PURPOSE: One-command key provisioning for physical nodes (P5.1).

Thin CLI wrapper around server.security.key_manager.KeyManager so onboarding a
node's shared key, rotating keys, or pushing a key to a node over SSH is a single
command instead of library calls.

Examples:
    # Create a brand-new key file (fails if it already exists unless --force)
    python provision_node.py generate --key-file secrets/shared.key

    # Rotate to a new key, keeping the old one valid for a grace period
    python provision_node.py rotate --key-file secrets/shared.key --grace-days 7

    # Show the active key fingerprint
    python provision_node.py show --key-file secrets/shared.key

    # Push the active key to a node over SSH
    python provision_node.py distribute --key-file secrets/shared.key \\
        --host 10.0.0.21 --user pi
"""

import argparse
import base64
import os
import sys
import time

# Allow running directly from the code/ directory.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from server.security.key_manager import KeyManager, KeyMetadata, key_fingerprint


def _fingerprint(key: bytes) -> str:
    """Short, non-secret identifier for a key (hash-derived, never raw bytes)."""
    return key_fingerprint(key)


def cmd_generate(args) -> int:
    if os.path.exists(args.key_file) and not args.force:
        print(f"Refusing to overwrite existing key file: {args.key_file} "
              f"(use --force or 'rotate')")
        return 1
    km = KeyManager()
    key = km.generate_key()
    km._keys = [KeyMetadata(key=key, created_at=time.time(), comment="provisioned")]
    km.save_keys(args.key_file)
    print(f"Generated new key {_fingerprint(key)} -> {args.key_file}")
    return 0


def cmd_rotate(args) -> int:
    if not os.path.exists(args.key_file):
        print(f"Key file not found: {args.key_file} (run 'generate' first)")
        return 1
    km = KeyManager(key_file=args.key_file)
    status = km.rotate_keys(grace_period_days=args.grace_days)
    km.save_keys(args.key_file)
    print(f"Rotated: new={status.new_key_id} old={status.old_key_id or '(none)'} "
          f"grace={args.grace_days}d")
    return 0


def cmd_show(args) -> int:
    if not os.path.exists(args.key_file):
        print(f"Key file not found: {args.key_file}")
        return 1
    km = KeyManager(key_file=args.key_file)
    primary = km.primary_key
    if not primary:
        print("No active key.")
        return 1
    valid = km.get_valid_keys()
    print(f"Active key: {_fingerprint(primary)}  ({len(valid)} key(s) valid)")
    return 0


def cmd_distribute(args) -> int:
    if not os.path.exists(args.key_file):
        print(f"Key file not found: {args.key_file}")
        return 1
    km = KeyManager(key_file=args.key_file)
    key = km.get_active_key(args.host)
    if not key:
        print("No active key to distribute.")
        return 1
    ok = km.distribute_key_ssh(args.host, key, remote_path=args.remote_path, username=args.user)
    print(f"Distribute to {args.user}@{args.host}: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision shared keys for OpticalRadar nodes.")
    parser.add_argument("--key-file", default="secrets/shared.key",
                        help="Path to the shared key file (default: secrets/shared.key)")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Create a new key file")
    g.add_argument("--force", action="store_true", help="Overwrite an existing key file")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("rotate", help="Rotate to a new key, keeping the old in a grace window")
    r.add_argument("--grace-days", type=int, default=7, help="Days the old key stays valid")
    r.set_defaults(func=cmd_rotate)

    s = sub.add_parser("show", help="Show the active key fingerprint")
    s.set_defaults(func=cmd_show)

    d = sub.add_parser("distribute", help="Push the active key to a node over SSH")
    d.add_argument("--host", required=True, help="Node hostname or IP")
    d.add_argument("--user", default="pi", help="SSH username (default: pi)")
    d.add_argument("--remote-path", default="/etc/optical_radar/secret.key",
                   help="Destination path on the node")
    d.set_defaults(func=cmd_distribute)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
