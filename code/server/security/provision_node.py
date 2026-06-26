#!/usr/bin/env python3
"""
provision_node.py
CLI tool to provision, distribute, and rotate keys to edge nodes.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from server.security.key_manager import KeyManager

def provision(args):
    km = KeyManager()

    if args.rotate:
        print(f"Rotating keys. Grace period: {args.grace_period} days.")
        status = km.rotate_keys(grace_period_days=args.grace_period)
        print(f"New Key ID: {status.new_key_id}")
        print(f"Old Key ID: {status.old_key_id} (Expires: {status.expires_at})")
        if args.save:
            km.save_keys()
            print("Keys saved to configured location.")

    primary = km.primary_key
    if not primary:
        print("No valid primary key available. Please rotate or generate one.", file=sys.stderr)
        sys.exit(1)

    if args.host:
        print(f"Distributing primary key to {args.host}...")
        success = km.distribute_key_ssh(
            host=args.host,
            key=primary,
            remote_path=args.remote_path,
            username=args.username
        )
        if success:
            print(f"Successfully provisioned {args.host}")
        else:
            print(f"Failed to provision {args.host}", file=sys.stderr)
            sys.exit(1)

    if args.verify:
        print(f"Verifying key sync on {args.host}...")
        results = km.verify_sync([args.host], username=args.username)
        if results.get(args.host):
            print("Key is synchronized.")
        else:
            print("Key is NOT synchronized.", file=sys.stderr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpticalRadar Node Provisioning Tool")
    parser.add_argument("--host", type=str, help="Hostname or IP of the node to provision via SSH")
    parser.add_argument("--username", type=str, default="pi", help="SSH username (default: pi)")
    parser.add_argument("--remote-path", type=str, default="/etc/optical_radar/secret.key", help="Remote key path")
    parser.add_argument("--rotate", action="store_true", help="Rotate keys before provisioning")
    parser.add_argument("--grace-period", type=int, default=7, help="Grace period in days for the old key")
    parser.add_argument("--save", action="store_true", help="Save the rotated key back to local storage")
    parser.add_argument("--verify", action="store_true", help="Verify the key synchronization after provisioning")

    args = parser.parse_args()
    provision(args)
