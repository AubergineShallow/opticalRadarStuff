"""
ray_builder.py
PURPOSE: Convert camera detections to 3D rays.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from math_utils.geo import wgs84_to_enu
from math_utils.quaternion import rotate_vector


@dataclass
class CameraState:
    """Camera position and orientation."""
    camera_id: str
    position_enu: np.ndarray  # [E, N, U] in meters
    orientation: Tuple[float, float, float, float]  # Quaternion [w, x, y, z]
    
    # Optional calibration offset
    calibration_offset: Optional[Tuple[float, float, float, float]] = None


@dataclass
class Ray:
    """3D ray from camera through detection."""
    origin: np.ndarray  # Ray origin (camera position)
    direction: np.ndarray  # Unit direction vector
    intensity: float  # From motion vector
    camera_id: str
    
    # Original angles (for debugging/calibration)
    azimuth: float = 0.0
    elevation: float = 0.0


class RayBuilder:
    """
    Convert camera detections to 3D rays in ENU coordinates.
    
    Takes:
        - Camera GPS position
        - Camera orientation (quaternion)
        - Detection angles (azimuth, elevation)
    
    Produces:
        - 3D ray in local ENU coordinates
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
            reference_alt: Reference altitude
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
            Updated camera state
        """
        # Convert GPS to ENU
        e, n, u = wgs84_to_enu(
            latitude, longitude, altitude,
            self.ref_lat, self.ref_lon, self.ref_alt
        )
        
        state = CameraState(
            camera_id=camera_id,
            position_enu=np.array([e, n, u]),
            orientation=orientation,
            calibration_offset=self._cameras.get(camera_id, CameraState(
                camera_id=camera_id,
                position_enu=np.zeros(3),
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
    
    def angles_to_direction(
        self,
        azimuth: float,
        elevation: float
    ) -> np.ndarray:
        """
        Convert azimuth/elevation to unit direction vector.
        
        Azimuth: 0° = North, 90° = East (clockwise from North)
        Elevation: 0° = horizon, positive = up
        
        Args:
            azimuth: Azimuth in degrees
            elevation: Elevation in degrees
        
        Returns:
            Unit direction vector [E, N, U]
        """
        az_rad = np.radians(azimuth)
        el_rad = np.radians(elevation)
        
        cos_el = np.cos(el_rad)
        
        # ENU convention: azimuth from North
        e = cos_el * np.sin(az_rad)  # East
        n = cos_el * np.cos(az_rad)  # North
        u = np.sin(el_rad)           # Up
        
        return np.array([e, n, u])
    
    def build_ray(
        self,
        camera_id: str,
        azimuth: float,
        elevation: float,
        intensity: float = 1.0
    ) -> Optional[Ray]:
        """
        Build 3D ray from camera detection.
        
        Args:
            camera_id: Camera ID
            azimuth: Detection azimuth (degrees)
            elevation: Detection elevation (degrees)
            intensity: Detection intensity
        
        Returns:
            Ray object or None if camera unknown
        """
        if camera_id not in self._cameras:
            return None
        
        state = self._cameras[camera_id]
        
        # Get body-frame direction
        body_direction = self.angles_to_direction(azimuth, elevation)
        
        # Apply camera orientation
        world_direction = rotate_vector(body_direction, state.orientation)
        
        # Apply calibration offset if present
        if state.calibration_offset:
            world_direction = rotate_vector(world_direction, state.calibration_offset)
        
        # Normalize
        world_direction = world_direction / np.linalg.norm(world_direction)
        
        return Ray(
            origin=state.position_enu.copy(),
            direction=np.array(world_direction),
            intensity=intensity,
            camera_id=camera_id,
            azimuth=azimuth,
            elevation=elevation
        )
    
    def build_rays_from_packet(
        self,
        camera_id: str,
        latitude: float,
        longitude: float,
        altitude: float,
        orientation: Tuple[float, float, float, float],
        vectors: List[Tuple[float, float, float]]  # (azimuth, elevation, intensity)
    ) -> List[Ray]:
        """
        Build rays from a telemetry packet.
        
        Args:
            camera_id: Camera ID
            latitude, longitude, altitude: Camera GPS
            orientation: Camera orientation quaternion
            vectors: List of (azimuth, elevation, intensity) tuples
        
        Returns:
            List of Ray objects
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
        """Get camera position in ENU."""
        if camera_id in self._cameras:
            return self._cameras[camera_id].position_enu.copy()
        return None
    
    def get_all_cameras(self) -> List[str]:
        """Get list of known camera IDs."""
        return list(self._cameras.keys())
