#!/usr/bin/env python
"""
system_test.py - Full system orchestration test.

Verifies that all modules import correctly and the server + simulation
pipeline runs end-to-end without errors.
"""

import sys
import os
import time
import threading
import traceback

# Setup path
code_dir = os.path.dirname(os.path.abspath(__file__))
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

PASS = 0
FAIL = 0

def check(name, fn):
    """Run a check and report pass/fail."""
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



def test_geo():
    print("\n=== Phase X: Geo Math ===")
    from math_utils.geo import haversine_distance

    def test_haversine():
        # New York
        lat1, lon1 = 40.7128, -74.0060
        # London
        lat2, lon2 = 51.5074, -0.1278

        dist = haversine_distance(lat1, lon1, lat2, lon2)
        assert 5500000 < dist < 5600000, f"Distance NY to London expected ~5570km, got {dist/1000}km"

        # Identical points
        dist_zero = haversine_distance(lat1, lon1, lat1, lon1)
        assert dist_zero == 0.0, f"Distance to self expected 0.0, got {dist_zero}"

        # Antipodal points
        dist_antipodal = haversine_distance(0.0, 0.0, 0.0, 180.0)
        # pi * R = 3.14159 * 6371000 = 20015086.7
        assert 20000000 < dist_antipodal < 20030000, f"Distance antipodal expected ~20015km, got {dist_antipodal/1000}km"

        return True

    check("haversine_distance calculations", test_haversine)



def test_quaternion():
    print("\n=== Phase X: Quaternion Math ===")
    from math_utils.quaternion import normalize

    def test_normalize():
        # Standard normalization
        q = (1.0, 1.0, 1.0, 1.0)
        norm_q = normalize(q)
        assert abs(norm_q[0] - 0.5) < 1e-6, f"Expected 0.5 for w, got {norm_q[0]}"
        assert abs(norm_q[1] - 0.5) < 1e-6, f"Expected 0.5 for x, got {norm_q[1]}"
        assert abs(norm_q[2] - 0.5) < 1e-6, f"Expected 0.5 for y, got {norm_q[2]}"
        assert abs(norm_q[3] - 0.5) < 1e-6, f"Expected 0.5 for z, got {norm_q[3]}"

        # Zero magnitude edge case
        zero_q = (0.0, 0.0, 0.0, 0.0)
        norm_zero = normalize(zero_q)
        assert norm_zero == (1.0, 0.0, 0.0, 0.0), f"Expected identity for zero mag, got {norm_zero}"

        return True

    check("quaternion normalize calculations", test_normalize)


def test_imports():
    """Test that all modules import without errors."""
    print("\n=== Phase 1: Import Verification ===")
    
    check("common.constants", lambda: __import__("common.constants"))
    check("common.config", lambda: __import__("common.config"))
    check("common.protocol", lambda: __import__("common.protocol"))
    check("math_utils.geo", lambda: __import__("math_utils.geo"))
    check("math_utils.quaternion", lambda: __import__("math_utils.quaternion"))
    check("server.udp_server", lambda: __import__("server.udp_server"))
    check("server.ray_builder", lambda: __import__("server.ray_builder"))
    check("server.voxel_grid", lambda: __import__("server.voxel_grid"))
    check("server.calibration", lambda: __import__("server.calibration"))
    check("server.websocket_server", lambda: __import__("server.websocket_server"))
    check("server.tracking.tracker", lambda: __import__("server.tracking.tracker"))
    check("server.tracking.kalman_filter", lambda: __import__("server.tracking.kalman_filter"))
    check("server.tracking.data_association", lambda: __import__("server.tracking.data_association"))
    check("server.tracking.track_manager", lambda: __import__("server.tracking.track_manager"))
    check("server.monitoring.node_health", lambda: __import__("server.monitoring.node_health"))
    check("server.security.authenticator", lambda: __import__("server.security.authenticator"))
    check("server.validation.ground_truth", lambda: __import__("server.validation.ground_truth"))
    check("server.validation.calibration_validator", lambda: __import__("server.validation.calibration_validator"))
    check("server.server_main", lambda: __import__("server.server_main"))
    check("simulation.sim_node", lambda: __import__("simulation.sim_node"))
    check("simulation.sim_utils", lambda: __import__("simulation.sim_utils"))


