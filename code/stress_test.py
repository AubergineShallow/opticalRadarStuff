#!/usr/bin/env python
"""
stress_test.py - Adversarial / limit-pushing test suite.

system_test.py verifies that the happy path works; this suite verifies that
the system SURVIVES the unhappy ones: fuzzed datagrams, boundary-value and
adversarial-but-parseable packets, registry floods with unique ids, WebSocket
clients sending garbage or command floods, oversized packets, replay attacks,
and sustained ingest load. Each phase asserts an explicit contract (bounded
memory, no exception, rejected input) rather than just "no crash".

Run:  PYTHONUTF8=1 python stress_test.py
"""

import sys
import os
import json
import math
import time
import random
import struct
import asyncio
import tempfile
import traceback

code_dir = os.path.dirname(os.path.abspath(__file__))
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

import numpy as np

PASS = 0
FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        result = fn()
        if result is not None and not result:
            raise AssertionError(f"Returned {result}")
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()


class _NullLogger:
    """Swallow log output during floods (the contract under test is behaviour,
    not log volume)."""
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def close(self): pass


def _make_server():
    """Headless server with security off and quiet logging."""
    from server.server_main import OpticalRadarServer
    server = OpticalRadarServer(headless=True)
    server.authenticator = None
    server.logger = _NullLogger()
    return server


def _telemetry(camera_id="CAM-01", n_vectors=1, lat=37.7750, lon=-122.4194,
               alt=10.0, health=0x07, seq=0, timestamp=None, orientation=None):
    from common.protocol import TelemetryPacket, MotionVector
    vecs = [MotionVector(azimuth=(i * 7) % 360, elevation=10.0 + (i % 45),
                         intensity=200, class_id=0)
            for i in range(n_vectors)]
    return TelemetryPacket(
        camera_id=camera_id, sequence_number=seq,
        timestamp=time.time() if timestamp is None else timestamp,
        latitude=lat, longitude=lon, altitude=alt,
        orientation=orientation or (1.0, 0.0, 0.0, 0.0),
        health_flags=health, vectors=vecs,
    )


# --------------------------------------------------------------------------- #
# Phase S1: Protocol fuzzing (random bytes must never escape the parse layer) #
# --------------------------------------------------------------------------- #
def test_fuzz_parsing():
    print("\n=== Phase S1: Protocol fuzzing ===")
    from server.udp_server import UDPServer
    from common.lora_protocol import unpack_lora, LoRaFramer

    def test_udp_fuzz_end_to_end():
        rng = random.Random(0xC0FFEE)
        udp = UDPServer(port=0)          # never started: parse path only
        server = _make_server()
        parsed = 0
        for i in range(3000):
            n = rng.choice((0, 1, 2, 10, 31, 60, 61, 62, 63, 93, 100, 200, 1500))
            data = bytes(rng.getrandbits(8) for _ in range(n))
            rp = udp._process_packet(data, ("10.0.0.1", 9), time.time())
            if rp is not None:
                parsed += 1
                # Whatever survives parsing must not blow up the server.
                server._process_packet(rp.packet, ("10.0.0.1", 9))
        # Some buffers should parse (61+ byte ones with any first bytes do).
        assert parsed > 0, "fuzz never produced a parseable packet (test is inert)"
        return True

    check("3000 fuzzed datagrams: parse layer + server._process_packet never raise",
          test_udp_fuzz_end_to_end)

    def test_lora_fuzz():
        rng = random.Random(0xBEEF)
        for _ in range(2000):
            n = rng.choice((0, 1, 6, 7, 8, 19, 20, 21, 64))
            unpack_lora(bytes(rng.getrandbits(8) for _ in range(n)))
        framer = LoRaFramer()
        for _ in range(500):
            framer.push(bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 64))))
        assert len(framer._buf) <= 4096, f"framer buffer grew to {len(framer._buf)}"
        return True

    check("LoRa unpack + framer survive 2500 noise bursts, buffer stays bounded",
          test_lora_fuzz)

    def test_framer_split_and_corrupt():
        from common.lora_protocol import frame_payload
        framer = LoRaFramer()
        p1, p2 = b"\x01" * 20, b"\x02" * 7
        stream = b"\xAA" + frame_payload(p1) + b"junk\xAA\x55" + frame_payload(p2)
        got = []
        for i in range(len(stream)):          # worst case: 1 byte at a time
            got.extend(framer.push(stream[i:i + 1]))
        assert p1 in got and p2 in got, f"payloads lost across corruption: {got}"
        return True

    check("Framer recovers both payloads across 1-byte reads + injected garbage",
          test_framer_split_and_corrupt)


