

"""
foxglove_broadcaster.py
PURPOSE: Optional, parallel live-streaming broadcaster for Foxglove/Flora.

This is a pure ADD-ON that runs alongside the bespoke JSON WebSocketBroadcaster
(websocket_server.py) without touching it. It speaks the Foxglove WebSocket
protocol (via foxglove-sdk) so Flora's built-in 3D / Map / Plot panels can
consume the exact same data server_main already computes for the JSON UI.

Two independent gates keep it inert by default:
  1. Lazy import: absence of `foxglove-sdk` is safe on its own (same pattern as
     rpi/vision.py's optional cv2 import). `_FG_AVAILABLE` reflects the import.
  2. Config flag: `foxglove.enabled` (default False) gates whether the second
     listening socket is ever opened -- a least-surprise/security control so a
     future `pip install foxglove-sdk` can't silently start streaming.

Ghost-geometry note: Foxglove SceneUpdate entities are persistent by id (unlike
the JSON broadcaster's full-replace-every-frame semantics). Rather than tracking
per-id deletes, every entity is published with a short lifetime (~2 frame times)
so cooled voxels / dropped tracks disappear on their own next frame -- matching
the JSON broadcaster's behaviour for free.

Every public method is wrapped in try/except: a publish failure must never
propagate into the 30Hz tracking loop. Methods are kept pure ("shape data in ->
call SDK", no side effects on server_main state) so the inline publish calls can
later be moved onto a worker thread as a localized change if the hot loop ever
shows frame-budget pressure.
"""

import time

# Gate 1: lazy import. The whole add-on degrades to no-ops if the SDK is absent.
try:
    import foxglove
    from foxglove import channels as _fg_channels
    from foxglove.messages import (
        SceneUpdate, SceneEntity, CubePrimitive, LinePrimitive, TextPrimitive,
        LocationFix, Color, Vector3, Point3, Pose, Quaternion, Duration,
        Timestamp,
    )
    _FG_AVAILABLE = True
except ImportError:
    _FG_AVAILABLE = False


# Entities are given ~2 frame times of lifetime (~66ms at 30fps) so expired
# voxels / dropped tracks self-delete instead of ghosting in Flora.
_ENTITY_LIFETIME_NS = 66_000_000

# Ray primitives are drawn as fixed-length segments: the Ray dataclass carries a
# unit direction but no range, so we use the ray-march ceiling (native_wrapper's
# max_distance default) as the visual length.
_RAY_LENGTH_M = 150.0

# All scene geometry lives in one fixed frame (no FrameTransforms are published),
# so Flora's 3D panel can use it directly as the display frame.
_SCENE_FRAME = "map"


