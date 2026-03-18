"""
ray_builder.py
PURPOSE: Convert camera detections to 2D rays on the ground plane (2D fork).

Elevation is ignored; only the azimuth component is used to produce a
horizontal bearing from each camera position.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
import sys
import os

_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from math_utils.geo import wgs84_to_enu
from math_utils.quaternion import rotate_vector


@dataclass
class CameraState:
    """Camera position and orientation (2D fork — only horizontal components kept)."""
    camera_id: str
    position_enu: np.ndarray  # [E, N] in meters (2D)
    orientation: Tuple[float, float, float, float]  # Quaternion [w, x, y, z]

    # Optional calibration offset
    calibration_offset: Optional[Tuple[float, float, float, float]] = None


@dataclass
class Ray:
    """2D ray from camera through detection."""
    origin: np.ndarray       # Ray origin (camera position) [E, N]
    direction: np.ndarray    # Unit direction vector [E, N]
    intensity: float         # From motion vector
    camera_id: str

    # Original angle (for debugging/calibration)
    azimuth: float = 0.0


class RayBuilder:
    """
    Convert camera detections to 2D rays in EN coordinates (2D fork).

    Takes:
        - Camera GPS position
        - Camera orientation (quaternion)
        - Detection azimuth angle (elevation ignored)

    Produces:
        - 2D ray on the ground plane in local EN coordinates
    """

    def __init__(
        self,
        reference_lat: float,
        reference_lon: float,
        reference_alt: float = 0.0
    ):
        """
        Initialize ray builder.

        Args:
            reference_lat: Reference latitude for ENU origin
            reference_lon: Reference longitude for ENU origin
            reference_alt: Reference altitude (kept for GPS conversion)
        """
        self.ref_lat = reference_lat
        self.ref_lon = reference_lon
        self.ref_alt = reference_alt

        # Camera states (updated per packet)
        self._cameras: dict = {}

    def update_camera(
        self,
        camera_id: str,
        latitude: float,
        longitude: float,
        altitude: float,
        orientation: Tuple[float, float, float, float]
    ) -> CameraState:
        """
        Update camera position and orientation.

        Args:
            camera_id: Camera identifier
            latitude, longitude, altitude: GPS position
            orientation: Quaternion [w, x, y, z]

        Returns:
            Updated camera state (2D position)
        """
        # Convert GPS to ENU – keep only E, N
        e, n, _u = wgs84_to_enu(
            latitude, longitude, altitude,
            self.ref_lat, self.ref_lon, self.ref_alt
        )

        state = CameraState(
            camera_id=camera_id,
            position_enu=np.array([e, n]),
            orientation=orientation,
            calibration_offset=self._cameras.get(camera_id, CameraState(
                camera_id=camera_id,
                position_enu=np.zeros(2),
                orientation=(1, 0, 0, 0)
            )).calibration_offset
        )

        self._cameras[camera_id] = state
        return state

    def set_calibration_offset(
        self,
        camera_id: str,
        offset_quaternion: Tuple[float, float, float, float]
    ) -> None:
        """
        Set calibration offset for camera orientation.

        Args:
            camera_id: Camera ID
            offset_quaternion: Calibration correction quaternion
        """
        if camera_id in self._cameras:
            self._cameras[camera_id].calibration_offset = offset_quaternion

    def azimuth_to_direction(self, azimuth: float) -> np.ndarray:
        """
        Convert azimuth to 2D unit direction vector.

        Azimuth: 0° = North, 90° = East (clockwise from North)

        Args:
            azimuth: Azimuth in degrees

        Returns:
            Unit direction vector [E, N]
        """
        az_rad = np.radians(azimuth)

        e = np.sin(az_rad)   # East
        n = np.cos(az_rad)   # North

        return np.array([e, n])

    def build_ray(
        self,
        camera_id: str,
        azimuth: float,
        elevation: float = 0.0,   # accepted but ignored in 2D fork
        intensity: float = 1.0
    ) -> Optional[Ray]:
        """
        Build 2D ray from camera detection.

        Args:
            camera_id: Camera ID
            azimuth: Detection azimuth (degrees)
            elevation: IGNORED in 2D fork
            intensity: Detection intensity

        Returns:
            Ray object or None if camera unknown
        """
        if camera_id not in self._cameras:
            return None

        state = self._cameras[camera_id]

        # Get body-frame direction in 3D, then project
        body_direction_3d = np.array([
            np.sin(np.radians(azimuth)),
            np.cos(np.radians(azimuth)),
            0.0
        ])

        # Apply camera orientation in 3D
        world_direction_3d = rotate_vector(body_direction_3d, state.orientation)

        # Apply calibration offset if present
        if state.calibration_offset:
            world_direction_3d = rotate_vector(world_direction_3d, state.calibration_offset)

        # Project to 2D ground plane
        d2 = np.array([world_direction_3d[0], world_direction_3d[1]])
        norm = np.linalg.norm(d2)
        if norm < 1e-12:
            return None
        d2 = d2 / norm

        return Ray(
            origin=state.position_enu.copy(),
            direction=d2,
            intensity=intensity,
            camera_id=camera_id,
            azimuth=azimuth,
        )

    def build_rays_from_packet(
        self,
        camera_id: str,
        latitude: float,
        longitude: float,
        altitude: float,
        orientation: Tuple[float, float, float, float],
        vectors: List[Tuple[float, float, float]]   # (azimuth, elevation, intensity)
    ) -> List[Ray]:
        """
        Build rays from a telemetry packet.

        Args:
            camera_id: Camera ID
            latitude, longitude, altitude: Camera GPS
            orientation: Camera orientation quaternion
            vectors: List of (azimuth, elevation, intensity) tuples

        Returns:
            List of Ray objects (2D)
        """
        # Update camera state
        self.update_camera(camera_id, latitude, longitude, altitude, orientation)

        # Build rays
        rays = []
        for az, el, intensity in vectors:
            ray = self.build_ray(camera_id, az, el, intensity / 255.0)
            if ray:
                rays.append(ray)

        return rays

    def get_camera_position(self, camera_id: str) -> Optional[np.ndarray]:
        """Get camera position in EN (2D)."""
        if camera_id in self._cameras:
            return self._cameras[camera_id].position_enu.copy()
        return None

    def get_all_cameras(self) -> List[str]:
        """Get list of known camera IDs."""
        return list(self._cameras.keys())
