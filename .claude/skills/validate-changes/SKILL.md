---
name: validate-changes
description: Validate any change to the OpticalRadar codebase — run the system and stress test suites correctly on Windows (UTF-8 gotcha), interpret results, know the suites' blind spots, add new test phases in the established pattern, and apply the definition-of-done checklist before declaring work complete.
---

# Validate Changes (Definition of Done)

## Running the suites

Both suites live in `code\` and MUST run from there. **On Windows, force UTF-8**
or Phase 9's `Simulation → Server` header crashes the run under the cp1252
console codec:

```bash
# Git Bash — functional test suite (~1–2 min)
cd code && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python system_test.py

# Git Bash — adversarial/stress suite (~2–4 min, heavier)
cd code && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python stress_test.py
```
```powershell
# PowerShell
cd code; $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python system_test.py
cd code; $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python stress_test.py
```

**Never run two suites (or a suite plus a live server) concurrently** — they bind
real UDP/WS ports and will produce spurious port-conflict failures.

Success is the summary line — as of 2026-07-03:

```
============================================================
Results: 91 passed, 0 failed (91 total)
============================================================
```

Check counts grow as tests are added; the contract is `0 failed`. One check —
Phase 14's "Enabled broadcaster publish smoke test" — prints `SKIPPED
(foxglove-sdk not installed)` and counts as a pass in the base environment; that
is expected (see `foxglove-addon` skill).

## system_test.py phase map

Two unnumbered math preludes run first (`Phase X: Geo Math`, `Phase X: Quaternion
Math`), then in `main()` execution order:

| Phase | Name | Covers |
|---|---|---|
| 1 | Import Verification | every module imports |
| 2 | Protocol Round-Trip | V3 telemetry/command pack↔unpack, header size, large vector counts |
| 3 | Config | defaults load |
| 4 | Voxel Grid | grid lifecycle, ray→voxel pipeline integration |
| 5 | Calibration | solver runs/converges, noisy rejection, feedback applies offset to server |
| 6 | Tracker | tracker update cycle |
| 7 | Server Initialization | `OpticalRadarServer(headless=True)` constructs with all subsystems |
| 8 | Server Frame Processing | `process_frame()` cycle |
| 9 | Simulation → Server Pipeline | SimNode target detection (no crash; server not driven) |
| 11 | Hierarchical Octree | cubic root, decay/consolidate independence, slab-test octree traversal, subdivision triggers/window, root expansion |
| 10 | WebSocket Rooms + Commands | rooms, command dispatch, CREATE_CLUSTER, networked `_process_packet` |
| 12 | Backend Regression Guards | decay/hot-threshold wiring into Cluster, monotonic uptime, battery absent, native in-place contract, **real `_run_loop` tick**, `server.start()` UDP bind |
| 13 | Security + Metrics (P5) | key rotation/grace window, announce signing, announce-flood bound, provision CLI round-trip, metrics snapshot (replay is in stress S5) |
| 14 | Foxglove Broadcaster | disabled = inert no-ops; enabled publish (skips w/o sdk) |
| 15 | Node Optics + Angular Uncertainty | optics specs, 1-vs-2-camera covariance, Kalman R weighting, covariance threading |
| 16 | LoRa / Meshtastic Suite | pack/unpack round-trips, framer, gateway translation/statefulness, end-to-end into `_process_packet` |
| 17 | Physical Size Estimation | angular_size threading, fusion geometry/gating, EMA, pipeline |

(Phases 10 and 11 print out of numeric order; that is cosmetic.)

## stress_test.py phase map (S1–S14)

Adversarial suite added 2026-07-02 after a fuzz round found real DoS gaps the
happy-path suite missed. Groups: S1 protocol fuzzing (random/truncated datagrams
must not crash parse), S2 adversarial packets (boundary values, NaN/Inf, zero
quaternions), S3 registry floods (announce/node caps), S4 WebSocket abuse
(non-object JSON frames, CREATE_CLUSTER/ASSIGN_NODE floods, SUBSCRIBE room leak),
S5 security attacks (replay, tamper), S6 tracking & octree limits (track cap,
flood/prune recovery), S7 geodesy edge cases, S8 throughput (asserts the octree
leaf cap), S9 config robustness (malformed YAML/env), S10 calibration solver,
S11 LoRa gateway (orphan updates, queue bound, serial framing; framer noise/
garbage is in S1), S12 broadcast serialization, S13 node health transitions, S14 numeric
hardening. Its summary line has the same `N passed, 0 failed` contract.

**Known failing check (as of 2026-07-03)** — delete this note once fixed: S8's
"Sustained 8-camera realistic ingest holds >200 pkts/s; octree under cap" fails
reproducibly at ~99 pkts/s (suite = 48/49). Suspected cause: the physical-size
estimator (landed 2026-07-03) does O(detections × rays) pure-Python work per frame
in `server_main.py::_build_detections` → `_estimate_physical_size`. Treat S8 as a
pre-existing failure; treat ANY OTHER failure as caused by your change.

## Known blind spots — read before trusting a green run

`system_test.py` verified "all pass" while FOUR ship-blocking bugs existed. Its
structural biases (still true today):

1. **`headless=True` everywhere** — the visualizer path is never exercised.
2. **`server.authenticator = None`** is set in several networked tests — auth
   integration is only covered where Phase 13 tests it explicitly.
3. **Fake configs**: some tests build minimal `FakeConfig` classes (one has a
   `voxel_grid` attr the real `Config` lacks). Passing a fake ≠ real config wiring
   works; Phase 12 exists because of this.
4. Historically **nothing called `server.start()`**, so bugs living only in
   `start()` (UDP bind crash BUG-007, dead metrics exporter) were invisible. A
   Phase 12 regression check now covers `start()`/bind, but the bias remains:
   prefer tests that exercise the REAL entry path, not just internal methods.
5. Timing-based checks can race on a loaded machine; a one-off failure in a
   timing check deserves a solo re-run before you chase it.

When you fix a bug the suite missed, ALSO add a check that would have caught it
(that's how Phase 12 grew).

## Adding a test phase (established pattern)

Both suites use the same skeleton — a global `check(name, fn)` that counts
PASS/FAIL (a check passes when `fn` returns None or truthy; raises/falsy = FAIL):

```python
def test_my_feature():
    """Phase 18: What it covers."""
    print("\n=== Phase 18: My Feature ===")
    from server.server_main import OpticalRadarServer

    def test_specific_behavior():
        server = OpticalRadarServer(headless=True)
        server.authenticator = None  # only if the test isn't about auth
        # ... drive server._process_packet(...) / server.process_frame() ...
        assert something, "message shown on failure"

    check("Readable one-line contract of the behavior", test_specific_behavior)