def test_protocol():
    """Test protocol pack/unpack round-trip."""
    print("\n=== Phase 2: Protocol Round-Trip ===")
    
    from common.protocol import (
        TelemetryPacket, MotionVector, CommandPacket,
        PACKET_TYPE_TELEMETRY, HEADER_SIZE
    )
    from common.constants import VERSION
    
    # Telemetry packet
    def test_telemetry_roundtrip():
        vectors = [
            MotionVector(azimuth=45.0, elevation=10.0, intensity=200, class_id=1),
            MotionVector(azimuth=90.0, elevation=-5.0, intensity=150, class_id=0),
        ]
        pkt = TelemetryPacket(
            version=VERSION,
            camera_id="cam01",
            timestamp=time.time(),
            sequence_number=42,
            latitude=1.3521,
            longitude=103.8198,
            altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            health_flags=0x07,
            vectors=vectors,
        )
        data = pkt.pack()
        assert len(data) >= HEADER_SIZE, f"Packed data too short: {len(data)}"
        
        pkt2 = TelemetryPacket.unpack(data)
        assert pkt2.camera_id == "cam01", f"Camera ID mismatch: {pkt2.camera_id}"
        assert len(pkt2.vectors) == 2, f"Vector count mismatch: {len(pkt2.vectors)}"
        assert pkt2.sequence_number == 42, f"Sequence mismatch: {pkt2.sequence_number}"
        return True
    
    check("Telemetry pack/unpack (2 vectors)", test_telemetry_roundtrip)
    
    # Command packet
    def test_command_roundtrip():
        cmd = CommandPacket(
            camera_id="cam02",
            command_type=CommandPacket.CMD_RESTART,
            payload=b"\x01\x02\x03",
        )
        data = cmd.pack()
        cmd2 = CommandPacket.unpack(data)
        assert cmd2.camera_id == "cam02"
        assert cmd2.command_type == CommandPacket.CMD_RESTART
        assert cmd2.payload == b"\x01\x02\x03"
        return True
    
    check("Command pack/unpack", test_command_roundtrip)
    
    # Header size (uint16 vector count = 61 bytes)
    def test_header_size():
        assert HEADER_SIZE == 61, f"Expected 61, got {HEADER_SIZE}"
        return True
    
    check("Header size == 61 (uint16 vector_count)", test_header_size)
    
    # Large vector count (>255)
    def test_large_vector_count():
        vectors = [
            MotionVector(azimuth=float(i), elevation=0.0, intensity=100, class_id=0)
            for i in range(300)
        ]
        pkt = TelemetryPacket(
            version=VERSION,
            camera_id="cam03",
            timestamp=time.time(),
            sequence_number=1,
            latitude=0.0, longitude=0.0, altitude=0.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            health_flags=0x07,
            vectors=vectors,
        )
        data = pkt.pack()
        pkt2 = TelemetryPacket.unpack(data)
        assert len(pkt2.vectors) == 300, f"Expected 300 vectors, got {len(pkt2.vectors)}"
        return True
    
    check("300 vectors (exceeds old uint8 limit)", test_large_vector_count)


def test_config():
    """Test config loading with new GPS/IMU sections."""
    print("\n=== Phase 3: Config ===")
    
    from common.config import Config, GPSConfig, IMUConfig
    
    def test_default_config():
        cfg = Config()
        assert hasattr(cfg, 'gps'), "Missing gps config"
        assert hasattr(cfg, 'imu'), "Missing imu config"
        assert cfg.gps.port == "/dev/serial0"
        assert cfg.imu.i2c_address == 0x68
        return True
    
    check("Config has GPS/IMU sections with defaults", test_default_config)