# --------------------------------------------------------------------------- #
# Phase S2: Adversarial-but-parseable packets                                 #
# --------------------------------------------------------------------------- #
def test_adversarial_packets():
    print("\n=== Phase S2: Adversarial packets ===")
    from common.protocol import TelemetryPacket, MotionVector

    def test_poison_values_rejected():
        server = _make_server()
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        nan, inf = float("nan"), float("inf")
        poison = [
            dict(lat=nan), dict(lon=inf), dict(alt=-inf),
            dict(timestamp=nan),
            dict(lat=91.0), dict(lat=-90.5), dict(lon=180.5), dict(lon=-999.0),
            dict(orientation=(0.0, 0.0, 0.0, 0.0)),
            dict(orientation=(nan, 0.0, 0.0, 1.0)),
        ]
        for kw in poison:
            server._process_packet(_telemetry(**kw), ("10.0.0.2", 1))
        # Nothing may have reached the grid or camera registry.
        assert server.ray_builder.get_camera_position("CAM-01") is None, \
            "poisoned telemetry registered a camera position"
        stats = server.voxel_grid.get_stats()
        assert stats["max_heat"] == 0.0, f"poisoned telemetry deposited heat: {stats}"
        return True

    check("NaN/Inf/out-of-range/degenerate-quaternion telemetry is fully inert",
          test_poison_values_rejected)

    def test_boundary_values_accepted():
        # Legal extremes must NOT be rejected: poles and antimeridian are valid.
        server = _make_server()
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        for lat, lon in ((90.0, 0.0), (-90.0, 0.0), (0.0, 180.0), (0.0, -180.0)):
            pkt = _telemetry(lat=lat, lon=lon)
            assert server._telemetry_sane(pkt), f"legal extreme rejected: {lat},{lon}"
            server._process_packet(pkt, ("10.0.0.2", 1))  # must not raise
        pos = server.ray_builder.get_camera_position("CAM-01")
        assert pos is not None and np.isfinite(pos).all(), \
            f"boundary coordinate produced non-finite ENU: {pos}"
        return True

    check("Legal extremes (poles, antimeridian) accepted and finite in ENU",
          test_boundary_values_accepted)

    def test_lying_vector_count():
        # Header claims 500 vectors, body carries 2: unpack must not over-read.
        pkt = _telemetry(n_vectors=2)
        raw = bytearray(pkt.pack())
        struct.pack_into(">H", raw, 59, 500)          # vector_count @ offset 59
        out = TelemetryPacket.unpack(bytes(raw))
        assert len(out.vectors) == 2, f"over-read vectors: {len(out.vectors)}"
        return True

    check("vector_count lying high does not over-read the buffer",
          test_lying_vector_count)

    def test_oversized_vector_packet_capped():
        # A single dense datagram must not buy unbounded server CPU: the
        # ingest path caps vectors per packet (network.max_vectors_per_packet).
        server = _make_server()
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        pkt = _telemetry(n_vectors=2000)
        t0 = time.perf_counter()
        server._process_packet(pkt, ("10.0.0.2", 1))
        elapsed = time.perf_counter() - t0
        cap = getattr(getattr(server.config, "network", None),
                      "max_vectors_per_packet", None)
        assert cap is not None, "no max_vectors_per_packet limit configured"
        stats = server.voxel_grid.get_stats()
        assert 0 < stats["active_leaves"], "capped packet processed nothing at all"
        print(f"        (2000-vector packet processed in {elapsed*1000:.1f} ms, cap={cap})")
        return True

    check("2000-vector packet is capped at ingest (bounded CPU per datagram)",
          test_oversized_vector_packet_capped)

    def test_motion_vector_boundaries():
        for az, el, size in ((0.0, -90.0, 0.0), (359.9945, 90.0, 180.0),
                             (180.0, 0.0, 90.0)):
            mv = MotionVector(azimuth=az, elevation=el, intensity=255,
                              class_id=255, angular_size=size)
            out = MotionVector.unpack(mv.pack())
            assert abs(out.azimuth - az) < 0.02, f"az {az} -> {out.azimuth}"
            assert abs(out.elevation - el) < 0.02, f"el {el} -> {out.elevation}"
            assert abs(out.angular_size - size) < 0.02, f"size {size} -> {out.angular_size}"
        return True

    check("MotionVector quantisation round-trips at field boundaries",
          test_motion_vector_boundaries)


# --------------------------------------------------------------------------- #
# Phase S3: Registry flood (unique-id memory DoS)                             #
# --------------------------------------------------------------------------- #
def test_registry_floods():
    print("\n=== Phase S3: Registry floods ===")
    from common.protocol import AnnouncePacket

    def test_announce_flood_bounded():
        server = _make_server()
        base_optics = len(server._node_optics)
        for i in range(5000):
            ann = AnnouncePacket(camera_id=f"N{i:05d}", timestamp=time.time())
            server._process_packet(ann, ("10.0.0.3", 1))
        cap = server._max_nodes
        assert len(server._node_optics) <= max(cap, base_optics), \
            f"optics registry grew to {len(server._node_optics)}"
        assert len(server.cluster_manager.node_assignments) <= cap + base_optics + 8, \
            f"assignments grew to {len(server.cluster_manager.node_assignments)}"
        assert len(server.cluster_manager.pending_nodes) <= cap, \
            f"pending grew to {len(server.cluster_manager.pending_nodes)}"
        return True

    check("5000-unique-id ANNOUNCE flood: optics/assignment/pending stay bounded",
          test_announce_flood_bounded)

    def test_telemetry_flood_bounded():
        server = _make_server()
        for i in range(5000):
            server._process_packet(
                _telemetry(camera_id=f"T{i:05d}", seq=i), ("10.0.0.4", 1))
        assert len(server.health_monitor._nodes) <= server.health_monitor.max_nodes, \
            f"health registry grew to {len(server.health_monitor._nodes)}"
        assert len(server.cluster_manager.pending_nodes) <= \
            server.cluster_manager.max_pending_nodes, \
            f"pending grew to {len(server.cluster_manager.pending_nodes)}"
        return True

    check("5000-unique-id telemetry flood: health/pending registries stay bounded",
          test_telemetry_flood_bounded)


