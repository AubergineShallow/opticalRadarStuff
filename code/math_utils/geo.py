"""
geo.py
PURPOSE: Convert between different ways of describing locations on Earth.
"""

import math
import numpy as np
from typing import Tuple

# WGS84 ellipsoid parameters
WGS84_A = 6378137.0  # semi-major axis (meters)
WGS84_B = 6356752.314245  # semi-minor axis (meters)
WGS84_E2 = 1.0 - (WGS84_B ** 2) / (WGS84_A ** 2)  # first eccentricity squared


def wgs84_to_ecef(lat: float, lon: float, alt: float) -> Tuple[float, float, float]:
    """
    Convert GPS coordinates to Earth-Centered Earth-Fixed (ECEF).
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        alt: Altitude in meters above WGS84 ellipsoid
    
    Returns:
        Tuple of (X, Y, Z) in meters
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    
    # Radius of curvature in the prime vertical
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    
    X = (N + alt) * cos_lat * cos_lon
    Y = (N + alt) * cos_lat * sin_lon
    Z = (N * (1.0 - WGS84_E2) + alt) * sin_lat
    
    return (X, Y, Z)


def ecef_to_enu(
    x: float, y: float, z: float,
    ref_lat: float, ref_lon: float, ref_alt: float
) -> Tuple[float, float, float]:
    """
    Convert ECEF to local ENU (East-North-Up) coordinates.
    
    Args:
        x, y, z: ECEF coordinates in meters
        ref_lat, ref_lon, ref_alt: Reference point (origin) in WGS84
    
    Returns:
        Tuple of (E, N, U) in meters relative to reference
    """
    # Get reference point in ECEF
    ref_x, ref_y, ref_z = wgs84_to_ecef(ref_lat, ref_lon, ref_alt)
    
    # Difference vector
    dx = x - ref_x
    dy = y - ref_y
    dz = z - ref_z
    
    # Rotation angles
    lat_rad = math.radians(ref_lat)
    lon_rad = math.radians(ref_lon)
    
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    
    # ENU transformation
    E = -sin_lon * dx + cos_lon * dy
    N = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    U = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    
    return (E, N, U)


def wgs84_to_enu(
    lat: float, lon: float, alt: float,
    ref_lat: float, ref_lon: float, ref_alt: float
) -> Tuple[float, float, float]:
    """
    Convert GPS directly to local ENU coordinates.
    
    Args:
        lat, lon, alt: Target point in WGS84
        ref_lat, ref_lon, ref_alt: Reference point (origin) in WGS84
    
    Returns:
        Tuple of (E, N, U) in meters
    """
    x, y, z = wgs84_to_ecef(lat, lon, alt)
    return ecef_to_enu(x, y, z, ref_lat, ref_lon, ref_alt)


def enu_to_wgs84(
    e: float, n: float, u: float,
    ref_lat: float, ref_lon: float, ref_alt: float
) -> Tuple[float, float, float]:
    """
    Convert local ENU coordinates back to WGS84.
    
    Args:
        e, n, u: Local ENU coordinates in meters
        ref_lat, ref_lon, ref_alt: Reference point (origin) in WGS84
    
    Returns:
        Tuple of (lat, lon, alt) in degrees/meters
    """
    # Get reference point in ECEF
    ref_x, ref_y, ref_z = wgs84_to_ecef(ref_lat, ref_lon, ref_alt)
    
    # Rotation angles
    lat_rad = math.radians(ref_lat)
    lon_rad = math.radians(ref_lon)
    
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    
    # Inverse ENU transformation (to ECEF delta)
    dx = -sin_lon * e - sin_lat * cos_lon * n + cos_lat * cos_lon * u
    dy = cos_lon * e - sin_lat * sin_lon * n + cos_lat * sin_lon * u
    dz = cos_lat * n + sin_lat * u
    
    # ECEF position
    x = ref_x + dx
    y = ref_y + dy
    z = ref_z + dz
    
    # Convert ECEF back to WGS84 (iterative)
    return ecef_to_wgs84(x, y, z)


def ecef_to_wgs84(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """
    Convert ECEF to WGS84 (iterative method).
    
    Args:
        x, y, z: ECEF coordinates in meters
    
    Returns:
        Tuple of (lat, lon, alt) in degrees/meters
    """
    lon = math.atan2(y, x)
    
    # Iterative solution for latitude and altitude
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    
    for _ in range(10):  # Usually converges in 2-3 iterations
        sin_lat = math.sin(lat)
        N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        lat = math.atan2(z + WGS84_E2 * N * sin_lat, p)
    
    sin_lat = math.sin(lat)
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    alt = p / math.cos(lat) - N
    
    return (math.degrees(lat), math.degrees(lon), alt)


def calculate_look_angles(
    observer_e: float, observer_n: float, observer_u: float,
    target_e: float, target_n: float, target_u: float
) -> Tuple[float, float]:
    """
    Calculate azimuth and elevation from observer to target.
    
    Args:
        observer_e, observer_n, observer_u: Observer position in ENU (meters)
        target_e, target_n, target_u: Target position in ENU (meters)
    
    Returns:
        Tuple of (azimuth, elevation) in degrees
        - Azimuth: 0-360° from TRUE NORTH, clockwise
        - Elevation: -90 to +90° from horizon
    """
    # Vector from observer to target
    de = target_e - observer_e
    dn = target_n - observer_n
    du = target_u - observer_u
    
    # Horizontal distance
    horizontal_dist = math.sqrt(de * de + dn * dn)
    
    # Azimuth (from North, clockwise)
    azimuth = math.degrees(math.atan2(de, dn))
    if azimuth < 0:
        azimuth += 360.0
    
    # Elevation (from horizon)
    elevation = math.degrees(math.atan2(du, horizontal_dist))
    
    return (azimuth, elevation)


def distance_3d(
    x1: float, y1: float, z1: float,
    x2: float, y2: float, z2: float
) -> float:
    """Calculate 3D Euclidean distance."""
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two GPS points.
    
    Args:
        lat1, lon1: First point in degrees
        lat2, lon2: Second point in degrees
    
    Returns:
        Distance in meters
    """
    R = 6371000  # Earth radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c