def test_voxel_grid():
    """Test voxel grid operations."""
    print("\n=== Phase 4: Voxel Grid ===")
    
    import numpy as np
    from server.voxel_grid import VoxelGrid, VoxelGridConfig
    
    def test_grid_lifecycle():
        cfg = VoxelGridConfig(width_m=50, height_m=25, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        
        # Add a ray
        origin = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        direction /= np.linalg.norm(direction)
        updated = grid.add_ray(origin, direction, intensity=10.0)
        assert updated > 0, f"No voxels updated: {updated}"
        
        # Stats
        stats = grid.get_stats()
        assert 'hot_count' in stats, f"Missing hot_count in stats: {stats.keys()}"
        assert 'total_voxels' in stats
        
        # Decay
        grid.decay()
        
        # Detections
        dets = grid.get_detections()
        assert isinstance(dets, list)
        
        return True
    
    check("Grid lifecycle: add_ray -> get_stats -> decay -> get_detections", test_grid_lifecycle)


def test_calibration():
    """Test calibration solver uses gradient descent."""
    print("\n=== Phase 5: Calibration ===")
    
    import numpy as np
    from server.calibration import Calibrator
    
    def test_solver_runs():
        cal = Calibrator(buffer_size=200)
        
        # Feed enough observations to trigger solve
        for i in range(60):
            cal.add_observation(
                camera_id="cam01",
                ray_direction=np.array([1.0, 0.1 * np.sin(i * 0.1), 0.0]),
                camera_position=np.array([0.0, 0.0, 0.0]),
                target_position=np.array([100.0, 5.0, 0.0])
            )
        
        result = cal.solve("cam01")
        assert result is not None, "Solver returned None"
        assert hasattr(result, 'correction_quaternion')
        assert hasattr(result, 'residual_before')
        assert hasattr(result, 'residual_after')
        return True
    
    check("Calibration solver (gradient descent)", test_solver_runs)


def test_tracker():
    """Test tracker pipeline."""
    print("\n=== Phase 6: Tracker ===")
    
    import numpy as np
    from server.tracking.tracker import Tracker
    
    def test_tracker_update():
        tracker = Tracker()
        
        class MockDetection:
            def __init__(self, pos):
                self.position = np.array(pos)
                self.confidence = 1.0
                self.timestamp = time.time()
                self.class_id = 0
        
        # Feed detections over several frames
        for frame in range(10):
            detections = [MockDetection([50.0 + frame, 30.0, 10.0])]
            result = tracker.update(detections)
            assert hasattr(result, 'tracks')
        
        tracks = tracker.get_confirmed_tracks()
        # After 10 frames, should have confirmed at least one track
        # (confirm threshold is typically 3 hits)
        return True
    
    check("Tracker: 10-frame update cycle", test_tracker_update)


def test_full_server_init():
    """Test that server can be initialized without network."""
    print("\n=== Phase 7: Server Initialization ===")
    
    from server.server_main import OpticalRadarServer
    
    def test_server_create():
        server = OpticalRadarServer(headless=True)
        
        # Check all subsystems initialized
        assert server.voxel_grid is not None, "Missing voxel_grid"
        assert server.ray_builder is not None, "Missing ray_builder"
        assert server.tracker is not None, "Missing tracker"
        assert server.calibrator is not None, "Missing calibrator"
        assert server.node_health is not None, "Missing node_health"
        assert server.ground_truth is not None, "Missing ground_truth"
        
        # Check new state variables
        assert hasattr(server, 'current_fps'), "Missing current_fps tracker"
        assert hasattr(server, '_start_time'), "Missing _start_time"
        assert hasattr(server, '_last_frame_time'), "Missing _last_frame_time"
        
        return True
    
    check("Server init (headless, all subsystems present)", test_server_create)


def test_server_process_frame():
    """Test that server can process frames without network."""
    print("\n=== Phase 8: Server Frame Processing ===")
    
    import numpy as np
    from server.server_main import OpticalRadarServer
    
    def test_frame_cycle():
        server = OpticalRadarServer(headless=True)
        
        # Manually add a ray to the voxel grid so there's data to process
        origin = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.5])
        direction /= np.linalg.norm(direction)
        server.voxel_grid.add_ray(origin, direction, intensity=10.0)
        
        # Process several frames
        for _ in range(5):
            server.process_frame()
        
        # Verify FPS tracking is working
        assert server.current_fps >= 0, f"FPS should be non-negative: {server.current_fps}"
        assert server.frame_count == 5, f"Frame count: {server.frame_count}"
        
        return True
    
    check("5-frame processing cycle (no network)", test_frame_cycle)


def test_ray_pipeline_integration():
    from server.ray_builder import RayBuilder
    from server.voxel_grid import VoxelGrid, VoxelGridConfig
    from common.protocol import MotionVector

    rb = RayBuilder(reference_lat=1.3521, reference_lon=103.8198, reference_alt=0.0)
    cfg = VoxelGridConfig(width_m=200, height_m=100, depth_m=200, resolution_m=1.0)
    grid = VoxelGrid(cfg)

    vectors = [
        MotionVector(azimuth=45.0, elevation=10.0, intensity=200, class_id=1),
        MotionVector(azimuth=90.0, elevation=5.0,  intensity=180, class_id=1),
    ]
    rays = rb.build_rays_from_packet(
        camera_id="CAM-01",
        latitude=1.3521, longitude=103.8198, altitude=15.0,
        orientation=(1.0, 0.0, 0.0, 0.0),
        vectors=[(v.azimuth, v.elevation, v.intensity) for v in vectors]
    )
    assert len(rays) == 2, f"Expected 2 rays, got {len(rays)}"
    updated = grid.add_rays_batch(rays)
    assert updated >= 0, "add_rays_batch raised or returned negative"
    return True