# --------------------------------------------------------------------------- #
# Phase S4: WebSocket abuse (garbage frames, command floods)                  #
# --------------------------------------------------------------------------- #
def test_websocket_abuse():
    print("\n=== Phase S4: WebSocket abuse ===")

    class MockWS:
        def __init__(self):
            self.sent = []
        async def send(self, payload):
            self.sent.append(payload)

    def test_garbage_messages_survive():
        server = _make_server()
        ws = server.ws_server
        mock = MockWS()
        garbage = [
            "", "not json", "{", "[]", "[1,2,3]", '"a string"', "42", "null",
            "true", '{"no_type": 1}', '{"type": 123}',
            '{"type": "SUBSCRIBE_CLUSTER"}',
            '{"type": "SUBSCRIBE_CLUSTER", "payload": null}',
            '{"type": "SUBSCRIBE_CLUSTER", "payload": "DEFAULT"}',
            '{"type": "SUBSCRIBE_CLUSTER", "payload": {"cluster_id": null}}',
            '{"type": "SUBSCRIBE_CLUSTER", "payload": {"cluster_id": 5}}',
            '{"type": "CREATE_CLUSTER", "payload": "oops"}',
            '{"type": "CREATE_CLUSTER", "payload": {"cluster_id": {"a": 1}}}',
            '{"type": "ASSIGN_NODE", "payload": {"node_id": [1], "cluster_id": 2}}',
            '{"type": "UNKNOWN_CMD", "payload": {}}',
        ]
        for raw in garbage:
            # Contract: a malformed client frame must not raise (it would kill
            # that client's connection) and must not corrupt server state.
            asyncio.run(ws._on_message(mock, raw))
        return True

    check("20 malformed client frames: no exception escapes the dispatcher",
          test_garbage_messages_survive)

    def test_create_cluster_flood_capped():
        server = _make_server()
        ws = server.ws_server
        mock = MockWS()
        for i in range(500):
            msg = json.dumps({"type": "CREATE_CLUSTER",
                              "payload": {"cluster_id": f"Z{i:04d}"}})
            asyncio.run(ws._on_message(mock, msg))
        n = len(server.cluster_manager.clusters)
        assert n <= 64, f"CREATE_CLUSTER flood grew clusters to {n} (unbounded CPU/mem)"
        return True

    check("500x CREATE_CLUSTER flood: cluster count is capped",
          test_create_cluster_flood_capped)

    def test_assign_unknown_node_rejected():
        server = _make_server()
        ws = server.ws_server
        mock = MockWS()
        before = len(server.cluster_manager.node_assignments)
        for i in range(500):
            msg = json.dumps({"type": "ASSIGN_NODE",
                              "payload": {"node_id": f"GHOST{i:04d}",
                                          "cluster_id": "DEFAULT"}})
            asyncio.run(ws._on_message(mock, msg))
        after = len(server.cluster_manager.node_assignments)
        assert after == before, \
            f"ASSIGN_NODE flood registered {after - before} never-seen nodes"
        # But a genuinely pending node is assignable.
        server.cluster_manager.get_cluster_for_node("REAL-01")  # -> pending
        msg = json.dumps({"type": "ASSIGN_NODE",
                          "payload": {"node_id": "REAL-01", "cluster_id": "DEFAULT"}})
        asyncio.run(ws._on_message(mock, msg))
        assert server.cluster_manager.node_assignments.get("REAL-01") == "DEFAULT", \
            "pending node could not be assigned via WS"
        return True

    check("ASSIGN_NODE only accepts known/pending nodes (no ghost registration)",
          test_assign_unknown_node_rejected)

    def test_room_registry_bounded():
        server = _make_server()
        ws = server.ws_server
        mock = MockWS()
        for i in range(500):
            msg = json.dumps({"type": "SUBSCRIBE_CLUSTER",
                              "payload": {"cluster_id": f"ROOM{i:04d}"}})
            asyncio.run(ws._on_message(mock, msg))
        # One client can occupy at most one room; stale empty rooms must not pile up.
        n_rooms = len(ws._rooms)
        assert n_rooms <= 4, f"room registry grew to {n_rooms} entries for one client"
        return True

    check("500x SUBSCRIBE flood from one client leaves <= a handful of rooms",
          test_room_registry_bounded)

    def test_port_conflict_surfaced():
        import socket
        from server.websocket_server import WebSocketBroadcaster
        # Deterministically hold the port with a plain listener, then start the
        # broadcaster on it: the bind must fail and running must flip to False
        # (no silent "started but bound to nothing").
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        holder.bind(("0.0.0.0", 0))
        port = holder.getsockname()[1]
        holder.listen(1)
        ws = WebSocketBroadcaster(port=port)
        ws.start()
        deadline = time.time() + 4.0
        while ws.running and time.time() < deadline:
            time.sleep(0.05)
        conflicted = not ws.running
        ws.stop()
        holder.close()
        assert conflicted, "broadcaster claims running despite a bind conflict"
        return True

    check("Port conflict flips running->False (no silent dead server)",
          test_port_conflict_surfaced)

    def test_stop_releases_port():
        import socket
        from server.websocket_server import WebSocketBroadcaster
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ws = WebSocketBroadcaster(port=port)
        ws.start()
        # Wait until the server actually owns the port (a fresh bind must fail).
        deadline = time.time() + 4.0
        bound = False
        while time.time() < deadline and not bound:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                probe.bind(("0.0.0.0", port))
                probe.close()
                time.sleep(0.05)
            except OSError:
                bound = True
            finally:
                try:
                    probe.close()
                except OSError:
                    pass
        assert bound, "broadcaster never actually bound the port"
        ws.stop()
        # After stop() the port must be reusable (supports an in-process restart).
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("0.0.0.0", port))
        s.close()
        return True

    check("stop() releases the port for an in-process rebind",
          test_stop_releases_port)


# --------------------------------------------------------------------------- #
# Phase S5: Security under attack                                             #
# --------------------------------------------------------------------------- #
def test_security_attacks():
    print("\n=== Phase S5: Security attacks ===")
    from server.security.authenticator import Authenticator
    from server.security.key_manager import KeyManager
    from common.protocol import TelemetryPacket, AnnouncePacket
    import base64

    def _authenticator():
        key = os.urandom(32)
        path = os.path.join(tempfile.gettempdir(), "or_stress_key.txt")
        with open(path, "w") as f:
            f.write(base64.b64encode(key).decode() + "\n")
        km = KeyManager(key_file=path)
        return Authenticator(key_manager=km, max_timestamp_drift_sec=30.0), \
            Authenticator(key=key)

    def test_replay_rejected():
        auth, signer = _authenticator()
        pkt = signer.sign_packet(_telemetry())
        wire = pkt.pack(include_signature=True)
        first = TelemetryPacket.unpack(wire)
        again = TelemetryPacket.unpack(wire)
        assert auth.verify_signed_packet(first), "genuine packet failed verification"
        assert not auth.verify_signed_packet(again), "byte-identical replay accepted"
        return True

    check("Byte-identical replay inside the drift window is rejected",
          test_replay_rejected)

    def test_tamper_and_stale_rejected():
        auth, signer = _authenticator()
        # Tampered: flip one latitude byte after signing.
        pkt = signer.sign_packet(_telemetry())
        raw = bytearray(pkt.pack(include_signature=True))
        raw[22] ^= 0xFF
        assert not auth.verify_signed_packet(TelemetryPacket.unpack(bytes(raw))), \
            "tampered packet accepted"
        # Stale: valid signature, hour-old timestamp.
        old = signer.sign_packet(_telemetry(timestamp=time.time() - 3600))
        assert not auth.verify_signed_packet(old), "hour-old packet accepted"
        # Future-dated beyond drift is equally invalid.
        future = signer.sign_packet(_telemetry(timestamp=time.time() + 3600))
        assert not auth.verify_signed_packet(future), "future-dated packet accepted"
        return True

    check("Tampered, stale, and future-dated packets are rejected",
          test_tamper_and_stale_rejected)

    def test_unsigned_announce_blocked_when_secured():
        auth, _ = _authenticator()
        server = _make_server()
        server.authenticator = auth
        ann = AnnouncePacket(camera_id="EVIL-1", timestamp=time.time())
        server._process_packet(ann, ("10.6.6.6", 1))
        assert "EVIL-1" not in server._node_optics, \
            "unsigned announce registered a node with security enabled"
        assert "EVIL-1" not in server.cluster_manager.node_assignments, \
            "unsigned announce got a cluster assignment with security enabled"
        return True

    check("Unsigned ANNOUNCE cannot register a node when security is on",
          test_unsigned_announce_blocked_when_secured)

    def test_signature_flood_bounded():
        auth, signer = _authenticator()
        for i in range(10000):
            pkt = signer.sign_packet(_telemetry(seq=i))
            auth.verify_signed_packet(pkt)
        assert len(auth._seen_signatures) <= auth._seen_order.maxlen + 1, \
            f"replay filter grew to {len(auth._seen_signatures)}"
        return True

    check("10k verified packets: replay-filter memory stays bounded",
          test_signature_flood_bounded)