class FoxgloveBroadcaster:
    """
    Parallel Foxglove-protocol broadcaster.

    Mirrors the message types the JSON WebSocketBroadcaster emits:
      - node-update / system-status / clusters  -> custom JSON channels
      - GPS                                       -> LocationFix channel
      - per-cluster tracks / voxels / rays        -> SceneUpdate channels

    node-update, system-status and cluster payloads are published verbatim (the
    same dicts server_main already builds); only tracks/voxels/rays are
    transformed into SceneUpdate primitives, because that's what buys the 3D
    panel.
    """

    def __init__(self, port: int = 8765, enabled: bool = False):
        self.port = port
        self.enabled = enabled
        self.running = False

        # SDK handles, created in start(). None until then.
        self._server = None
        self._node_channel = None
        self._status_channel = None
        self._clusters_channel = None
        self._gps_channel = None
        # Per-cluster SceneUpdate channels, created lazily on first sight.
        self._scene_channels = {}

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    def start(self):
        """Open the Foxglove server + channels. No-op unless enabled & available."""
        if not (self.enabled and _FG_AVAILABLE):
            return
        try:
            self._server = foxglove.start_server(
                name="OpticalRadar", host="0.0.0.0", port=self.port
            )
            # One JSON channel per JSON message type (mirrors websocket_server).
            self._node_channel = foxglove.Channel(
                "/node_update", message_encoding="json", schema={"type": "object"}
            )
            self._status_channel = foxglove.Channel(
                "/system_status", message_encoding="json", schema={"type": "object"}
            )
            self._clusters_channel = foxglove.Channel(
                "/clusters", message_encoding="json", schema={"type": "object"}
            )
            self._gps_channel = _fg_channels.LocationFixChannel("/gps")
            self.running = True
            print(f"Foxglove server started on port {self.port}")
        except Exception as e:
            print(f"Foxglove server start failed: {e}")
            self.running = False

    def stop(self):
        """Stop the Foxglove server. No-op unless it was started."""
        if not self.running:
            return
        self.running = False
        try:
            if self._server is not None:
                self._server.stop()
        except Exception as e:
            print(f"Foxglove server stop error: {e}")

    # ------------------------------------------------------------------ #
    # Pass-through JSON publishers (verbatim server_main dicts)          #
    # ------------------------------------------------------------------ #
    def publish_node_update(self, data: dict):
        """Publish a node-update dict verbatim (same dict as broadcast_node_update)."""
        if not self.running:
            return
        try:
            self._node_channel.log(data)
        except Exception as e:
            print(f"Foxglove publish_node_update error: {e}")

    def publish_node_location(self, node_id, lat, lon, alt):
        """Publish a node's raw GPS fix (for Flora's Map panel)."""
        if not self.running:
            return
        try:
            self._gps_channel.log(LocationFix(
                timestamp=self._now(),
                frame_id=str(node_id),
                latitude=float(lat),
                longitude=float(lon),
                altitude=float(alt),
            ))
        except Exception as e:
            print(f"Foxglove publish_node_location error: {e}")

    def publish_system_status(self, data: dict):
        """Publish the system-status dict verbatim."""
        if not self.running:
            return
        try:
            self._status_channel.log(data)
        except Exception as e:
            print(f"Foxglove publish_system_status error: {e}")

    def publish_clusters(self, data: dict):
        """Publish the cluster-topology dict verbatim."""
        if not self.running:
            return
        try:
            self._clusters_channel.log(data)
        except Exception as e:
            print(f"Foxglove publish_clusters error: {e}")

    # ------------------------------------------------------------------ #
    # SceneUpdate publisher (the 3D payload)                             #
    # ------------------------------------------------------------------ #
    def publish_scene(self, cluster_id, tracks, hot_voxels, rays):
        """
        Publish one SceneUpdate for a cluster: voxel cubes, sensor-ray lines, and
        track cubes + text labels, all in a single short-lifetime entity keyed by
        cluster_id. The next frame's entity replaces this one (same topic+id) and
        the lifetime is a backstop for a cluster that stops publishing entirely.
        """
        if not self.running:
            return
        try:
            channel = self._scene_channel(cluster_id)

            cubes = []
            lines = []
            texts = []

            for v in (hot_voxels or []):
                cubes.append(self._voxel_cube(v))

            for r in (rays or []):
                lines.append(self._ray_line(r))

            for t in (tracks or []):
                cube, label = self._track_primitives(t, cluster_id)
                cubes.append(cube)
                texts.append(label)

            entity = SceneEntity(
                timestamp=self._now(),
                frame_id=_SCENE_FRAME,
                id=str(cluster_id),
                lifetime=Duration(sec=0, nsec=_ENTITY_LIFETIME_NS),
                cubes=cubes,
                lines=lines,
                texts=texts,
            )
            channel.log(SceneUpdate(entities=[entity]))
        except Exception as e:
            print(f"Foxglove publish_scene error: {e}")

    # ------------------------------------------------------------------ #
    # Shaping helpers (pure: data in -> SDK primitive out)              #
    # ------------------------------------------------------------------ #
    def _scene_channel(self, cluster_id):
        """Lazily create + cache a per-cluster SceneUpdate channel."""
        channel = self._scene_channels.get(cluster_id)
        if channel is None:
            channel = _fg_channels.SceneUpdateChannel(f"/scene/{cluster_id}")
            self._scene_channels[cluster_id] = channel
        return channel

    @staticmethod
    def _now():
        """Current wall-clock as a Foxglove Timestamp (lifetime is relative to it)."""
        now = time.time()
        sec = int(now)
        return Timestamp(sec=sec, nsec=int((now - sec) * 1e9))

    @staticmethod
    def _identity_pose(x, y, z):
        return Pose(
            position=Vector3(x=float(x), y=float(y), z=float(z)),
            orientation=Quaternion(x=0.0, y=0.0, z=0.0, w=1.0),
        )

    def _voxel_cube(self, voxel):
        """A HotVoxel -> a heat-coloured, heat-transparent cube."""
        cx, cy, cz = float(voxel.center[0]), float(voxel.center[1]), float(voxel.center[2])
        size = float(voxel.size_m)
        # Heat ramp: cool = blue/low-alpha, hot = red/high-alpha. Clamped so a
        # runaway heat value can't produce an out-of-range colour.
        t = max(0.0, min(1.0, float(voxel.heat) / 50.0))
        return CubePrimitive(
            pose=self._identity_pose(cx, cy, cz),
            size=Vector3(x=size, y=size, z=size),
            color=Color(r=t, g=0.2, b=1.0 - t, a=0.25 + 0.55 * t),
        )

    def _ray_line(self, ray):
        """A Ray -> a fixed-length line segment (origin -> origin + dir*len)."""
        ox, oy, oz = float(ray.origin[0]), float(ray.origin[1]), float(ray.origin[2])
        dx, dy, dz = float(ray.direction[0]), float(ray.direction[1]), float(ray.direction[2])
        end = Point3(
            x=ox + dx * _RAY_LENGTH_M,
            y=oy + dy * _RAY_LENGTH_M,
            z=oz + dz * _RAY_LENGTH_M,
        )
        intensity = max(0.0, min(1.0, float(getattr(ray, "intensity", 0.0))))
        return LinePrimitive(
            pose=self._identity_pose(0.0, 0.0, 0.0),
            thickness=2.0,
            scale_invariant=True,
            points=[Point3(x=ox, y=oy, z=oz), end],
            color=Color(r=0.2, g=0.8, b=1.0, a=0.3 + 0.5 * intensity),
        )

    def _track_primitives(self, track, cluster_id):
        """A Track -> (cube at its position, text label with id/state)."""
        pos = track.position
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        track_id = getattr(track, "track_id", getattr(track, "id", "?"))
        state = int(getattr(track, "state", 0))
        cube = CubePrimitive(
            pose=self._identity_pose(px, py, pz),
            size=Vector3(x=2.0, y=2.0, z=2.0),
            color=Color(r=0.1, g=1.0, b=0.3, a=0.8),
        )
        label = TextPrimitive(
            pose=self._identity_pose(px, py, pz + 2.0),
            billboard=True,
            font_size=1.0,
            scale_invariant=True,
            color=Color(r=1.0, g=1.0, b=1.0, a=1.0),
            text=f"T-{track_id} ({state})",
        )
        return cube, label