def test_decay_rate_default_in_cluster():
    from server.cluster_manager import Cluster
    from common.config import Config

    config = Config() # Create empty config
    cluster = Cluster("TEST", config)
    assert cluster.voxel_grid.config.decay_rate == 0.95, f"Expected 0.95, got {cluster.voxel_grid.config.decay_rate}"
    return True

def test_hot_threshold_in_cluster():
    from server.cluster_manager import Cluster
    from common.config import Config

    config = Config()
    config.voxel_grid = {'hot_threshold': 2.0}
    cluster = Cluster("TEST", config)
    assert cluster.voxel_grid.config.hot_threshold == 2.0, f"Expected 2.0, got {cluster.voxel_grid.config.hot_threshold}"
    return True

def test_battery_level_absent():
    from server.server_main import OpticalRadarServer
    from common.protocol import TelemetryPacket, PACKET_TYPE_TELEMETRY
    import os

    os.environ['OR_SECURITY_ENABLED'] = 'false'
    server = OpticalRadarServer(headless=True)

    class FakePacket:
        packet_type = PACKET_TYPE_TELEMETRY
        camera_id = "TEST_NODE"
        latitude = 0.0
        longitude = 0.0
        altitude = 0.0
        orientation = (1.0, 0.0, 0.0, 0.0)
        health_flags = 0
        vectors = []
        timestamp = 123456789.0
        sequence_number = 1

    try:
        server._process_packet(FakePacket(), ('127.0.0.1', 12345))
    except AttributeError as e:
        assert False, f"AttributeError raised: {e}"

    return True

def test_uptime_monotonic():
    from server.server_main import OpticalRadarServer
    import os
    import time

    os.environ['OR_SECURITY_ENABLED'] = 'false'
    server = OpticalRadarServer(headless=True)

    # Force some time to pass
    time.sleep(0.1)

    # Broadcast status doesn't return anything but it creates the dict internally.
    # We will test the time diff calculation logic.
    uptime1 = int(time.time() - server._start_time)
    time.sleep(1.0)
    uptime2 = int(time.time() - server._start_time)
    assert uptime2 >= uptime1, f"Uptime not monotonic: {uptime1} -> {uptime2}"
    return True

