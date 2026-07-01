import logging
import json
from typing import Dict, List, Any

try:
    import foxglove
    from foxglove import start_server, Channel, Schema
    _FG_AVAILABLE = True
except ImportError:
    _FG_AVAILABLE = False

logger = logging.getLogger(__name__)

class FoxgloveBroadcaster:
    def __init__(self, port: int = 8765, enabled: bool = False):
        self.port = port
        self.enabled = enabled
        self.server = None

        self.node_update_channel = None
        self.system_status_channel = None
        self.clusters_channel = None
        self.location_fix_channel = None

        self.scene_channels: Dict[str, Channel] = {}

    def start(self):
        if not self.enabled or not _FG_AVAILABLE:
            return

        try:
            self.server = start_server(host="0.0.0.0", port=self.port, name="Optical Radar")

            # Setup JSON channels
            self.node_update_channel = Channel("opticalradar/node_updates")
            self.system_status_channel = Channel("opticalradar/system_status")
            self.clusters_channel = Channel("opticalradar/clusters")

            # Setup standard LocationFix channel
            self.location_fix_channel = Channel(
                "opticalradar/location",
                schema={"type": "object", "title": "foxglove.LocationFix"},
                message_encoding="json"
            )
            logger.info(f"Foxglove server started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start Foxglove server: {e}")

    def stop(self):
        if not self.enabled or not _FG_AVAILABLE or not self.server:
            return
        try:
            self.server.stop()
        except Exception as e:
            logger.error(f"Error stopping Foxglove server: {e}")

    def publish_node_update(self, data: dict):
        if not self.enabled or not _FG_AVAILABLE or not self.node_update_channel:
            return
        try:
            self.node_update_channel.log(data)
        except Exception as e:
            logger.error(f"Failed to publish node update: {e}")

    def publish_node_location(self, node_id: str, lat: float, lon: float, alt: float):
        if not self.enabled or not _FG_AVAILABLE or not self.location_fix_channel:
            return
        try:
            # foxglove.LocationFix JSON representation
            # see: https://foxglove.dev/docs/studio/messages/location-fix
            msg = {
                "latitude": lat,
                "longitude": lon,
                "altitude": alt
            }
            self.location_fix_channel.log(msg)
        except Exception as e:
            logger.error(f"Failed to publish node location: {e}")

    def publish_system_status(self, data: dict):
        if not self.enabled or not _FG_AVAILABLE or not self.system_status_channel:
            return
        try:
            self.system_status_channel.log(data)
        except Exception as e:
            logger.error(f"Failed to publish system status: {e}")

    def publish_clusters(self, data: dict):
        if not self.enabled or not _FG_AVAILABLE or not self.clusters_channel:
            return
        try:
            self.clusters_channel.log(data)
        except Exception as e:
            logger.error(f"Failed to publish clusters: {e}")

    def publish_scene(self, cluster_id: str, tracks: List[Any], hot_voxels: List[Any], rays: List[Any]):
        if not self.enabled or not _FG_AVAILABLE:
            return

        try:
            if cluster_id not in self.scene_channels:
                self.scene_channels[cluster_id] = Channel(
                    f"opticalradar/scene/{cluster_id}",
                    schema={"type": "object", "title": "foxglove.SceneUpdate"},
                    message_encoding="json"
                )

            channel = self.scene_channels[cluster_id]

            # Construct SceneUpdate
            # foxglove.SceneUpdate schema:
            # { "entities": [ { "id": "...", "timestamp": {...}, "frame_id": "...", "cubes": [...], "lines": [...], ... } ] }

            # Short lifetime (~66ms) to avoid manual deletes
            LIFETIME = {"sec": 0, "nsec": 66_000_000}

            entities = []

            # Add voxels as cubes
            for i, voxel in enumerate(hot_voxels):
                cube = {
                    "pose": {
                        "position": {"x": float(voxel.center[0]), "y": float(voxel.center[1]), "z": float(voxel.center[2])},
                        "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}
                    },
                    "size": {"x": float(voxel.size_m), "y": float(voxel.size_m), "z": float(voxel.size_m)},
                    "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": min(1.0, float(voxel.heat) / 10.0)}
                }
                entities.append({
                    "id": f"voxel_{i}",
                    "timestamp": {"sec": 0, "nsec": 0},
                    "frame_id": "map",
                    "lifetime": LIFETIME,
                    "cubes": [cube]
                })

            # Add rays as lines
            for i, ray in enumerate(rays):
                end = ray.origin + (ray.direction * 100.0) # Assume 100m range for visualization
                line = {
                    "type": 0, # LINE_LIST
                    "pose": {
                        "position": {"x": 0, "y": 0, "z": 0},
                        "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}
                    },
                    "thickness": 0.5,
                    "color": {"r": 0.0, "g": 1.0, "b": 0.0, "a": 0.5},
                    "points": [
                        {"x": float(ray.origin[0]), "y": float(ray.origin[1]), "z": float(ray.origin[2])},
                        {"x": float(end[0]), "y": float(end[1]), "z": float(end[2])}
                    ]
                }
                entities.append({
                    "id": f"ray_{i}",
                    "timestamp": {"sec": 0, "nsec": 0},
                    "frame_id": "map",
                    "lifetime": LIFETIME,
                    "lines": [line]
                })

            # Add tracks as cubes + text
            for i, track in enumerate(tracks):
                cube = {
                    "pose": {
                        "position": {"x": float(track.position[0]), "y": float(track.position[1]), "z": float(track.position[2])},
                        "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}
                    },
                    "size": {"x": 2.0, "y": 2.0, "z": 2.0},
                    "color": {"r": 0.0, "g": 0.0, "b": 1.0, "a": 1.0}
                }
                text = {
                    "pose": {
                        "position": {"x": float(track.position[0]), "y": float(track.position[1]), "z": float(track.position[2]) + 2.0},
                        "orientation": {"x": 0, "y": 0, "z": 0, "w": 1}
                    },
                    "billboard": True,
                    "font_size": 1.0,
                    "scale_invariant": False,
                    "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                    "text": f"Track {track.track_id} ({track.state.name})"
                }
                entities.append({
                    "id": f"track_{track.track_id}",
                    "timestamp": {"sec": 0, "nsec": 0},
                    "frame_id": "map",
                    "lifetime": LIFETIME,
                    "cubes": [cube],
                    "texts": [text]
                })

            if entities:
                channel.log({"deletions": [], "entities": entities})

        except Exception as e:
            logger.error(f"Failed to publish scene: {e}")