```

Then add `test_my_feature()` to `main()` (keep execution order = phase order).
Conventions: name checks as behavioral contracts ("Server start() binds the UDP
socket"), construct servers `headless=True`, use `_process_packet`/`process_frame`
for pipeline tests, and use ephemeral ports if you must bind.

## Non-Python validation

- **UI (NEW-UI-V2)**: no node_modules → no tsc. Minimum bar is a per-file esbuild
  syntax check; real bar is the browser runtime preview. Both in `ui-development`.
  Syntax check (from `NEW-UI-V2\`):
  `npx esbuild --log-level=warning <file>.tsx > /dev/null` (loader inferred from
  extension; adding `--loader=tsx` with a file argument is an error)
- **Protocol changes**: run Phase 16 (in system_test) AND the C++ host-compile
  byte cross-check of `code/esp32/firmware/include/lora_protocol.h` — see
  `wire-protocols` skill.
- **Android / ESP32 firmware**: not buildable here — validation is code review
  against the conventions in `edge-nodes` plus keeping the Python side of any
  shared contract tested.

## Definition of done

A change is done when ALL of the following hold:

- [ ] `system_test.py`: `0 failed` (UTF-8 env, from `code\`).
- [ ] `stress_test.py`: no failures beyond the documented known-failing check(s)
      above — mandatory for changes touching ingest, network, security, octree,
      tracking, LoRa, or any cap/bound; recommended always.
- [ ] New behavior has a new check in the appropriate phase (or a new phase).
- [ ] Bug fixes include a regression check that fails without the fix.
- [ ] UI touched → esbuild syntax check clean; store/layer/WS changes runtime-
      verified in the browser preview (`ui-development`).
- [ ] Wire format touched → both language sides updated + cross-checked
      (`wire-protocols`).
- [ ] Any new unbounded collection/loop got a cap with a config default
      (`quality-standards`).
- [ ] No suite was run concurrently with another port-binding process.
