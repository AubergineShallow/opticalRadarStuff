---
name: security-provisioning
description: Configure and debug packet authentication — HMAC signing, key management and rotation, replay rejection, the server's fail-fast startup check, node-side key resolution, the provision_node.py CLI, and how to run development with security off. Also covers what is NOT authenticated (LoRa, WebSocket).
---

# Security & Provisioning

Shared-key HMAC-SHA256 over UDP packets. **Off by default** (`security.enabled:
false`): edge nodes ship unsigned, and a default-on once silently dropped 100% of
real telemetry (BUG-008). Turn it on only after provisioning the same key on
server AND every node.

## What is (and isn't) authenticated

| Path | Authenticated? |
|---|---|
| UDP telemetry (0x01) | HMAC verified when security on |
| UDP announce (0x04) | HMAC verified when security on — announces are signable (`AnnouncePacket.get_data_for_signing`); an unsigned-announce bypass once allowed node-registration poisoning |
| Ground truth (0x03) | same object-level gate |
| LoRa gateway packets | **NO HMAC by design** (no airtime; physically-scoped link) — processed with `trusted=True` in `server_main._run_loop`. RF injection is out of scope of this model. |
| WebSocket commands (UI) | **Unauthenticated** — treated as untrusted input; guarded by caps/validation instead (`quality-standards`) |

Signature on the wire: optional trailing 32 bytes; auto-detected by length (no
flag byte) — see `wire-protocols`.

## Server side

- `server/security/key_manager.py::KeyManager` owns keys: loads from
  `security.key_file` (default `secrets/shared.key`), supports multiple
  concurrently-valid keys with expiry (rotation grace), key ids =
  `key_fingerprint` (first 8 hex of SHA-256). `distribute_key_ssh` pushes a key
  to a node over SSH.
- `server/security/authenticator.py::Authenticator` is a thin consumer:
  `verify_signed_packet(packet)` = (1) HMAC-SHA256 over
  `packet.get_data_for_signing()` checked against every valid key
  (constant-time compare), (2) freshness: |now − packet.timestamp| ≤
  `max_timestamp_drift` (config `security.auth_timeout_sec`, default 30 s),
  (3) **exact-replay rejection**: byte-identical signatures seen within the
  window are refused (bounded FIFO of 8192 — a captured datagram re-sent inside
  the drift window used to verify fine).
- **Fail-fast startup** (`server_main.__init__`): if security is enabled and
  `KeyManager.get_valid_keys()` is empty, a
  `RuntimeError: security.enabled is set but no keys could be loaded (key_file=...).
  Provision one with 'python provision_node.py generate'.`
  is raised — note it is caught by the enclosing try/except, which logs it
  (`Failed to initialize authenticator: ...`) and re-raises
  `RuntimeError("Authentication initialization failed")`; the provision hint is
  in the **error log**, not the final traceback. This is deliberate: an Authenticator with zero keys rejects every packet, so
  the server would start "successfully" and silently drop all traffic. Never
  soften this into a warning.
- Enable/disable: config `security.enabled`, or env `OR_SECURITY_ENABLED` which
  **forces either way** (`0/false/no/off` vs `1/true/yes/on`) — read directly in
  `server_main`, wins over config.

## Node side (signing)

`rpi/rpi_node.py::_load_signer` resolution order:

1. `--key-file <path>` — missing/invalid file **RAISES** (an operator who asked
   for signing must not silently run unsigned);
2. env `OPTICAL_RADAR_SECRET_KEY`;
3. `/etc/optical_radar/secret.key` (what `provision_node.py distribute` writes),
   then `secrets/shared.key` — silently skipped when absent, so unprovisioned
   nodes run unsigned out of the box.

A node with a key signs every packet; replays of an identical signature inside
the drift window are rejected server-side.

## provision_node.py CLI (run from `code\`)

Global flag `--key-file` (default `secrets/shared.key`). Subcommands:

- `generate [--force]` — create a new key file. Output pattern:
  `Generated new key <8-hex-id> -> <path>`.
- `show` — active key fingerprint + count of valid keys.
- `rotate [--grace-days 7]` — new key becomes primary; old stays valid through
  the grace window (nodes can be updated one at a time without an outage).
- `distribute --host <ip> [--user pi] [--remote-path /etc/optical_radar/secret.key]`
  — push the active key to a node over SSH.

Standard bring-up:

```bash
cd code
python provision_node.py generate
python provision_node.py distribute --host 192.168.1.42        # per node
OR_SECURITY_ENABLED=true python run_server.py --headless
python rpi/rpi_node.py --mock --key-file secrets/shared.key    # signed node
```

## Development without security

Do nothing — the default is off. To force off despite a config file:
`OR_SECURITY_ENABLED=false`. Tests that aren't about auth construct the server
then set `server.authenticator = None` (the established pattern in
system_test.py) — acceptable in tests, never in production code paths.

## Debugging auth failures

| Symptom | Cause | Fix |
|---|---|---|
| Server exits at startup (`Authentication initialization failed`; provision hint in the error log) | security on, no key file | `generate`, or `OR_SECURITY_ENABLED=false` |
| Log: `Signature verification failed for packet from ...` | node unsigned or wrong key | provision node; compare `show` fingerprints both ends |
| Same, only for some packets | replay filter (duplicate datagrams) or clock drift > 30 s | check node clock/NTP; drift window `security.auth_timeout_sec` |
| Node refuses to start with `--key-file` | missing/invalid file | deliberate — fix the path, don't remove the raise |
| Verified in tests but dropped live | keys differ between `secrets/shared.key` and what the node loaded via env | eliminate env overrides, re-check resolution order above |

Coverage: system_test Phase 13 (key rotation, announce signing + wire
round-trip, announce-flood registry bound, provision CLI round-trip) and stress
S5 (replay rejection, tamper/stale packets, replay-filter memory bound).

## Related skills

`wire-protocols` (signature bytes), `edge-nodes` (node key loading),
`lora-meshtastic` (the unauthenticated-by-design path), `quality-standards`
(fail-fast philosophy).