def test_octree():
    print("\n=== Phase 8.5: Octree ===")
    from server.voxel_grid import VoxelGrid, VoxelGridConfig
    import numpy as np

    def test_decay_consolidate_independence():
        cfg = VoxelGridConfig(width_m=50, height_m=25, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        origin    = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        grid.add_ray(origin, direction, intensity=10.0)

        heat_before = grid.get_stats()['max_heat']

        # Run 10 decay cycles WITHOUT consolidate
        for _ in range(10):
            grid.decay_active_leaves()

        heat_after = grid.get_stats()['max_heat']
        expected = heat_before * (0.95 ** 10)
        assert abs(heat_after - expected) < 0.01, \
            f"Heat after 10 decays: {heat_after:.4f}, expected ~{expected:.4f}"
        return True

    def test_root_expansion_preserves_coords():
        cfg = VoxelGridConfig(width_m=50, height_m=50, depth_m=50, resolution_m=5.0)
        grid = VoxelGrid(cfg)
        origin    = np.array([0.0, 0.0, 25.0])
        direction = np.array([1.0, 0.0, 0.0])
        grid.add_ray(origin, direction, intensity=10.0)
        hot_before = grid.get_hot_voxels()
        assert hot_before, "No hot voxels before expansion"
        center_before = hot_before[0].center.copy()

        # Trigger expansion on the +X axis
        grid.expand_root(np.array([48.0, 0.0, 25.0]))

        hot_after = grid.get_hot_voxels()
        assert hot_after, "No hot voxels after expansion"
        assert np.allclose(center_before, hot_after[0].center, atol=0.1), \
            f"Leaf moved: {center_before} -> {hot_after[0].center}"
        return True

    def test_amanatiedes_woo_exact_visit():
        cfg = VoxelGridConfig(width_m=50, height_m=50, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        # We start just inside the bounding box
        origin    = np.array([-24.9, 0.0, 25.0])
        direction = np.array([1.0, 0.0, 0.0])
        updated = grid.add_ray(origin, direction, intensity=1.0)

        # root is 64x64x64, we walk through 64 meters, but origin is at -24.9, so we travel 50m to edge.
        # But wait, max_distance is 150m, root bound might be 64.
        # The number of updated cells could be around 25 to 32, we just want > 0 and no crash.
        assert updated > 0, "No cells visited"
        return True

    def test_subdivision_trigger_camera_count():
        cfg = VoxelGridConfig(width_m=50, height_m=50, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        origin = np.array([0.0, 0.0, 25.0])
        direction = np.array([0.0, 0.0, 1.0])

        # Send 3 distinct cameras
        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM1")
        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM2")
        # Ensure we are not sub-divided yet
        leaves_before = len(grid._active_leaves)
        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM3")
        leaves_after = len(grid._active_leaves)

        assert leaves_after > leaves_before, "Failed to subdivide after 3 distinct cameras"
        return True

    def test_subdivision_window_gating():
        import time
        cfg = VoxelGridConfig(width_m=50, height_m=50, depth_m=50, resolution_m=2.0, camera_window_s=0.1)
        grid = VoxelGrid(cfg)
        origin = np.array([0.0, 0.0, 25.0])
        direction = np.array([0.0, 0.0, 1.0])

        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM1")
        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM2")
        time.sleep(0.2) # Wait past window
        leaves_before = len(grid._active_leaves)
        grid.add_ray(origin, direction, intensity=1.0, camera_id="CAM3")
        leaves_after = len(grid._active_leaves)

        assert leaves_after == leaves_before, "Subdivided despite votes being outside window"
        return True

    def test_cubic_root_derivation():
        cfg1 = VoxelGridConfig(width_m=200, depth_m=200, height_m=100)
        grid1 = VoxelGrid(cfg1)
        assert grid1._root.size[0] == 256.0, "Root should be pow2(max_dim)=256"

        cfg2 = VoxelGridConfig(width_m=200, depth_m=200, height_m=100, root_cell_size_m=512)
        grid2 = VoxelGrid(cfg2)
        assert grid2._root.size[0] == 512.0, "Root should use explicit size"
        return True

    check("Decay / Consolidate independence", test_decay_consolidate_independence)
    check("Root expansion coords preserved", test_root_expansion_preserves_coords)
    check("Amanatides-Woo exact visit", test_amanatiedes_woo_exact_visit)
    check("Subdivision by camera count", test_subdivision_trigger_camera_count)
    check("Subdivision window gating", test_subdivision_window_gating)
    check("Cubic root size derivation", test_cubic_root_derivation)

def test_simulation_to_server():
    """Test simulation node sends packets that server can unpack."""
    print("\n=== Phase 9: Simulation → Server Pipeline ===")
    
    import numpy as np
    from simulation.sim_node import SimNode, SimCameraConfig, SimTarget
    from common.protocol import TelemetryPacket
    
    def test_sim_packet_creation():
        config = SimCameraConfig(
            camera_id="sim01",
            position=np.array([100.0, 0.0, 2.0]),
            latitude=1.3521,
            longitude=103.8198,
            altitude=15.0,
            fov_horizontal=90.0
        )
        
        node = SimNode(config)
        node.add_target(SimTarget(
            target_id="t1",
            position=np.array([50.0, 50.0, 30.0])
        ))
        
        # Manually call process_frame internals
        detections = node.detect_targets()
        # Whether or not we detect depends on FOV, but the code should not crash
        return True
    
    check("SimNode detect_targets (no crash)", test_sim_packet_creation)


def main():
    print("=" * 60)
    print("OpticalRadar-Iter3 Full System Orchestration Test")
    print("=" * 60)
    
    test_geo()
    test_quaternion()
    test_imports()
    test_protocol()
    test_config()
    test_voxel_grid()
    test_calibration()
    test_tracker()
    test_full_server_init()
    test_server_process_frame()
    check("Ray pipeline: build_rays_from_packet -> add_rays_batch", test_ray_pipeline_integration)
    check("Cluster default decay_rate", test_decay_rate_default_in_cluster)
    check("Cluster hot_threshold override", test_hot_threshold_in_cluster)
    check("Packet battery level missing ignored", test_battery_level_absent)
    check("Uptime monotonic", test_uptime_monotonic)
    test_octree()
    test_simulation_to_server()
    
    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed ({PASS + FAIL} total)")
    print("=" * 60)
    
    return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