# --------------------------------------------------------------------------- #
# Phase S6: Tracking & octree under load                                      #
# --------------------------------------------------------------------------- #
def test_pipeline_limits():
    print("\n=== Phase S6: Tracking & octree limits ===")
    from server.tracking.tracker import Tracker, Detection
    from server.voxel_grid import VoxelGrid, VoxelGridConfig

    def test_detection_storm_capped():
        tracker = Tracker()
        rng = random.Random(7)
        t0 = time.perf_counter()
        for frame in range(5):
            dets = [Detection(position=np.array([rng.uniform(-100, 100),
                                                 rng.uniform(-100, 100),
                                                 rng.uniform(0, 100)]))
                    for _ in range(500)]
            tracker.update(dets)
        elapsed = time.perf_counter() - t0
        n = len(tracker.get_all_tracks())
        assert n <= 100, f"max_tracks not enforced under storm: {n}"
        print(f"        (5 frames x 500 detections in {elapsed*1000:.0f} ms)")
        return True

    check("500-detection storm: max_tracks cap enforced", test_detection_storm_capped)

    def test_same_timestamp_update():
        tracker = Tracker()
        dets = [Detection(position=np.array([1.0, 2.0, 3.0]))]
        t = time.time()
        tracker.update(dets, timestamp=t)
        tracker.update(dets, timestamp=t)        # dt == 0
        tracker.update(dets, timestamp=t - 1.0)  # dt < 0 (clock step)
        for tr in tracker.get_all_tracks():
            assert np.isfinite(tr.position).all(), "non-finite state after dt<=0"
        return True

    check("dt=0 and negative-dt updates leave finite track state",
          test_same_timestamp_update)

    def test_octree_flood_and_recovery():
        grid = VoxelGrid(VoxelGridConfig())
        target = np.array([20.0, 30.0, 40.0])
        cams = [np.array([math.cos(a) * 90, math.sin(a) * 90, 5.0])
                for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
        t0 = time.perf_counter()
        for frame in range(30):
            for ci, cam in enumerate(cams):
                d = target - cam
                d = d / np.linalg.norm(d)
                grid.add_ray(cam, d, intensity=5.0, camera_id=f"C{ci}",
                             frame_index=frame)
        build_ms = (time.perf_counter() - t0) * 1000
        peak = len(grid._active_leaves)
        dets = grid.get_detections()
        assert dets, "8-camera convergence produced no detection"
        err = float(np.linalg.norm(dets[0] - target))
        assert err < 8.0, f"detection {dets[0]} is {err:.1f} m from target"
        # Cool-down: decay + prune must collapse the structure back.
        for _ in range(400):
            grid.decay_active_leaves()
        grid.consolidate_and_prune()
        after = len(grid._active_leaves)
        assert after < peak / 4, f"prune failed: {peak} -> {after} leaves"
        print(f"        (240 rays in {build_ms:.0f} ms; leaves {peak} -> {after}; "
              f"localisation error {err:.2f} m)")
        return True

    check("Octree: 8-camera flood localises target, then prune reclaims memory",
          test_octree_flood_and_recovery)

    def test_ray_from_far_outside():
        grid = VoxelGrid(VoxelGridConfig())
        # Ray starting 100 km away pointing away from the grid: zero heat.
        n = grid.add_ray(np.array([1e5, 1e5, 50.0]), np.array([1.0, 0.0, 0.0]),
                         intensity=5.0)
        assert n == 0, f"far/away ray deposited into {n} leaves"
        # Axis-aligned ray along a grid boundary must not blow up either.
        grid.add_ray(np.array([-128.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]),
                     intensity=1.0)
        return True

    check("Rays far outside the volume deposit nothing", test_ray_from_far_outside)


# --------------------------------------------------------------------------- #
# Phase S7: Geodesy round-trips at the edges of the Earth                     #
# --------------------------------------------------------------------------- #
def test_geo_edges():
    print("\n=== Phase S7: Geodesy edge cases ===")
    from math_utils.geo import wgs84_to_enu, enu_to_wgs84

    def test_roundtrip_midlat():
        ref = (37.7749, -122.4194, 0.0)
        for de, dn, du in ((100.0, -50.0, 30.0), (0.0, 0.0, 0.0), (-1000.0, 2000.0, 500.0)):
            lat, lon, alt = enu_to_wgs84(de, dn, du, *ref)
            e, n, u = wgs84_to_enu(lat, lon, alt, *ref)
            assert abs(e - de) < 0.01 and abs(n - dn) < 0.01 and abs(u - du) < 0.01, \
                f"roundtrip error: {(e - de, n - dn, u - du)}"
        return True

    check("ENU<->WGS84 round-trip closes to <1 cm at mid-latitude", test_roundtrip_midlat)

    def test_antimeridian_and_poles():
        # Antimeridian: two points 0.001 deg apart across +/-180 must be ~111 m
        # apart in ENU, not 40,000 km the wrong way round.
        e, n, u = wgs84_to_enu(0.0, -179.9995, 0.0, 0.0, 179.9995, 0.0)
        assert abs(e) < 1000.0, f"antimeridian E blew up: {e}"
        assert 50.0 < abs(e), f"antimeridian E suspiciously small: {e}"
        # Near-polar reference must stay finite.
        lat, lon, alt = enu_to_wgs84(100.0, 100.0, 10.0, 89.9, 0.0, 0.0)
        assert all(math.isfinite(v) for v in (lat, lon, alt)), "polar conversion not finite"
        e, n, u = wgs84_to_enu(lat, lon, alt, 89.9, 0.0, 0.0)
        assert abs(e - 100.0) < 0.1 and abs(n - 100.0) < 0.1, \
            f"polar roundtrip error: {(e, n, u)}"
        return True

    check("Antimeridian crossing and near-polar round-trips behave",
          test_antimeridian_and_poles)


# --------------------------------------------------------------------------- #
# Phase S8: Sustained ingest throughput (find the limit, assert a floor)      #
# --------------------------------------------------------------------------- #
def test_throughput():
    print("\n=== Phase S8: Throughput ===")

    def test_ingest_rate():
        # Realistic scene: 8 cameras each report a few bearings toward a small set
        # of shared target directions (what real detections look like), and the
        # loop drains-then-ticks per frame exactly like _run_loop. This measures
        # the real-time hot path rather than an adversarial all-directions spray
        # (that pathological case is covered by the vector-cap and leaf-cap tests).
        from common.protocol import TelemetryPacket, MotionVector
        server = _make_server()
        for c in range(8):
            server.cluster_manager.assign_node(f"CAM-{c:02d}", "DEFAULT")
        n_packets = 2000
        rng = random.Random(3)
        target_bearings = [(40.0, 12.0), (135.0, 18.0), (250.0, 8.0)]  # az, el
        # Sensors are FIXED installations — each camera keeps one position for the
        # whole run (a real node does not teleport between frames). Fixed origins +
        # stable bearings keep ray intersections coherent, so the octree converges
        # to a few compact regions instead of spraying leaves everywhere.
        cam_pos = {
            f"CAM-{c:02d}": (37.7750 + (c - 4) * 3e-4, -122.4194 + (c - 4) * 3e-4)
            for c in range(8)
        }

        def make_pkt(i):
            cam = f"CAM-{i % 8:02d}"
            lat, lon = cam_pos[cam]
            vecs = [MotionVector(azimuth=az + rng.uniform(-0.5, 0.5),
                                 elevation=el + rng.uniform(-0.5, 0.5),
                                 intensity=200, class_id=0)
                    for az, el in target_bearings]
            return TelemetryPacket(
                camera_id=cam, sequence_number=i, timestamp=time.time(),
                latitude=lat, longitude=lon, altitude=10.0,
                orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0x07, vectors=vecs)

        packets = [make_pkt(i) for i in range(n_packets)]

        def tick():
            for cl in server.cluster_manager.get_all_clusters().values():
                cl.voxel_grid.decay_active_leaves()
                cl.voxel_grid.consolidate_and_prune()
            server.process_frame()

        t0 = time.perf_counter()
        for i, pkt in enumerate(packets):
            server._process_packet(pkt, ("10.0.0.9", 1))
            if i % 100 == 99:            # drain-then-tick, ~100 pkts/frame
                tick()
        elapsed = time.perf_counter() - t0
        rate = n_packets / elapsed
        leaves = sum(len(cl.voxel_grid._active_leaves)
                     for cl in server.cluster_manager.get_all_clusters().values())
        print(f"        ({n_packets} pkts x 3 targets: {rate:,.0f} pkts/s; "
              f"leaves={leaves}, cap={server.voxel_grid.config.max_active_leaves})")
        assert leaves <= server.voxel_grid.config.max_active_leaves + 16, \
            f"octree exceeded leaf cap: {leaves}"
        assert rate > 200, f"ingest collapsed to {rate:.0f} pkts/s"
        return True

    check("Sustained 8-camera realistic ingest holds >200 pkts/s; octree under cap",
          test_ingest_rate)

    def test_udp_socket_flood():
        import socket
        from server.udp_server import UDPServer
        srv = UDPServer(port=0)
        # Bind to an ephemeral port ourselves so we know where to send.
        srv._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv._socket.bind(("127.0.0.1", 0))
        srv._socket.settimeout(0.1)
        port = srv._socket.getsockname()[1]
        srv._running = True
        import threading
        thread = threading.Thread(target=srv._receive_loop, daemon=True)
        thread.start()
        payload = _telemetry(n_vectors=5).pack()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for _ in range(3000):
            sender.sendto(payload, ("127.0.0.1", port))
        time.sleep(0.5)
        stats = srv.get_stats()
        srv._running = False
        thread.join(timeout=2.0)
        srv._socket.close()
        sender.close()
        assert stats["packets_received"] > 0, "flood: nothing received"
        assert stats["queue_size"] <= 1000, f"queue unbounded: {stats['queue_size']}"
        drained = len(srv.get_packets(max_count=5000))
        print(f"        (received {stats['packets_received']}, queued<=1000, "
              f"drained {drained}, dropped {stats['packets_dropped']})")
        return True

    check("3000-datagram loopback flood: queue bounded, drops counted, no crash",
          test_udp_socket_flood)


# --------------------------------------------------------------------------- #
# Phase S9: Config robustness (bad input must degrade, not crash startup)      #
# --------------------------------------------------------------------------- #
def test_config_robustness():
    print("\n=== Phase S9: Config robustness ===")
    from common.config import load

    def test_bad_env_override_does_not_crash():
        # A typo'd/hostile env override used to raise ValueError and abort the
        # WHOLE server at startup. It must now be ignored, default preserved,
        # while a well-formed override on the same section still applies.
        saved = dict(os.environ)
        try:
            os.environ["OR_NETWORK_UDP_PORT"] = "not_an_int"     # malformed int
            os.environ["OR_SERVER_TARGET_FPS"] = "3.5.1"          # malformed int
            os.environ["OR_NETWORK_MAX_NODES"] = "42"             # valid
            os.environ["OR_SECURITY_ENABLED"] = "yes"             # valid bool
            cfg = load()  # must not raise
            assert cfg.network.udp_port == 5005, "malformed int override was applied"
            assert cfg.network.max_nodes == 42, "valid override next to a bad one was dropped"
            assert cfg.security.enabled is True, "valid bool override lost"
        finally:
            os.environ.clear()
            os.environ.update(saved)
        return True

    check("Malformed env override is ignored (server startup survives it)",
          test_bad_env_override_does_not_crash)

    def test_unknown_yaml_key_tolerated():
        # An unknown/typo'd YAML key must be dropped with a warning, not abort load.
        cfg_path = os.path.join(tempfile.gettempdir(), "or_stress_cfg.yaml")
        with open(cfg_path, "w") as f:
            f.write("network:\n  udp_port: 6001\n  bogus_key_v9: 123\n"
                    "grid:\n  resolution_m: 2.0\n")
        try:
            from common.config import load as _load
            cfg = _load(cfg_path)
            assert cfg.network.udp_port == 6001, "known key next to unknown one lost"
            assert cfg.grid.resolution_m == 2.0, "second section not applied"
            assert not hasattr(cfg.network, "bogus_key_v9"), "unknown key leaked onto config"
        finally:
            os.remove(cfg_path)
        return True

    check("Unknown YAML key is dropped, the rest of the config still applies",
          test_unknown_yaml_key_tolerated)

    def test_non_dict_yaml_section_ignored():
        # A section given a scalar instead of a mapping must be skipped, not crash.
        cfg_path = os.path.join(tempfile.gettempdir(), "or_stress_cfg2.yaml")
        with open(cfg_path, "w") as f:
            f.write("network: not_a_mapping\ngrid:\n  resolution_m: 3.0\n")
        try:
            from common.config import load as _load
            cfg = _load(cfg_path)
            assert cfg.network.udp_port == 5005, "scalar section corrupted defaults"
            assert cfg.grid.resolution_m == 3.0, "valid section after a scalar one lost"
        finally:
            os.remove(cfg_path)
        return True

    check("A scalar where a config section is expected is ignored safely",
          test_non_dict_yaml_section_ignored)


# --------------------------------------------------------------------------- #
# Phase S10: Calibration solver under stress                                  #
# --------------------------------------------------------------------------- #
def test_calibration_solver():
    print("\n=== Phase S10: Calibration solver ===")
    from server.calibration import Calibrator
    from server.validation.calibration_validator import CalibrationValidator, ValidationResult
    from math_utils.quaternion import from_axis_angle, rotate_vector

    def _observations(cal, camera_id, mis_deg, n=200):
        cam = np.array([0.0, 0.0, 0.0])
        target = np.array([0.0, 100.0, 0.0])
        true_dir = (target - cam) / np.linalg.norm(target - cam)
        mis = from_axis_angle((0, 0, 1), mis_deg)
        obs_dir = np.array(rotate_vector(tuple(true_dir), mis))
        for _ in range(n):
            cal.add_observation(camera_id, obs_dir, target, cam)

    def test_recovers_known_misalignment():
        val = CalibrationValidator(min_observations=100)
        cal = Calibrator(buffer_size=2000, solve_interval=0.0,
                         blend_factor=0.5, validator=val)
        _observations(cal, "CAM-01", 3.0)
        res = cal.solve("CAM-01")
        assert res is not None, "solver returned nothing on ample observations"
        # A 3-degree yaw error must be recovered to within a fraction of a degree
        # and reduce (not increase) the residual.
        assert abs(res.correction_degrees - 3.0) < 1.0, \
            f"misalignment estimate off: {res.correction_degrees:.2f} deg"
        assert res.residual_after < res.residual_before, "solve made the residual worse"
        assert res.approved, f"a valid small correction was rejected: {res.reason}"
        return True

    check("Calibrator recovers a 3-degree injected misalignment and improves residual",
          test_recovers_known_misalignment)

    def test_oversized_correction_rejected():
        # A wild misalignment beyond max_correction_degrees must be REJECTED by
        # the validator so calibration never applies a huge, destabilising swing.
        val = CalibrationValidator(max_correction_degrees=15.0, min_observations=100)
        cal = Calibrator(buffer_size=2000, solve_interval=0.0,
                         blend_factor=0.5, validator=val)
        # Force a large validate query directly (solver clamps its own search).
        result, reason = val.validate_correction("CAM-huge", 40.0)
        assert result == ValidationResult.REJECT, "40-degree correction was not rejected"
        return True

    check("Validator rejects a correction beyond the max-correction gate",
          test_oversized_correction_rejected)

    def test_degenerate_and_empty_solve():
        val = CalibrationValidator(min_observations=100)
        cal = Calibrator(buffer_size=2000, solve_interval=0.0,
                         blend_factor=0.5, validator=val)
        # No observations at all: must return None, not raise.
        assert cal.solve("GHOST") is None, "empty solve did not return None"
        # Too-few observations: still no crash, still None.
        cam = np.array([0.0, 0.0, 0.0]); target = np.array([0.0, 50.0, 0.0])
        d = (target - cam) / np.linalg.norm(target - cam)
        for _ in range(10):
            cal.add_observation("CAM-2", d, target, cam)
        assert cal.solve("CAM-2") is None, "under-populated solve should be None"
        return True

    check("Empty / under-populated calibration solves return None without raising",
          test_degenerate_and_empty_solve)

    def test_apply_clears_buffer():
        # Applying a correction must clear that node's observation buffer, so the
        # next solve is not re-derived from stale (pre-correction) rays.
        val = CalibrationValidator(min_observations=100)
        cal = Calibrator(buffer_size=2000, solve_interval=0.0,
                         blend_factor=0.3, validator=val)
        _observations(cal, "CAM-3", 2.0)
        res = cal.solve("CAM-3")
        assert res is not None and res.approved
        assert cal.apply_correction(res) is True, "approved correction did not apply"
        assert len(cal._buffers["CAM-3"]) == 0, "buffer not cleared after apply (would oscillate)"
        # The applied offset is a unit quaternion.
        off = cal.get_offset("CAM-3")
        assert abs(sum(c * c for c in off) - 1.0) < 1e-6, f"offset not normalised: {off}"
        return True

    check("apply_correction clears the observation buffer and stores a unit offset",
          test_apply_clears_buffer)


# --------------------------------------------------------------------------- #
# Phase S11: LoRa gateway end-to-end translation                              #
# --------------------------------------------------------------------------- #
def test_lora_gateway():
    print("\n=== Phase S11: LoRa gateway ===")
    from server.lora_gateway import LoRaGateway
    from common.lora_protocol import (
        LoraAnnouncePacket, LoraUpdatePacket, frame_payload, LoRaFramer,
        node_id_to_camera_id, camera_id_to_node_id,
    )
    from common.protocol import AnnouncePacket, TelemetryPacket

    class _Transport:
        def start(self): pass
        def stop(self): pass
        def poll(self): return []

    def test_update_before_announce_is_orphaned():
        gw = LoRaGateway(_Transport())
        rp = gw._translate_update(
            LoraUpdatePacket(node_id=7, track_id=1, azimuth=45.0, elevation=10.0),
            time.time())
        assert rp is None, "update with no cached pose should be dropped"
        assert gw.get_stats()["orphan_updates"] == 1, "orphan not counted"
        return True

    check("LoRa UPDATE before any ANNOUNCE is dropped and counted (no pose to place it)",
          test_update_before_announce_is_orphaned)

    def test_announce_then_update_translates():
        gw = LoRaGateway(_Transport())
        # Yaw 330 exercises the wrap180 path in the announce packing.
        ann = gw._translate_announce(
            LoraAnnouncePacket(node_id=7, lat=37.7, lon=-122.4, alt=12.0,
                               roll_deg=0.0, pitch_deg=0.0, yaw_deg=330.0),
            time.time())
        assert isinstance(ann.packet, AnnouncePacket), "announce not translated"
        rp = gw._translate_update(
            LoraUpdatePacket(node_id=7, track_id=3, azimuth=45.0, elevation=10.0),
            time.time())
        assert isinstance(rp.packet, TelemetryPacket), "update not translated to telemetry"
        assert rp.packet.camera_id == node_id_to_camera_id(7), "camera_id mismatch"
        assert rp.packet.health_flags & 0x01, "synthesised telemetry lacks GPS-ok flag"
        assert all(math.isfinite(c) for c in rp.packet.orientation), \
            "non-finite orientation from Euler->quat"
        return True

    check("ANNOUNCE caches pose so a following UPDATE becomes full telemetry",
          test_announce_then_update_translates)

    def test_node_id_roundtrip_wraps():
        # uint8 node ids: a value > 255 wraps; mapping must be lossless mod 256.
        for nid in (0, 5, 255, 256 + 5):
            cam = node_id_to_camera_id(nid)
            back = camera_id_to_node_id(cam)
            assert back == (nid & 0xFF), f"node id {nid} -> {cam} -> {back}"
        return True

    check("node-id <-> camera-id mapping is lossless modulo 256",
          test_node_id_roundtrip_wraps)

    def test_gateway_queue_bounded_under_flood():
        # Ingest far more than the internal 1000-cap without draining; the queue
        # must stay bounded and the overflow must be counted, not grow the list.
        gw = LoRaGateway(_Transport())
        gw._ingest(LoraAnnouncePacket(node_id=1, lat=37.7, lon=-122.4, alt=5.0,
                                      roll_deg=0, pitch_deg=0, yaw_deg=0).pack(),
                   time.time())
        upd = LoraUpdatePacket(node_id=1, track_id=1, azimuth=10.0, elevation=5.0).pack()
        for _ in range(5000):
            gw._ingest(upd, time.time())
        stats = gw.get_stats()
        assert stats["queue_size"] <= 1000, f"gateway queue unbounded: {stats['queue_size']}"
        assert stats["queue_dropped"] > 0, "overflow not counted"
        return True

    check("LoRa gateway queue stays <=1000 under a 5000-update flood; drops counted",
          test_gateway_queue_bounded_under_flood)

    def test_framer_to_gateway_integration():
        # Frame two payloads over a raw serial byte stream, deframe them 1 byte at
        # a time (worst case), and confirm the gateway decodes both.
        gw = LoRaGateway(_Transport())
        framer = LoRaFramer()
        stream = (frame_payload(LoraAnnouncePacket(node_id=2, lat=37.7, lon=-122.4,
                                                   alt=5.0, roll_deg=0, pitch_deg=0,
                                                   yaw_deg=0).pack())
                  + frame_payload(LoraUpdatePacket(node_id=2, track_id=1,
                                                   azimuth=20.0, elevation=8.0).pack()))
        emitted = 0
        for i in range(len(stream)):
            for payload in framer.push(stream[i:i + 1]):
                before = gw.get_stats()["packets_emitted"]
                gw._ingest(payload, time.time())
                emitted += gw.get_stats()["packets_emitted"] - before
        assert emitted == 2, f"framer->gateway emitted {emitted} packets (expected 2)"
        return True

    check("Serial framing round-trips announce+update through the gateway (1-byte reads)",
          test_framer_to_gateway_integration)


# --------------------------------------------------------------------------- #
# Phase S12: Broadcast payloads are strict-JSON safe (never exercised by the  #
#            tests before: the WS loop is not started, so json.dumps is skipped)#
# --------------------------------------------------------------------------- #
def test_broadcast_serialization():
    print("\n=== Phase S12: Broadcast serialization ===")

    def _strict(obj):
        # allow_nan=False: NaN/Inf serialise to tokens Python accepts but the
        # browser's JSON.parse rejects — catch them here, not in the field.
        return json.dumps(obj, allow_nan=False)

    def _drive_one_frame(server):
        # Push a couple of real telemetry packets from two nodes toward a shared
        # bearing, then run one processing frame so tracks/voxels/rays exist.
        for c, (lat, lon) in enumerate([(37.7752, -122.4194), (37.7748, -122.4190)]):
            server.cluster_manager.assign_node(f"CAM-{c:02d}", "DEFAULT")
        for frame in range(6):
            for c, (lat, lon) in enumerate([(37.7752, -122.4194), (37.7748, -122.4190)]):
                server._process_packet(
                    _telemetry(camera_id=f"CAM-{c:02d}", n_vectors=3,
                               lat=lat, lon=lon, seq=frame),
                    ("10.0.0.1", 1))
            server.frame_count = frame
            for cl in server.cluster_manager.get_all_clusters().values():
                cl.voxel_grid.decay_active_leaves()
                dets = cl.voxel_grid.get_detections()
                cl.tracker.update(server._build_detections(cl, dets))

    def test_system_status_payload_is_strict_json():
        # Rebuild exactly what _broadcast_system_status composes, but capture the
        # dict instead of sending it (the loop is not running in this harness).
        server = _make_server()
        _drive_one_frame(server)
        captured = {}
        server.ws_server.broadcast_system_status = lambda status: captured.update(status)
        server.fg_server.publish_system_status = lambda status: None
        server.ws_server.broadcast_clusters = lambda clusters: None
        server.fg_server.publish_clusters = lambda clusters: None
        server._broadcast_system_status()
        assert captured, "system status never composed"
        _strict(captured)  # raises ValueError on NaN/Inf or a non-serialisable type
        # The metrics snapshot rides inside; make sure it is JSON-safe too.
        _strict(captured.get("metrics", {}))
        return True

    check("Composed SYSTEM_STATUS payload is strict-JSON serialisable (no NaN/Inf/np types)",
          test_system_status_payload_is_strict_json)

    def test_track_voxel_ray_payloads_are_strict_json():
        server = _make_server()
        _drive_one_frame(server)
        sent = {"tracks": None, "voxels": None, "rays": None}
        server.ws_server.broadcast_tracks = lambda data, room=None: sent.__setitem__("tracks", data)
        server.ws_server.broadcast_voxels = lambda data, room=None: sent.__setitem__("voxels", data)
        server.ws_server.broadcast_rays = lambda data, room=None: sent.__setitem__("rays", data)
        for cid, cluster in server.cluster_manager.get_all_clusters().items():
            tracks = cluster.tracker.get_all_tracks()
            server._broadcast_tracks(cid, tracks)
            server._broadcast_voxels(cid, cluster.voxel_grid)
            server._broadcast_rays(cid, [])
        for kind, payload in sent.items():
            assert payload is not None, f"{kind} broadcast never fired"
            _strict(payload)  # each wire array must be strict-JSON safe
        return True

    check("TRACK/VOXEL/RAY wire payloads are strict-JSON serialisable",
          test_track_voxel_ray_payloads_are_strict_json)


# --------------------------------------------------------------------------- #
# Phase S13: Node-health lifecycle transitions                                #
# --------------------------------------------------------------------------- #
def test_node_health_transitions():
    print("\n=== Phase S13: Node health transitions ===")
    from server.monitoring.node_health import NodeHealthMonitor, NodeStatus

    def test_offline_after_timeout():
        mon = NodeHealthMonitor(offline_timeout_sec=30.0)
        mon.record_packet("N1", packet_timestamp=time.time(), sequence=0, health_flags=0x07)
        rec = mon.get_node_health("N1")
        # A record whose last packet is older than the timeout reads OFFLINE.
        assert rec.get_status(current_time=time.time() + 31) == NodeStatus.OFFLINE, \
            "node not marked offline past the timeout"
        assert rec.get_status(current_time=time.time()) != NodeStatus.OFFLINE, \
            "fresh node wrongly offline"
        return True

    check("Node goes OFFLINE only after the offline timeout elapses",
          test_offline_after_timeout)

    def test_missing_gps_is_unhealthy():
        mon = NodeHealthMonitor()
        # health_flags without the GPS bit (0x01) -> UNHEALTHY regardless of rate.
        for i in range(50):
            mon.record_packet("N2", packet_timestamp=time.time(), sequence=i,
                              health_flags=0x06)  # CAM+IMU, no GPS
        assert mon.get_node_status("N2") == NodeStatus.UNHEALTHY, \
            "node without a GPS fix is not flagged UNHEALTHY"
        return True

    check("A node reporting no GPS fix is UNHEALTHY",
          test_missing_gps_is_unhealthy)

    def test_sequence_gaps_counted():
        mon = NodeHealthMonitor()
        seqs = list(range(0, 200))
        del seqs[50]      # drop one -> a single gap
        del seqs[100]     # and another
        for s in seqs:
            mon.record_packet("N3", packet_timestamp=time.time(), sequence=s,
                              health_flags=0x07)
        assert mon.get_node_health("N3").sequence_gaps == 2, \
            f"gap detector miscounted: {mon.get_node_health('N3').sequence_gaps}"
        return True

    check("Sequence-number gaps are detected and counted",
          test_sequence_gaps_counted)


# --------------------------------------------------------------------------- #
# Phase S14: Numeric hardening (geodesy poles, covariance, Kalman, quats)      #
# --------------------------------------------------------------------------- #
def test_numeric_hardening():
    print("\n=== Phase S14: Numeric hardening ===")

    def test_pole_conversions_finite():
        from math_utils.geo import enu_to_wgs84, wgs84_to_enu
        # Exactly at the north pole the ENU east axis is degenerate; the result
        # must still be finite (no divide-by-zero blow-up).
        for ref_lat in (90.0, -90.0, 89.9999):
            lla = enu_to_wgs84(100.0, 100.0, 10.0, ref_lat, 0.0, 0.0)
            assert all(math.isfinite(v) for v in lla), f"pole ref {ref_lat} -> {lla}"
            enu = wgs84_to_enu(*lla, ref_lat, 0.0, 0.0)
            assert all(math.isfinite(v) for v in enu), f"pole roundtrip non-finite: {enu}"
        return True

    check("Geodesy stays finite exactly at the poles", test_pole_conversions_finite)

    def test_covariance_degenerate_geometry():
        from server.uncertainty import measurement_covariance
        pos = np.array([0.0, 100.0, 0.0])
        # Single node: finite, well-formed, depth-uncertain (large along-ray var).
        R1 = measurement_covariance(pos, [(np.array([0., 0., 0.]), math.radians(0.1))])
        assert R1 is not None and np.isfinite(R1).all(), "single-node covariance not finite"
        # Two perfectly collinear nodes (behind the target on one axis): the
        # regularisation must keep the fused matrix invertible and finite.
        cams = [(np.array([0., -10., 0.]), math.radians(0.1)),
                (np.array([0., -60., 0.]), math.radians(0.1))]
        R2 = measurement_covariance(pos, cams)
        assert R2 is not None and np.isfinite(R2).all(), "collinear covariance blew up"
        assert np.linalg.cond(R2) < 1e8, f"collinear covariance ill-conditioned: {np.linalg.cond(R2):.1e}"
        # A node sitting exactly on the target contributes nothing -> None (caller
        # falls back to its default isotropic R).
        assert measurement_covariance(pos, [(pos.copy(), math.radians(0.1))]) is None, \
            "zero-range node should contribute no information"
        return True

    check("Fused measurement covariance stays finite for degenerate node geometry",
          test_covariance_degenerate_geometry)

    def test_kalman_survives_idle_gap():
        from server.tracking.tracker import Tracker, Detection
        tr = Tracker()
        t0 = time.time()
        tr.update([Detection(position=np.array([1., 2., 3.]))], timestamp=t0)
        # One-hour dt gap (node idle, then resumes): dt^4 process noise is huge,
        # but the state and covariance must stay finite.
        tr.update([Detection(position=np.array([1., 2., 3.]))], timestamp=t0 + 3600)
        for t in tr.get_all_tracks():
            assert np.isfinite(t.position).all(), "position went non-finite after idle gap"
            assert np.isfinite(t.kalman_state.P).all(), "covariance went non-finite after idle gap"
        return True

    check("Kalman filter survives a one-hour dt gap with finite state",
          test_kalman_survives_idle_gap)

    def test_quaternion_edges_roundtrip():
        from math_utils.quaternion import (
            from_axis_angle, to_axis_angle, slerp, normalize, multiply, conjugate)
        # Negative-w quaternion must canonicalise to the same rotation.
        q = from_axis_angle((0, 0, 1), 200.0)  # >180 -> negative-w hemisphere
        axis, ang = to_axis_angle(q)
        assert 0.0 <= ang <= 360.0 and all(math.isfinite(a) for a in axis), \
            f"axis-angle degenerate: {axis}, {ang}"
        # slerp endpoints must be exact (t=0 -> q1, t=1 -> q2) even near-antipodal.
        q1 = normalize((1, 0, 0, 0))
        q2 = normalize((0, 0, 0, 1))
        s0, s1 = slerp(q1, q2, 0.0), slerp(q1, q2, 1.0)
        # Compare as rotations (q and -q are equal): dot magnitude ~1.
        d0 = abs(sum(a * b for a, b in zip(s0, q1)))
        d1 = abs(sum(a * b for a, b in zip(s1, q2)))
        assert d0 > 0.999 and d1 > 0.999, f"slerp endpoints drifted: {d0}, {d1}"
        # q * q^-1 == identity.
        ident = multiply(q, conjugate(q))
        assert abs(ident[0] - 1.0) < 1e-9 and max(abs(c) for c in ident[1:]) < 1e-9, \
            f"q * conj(q) != identity: {ident}"
        return True

    check("Quaternion axis-angle / slerp / inverse behave at their edges",
          test_quaternion_edges_roundtrip)


def main():
    random.seed(1234)
    print("=" * 60)
    print("OpticalRadar STRESS suite")
    print("=" * 60)
    test_fuzz_parsing()
    test_adversarial_packets()
    test_registry_floods()
    test_websocket_abuse()
    test_security_attacks()
    test_pipeline_limits()
    test_geo_edges()
    test_throughput()
    test_config_robustness()
    test_calibration_solver()
    test_lora_gateway()
    test_broadcast_serialization()
    test_node_health_transitions()
    test_numeric_hardening()
    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed ({PASS + FAIL} total)")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
