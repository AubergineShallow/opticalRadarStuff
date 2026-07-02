

"""Math module - coordinate transformations and quaternion operations."""

from .geo import (
    wgs84_to_ecef, ecef_to_enu, wgs84_to_enu, enu_to_wgs84, ecef_to_wgs84,
    calculate_look_angles, distance_3d, haversine_distance,
    WGS84_A, WGS84_B, WGS84_E2
)
from .quaternion import (
    normalize, multiply, conjugate, rotate_vector,
    from_euler, to_euler, from_axis_angle, to_axis_angle,
    slerp, identity, angle_between
)

__all__ = [
    # Geo
    'wgs84_to_ecef', 'ecef_to_enu', 'wgs84_to_enu', 'enu_to_wgs84', 'ecef_to_wgs84',
    'calculate_look_angles', 'distance_3d', 'haversine_distance',
    'WGS84_A', 'WGS84_B', 'WGS84_E2',
    
    # Quaternion
    'normalize', 'multiply', 'conjugate', 'rotate_vector',
    'from_euler', 'to_euler', 'from_axis_angle', 'to_axis_angle',
    'slerp', 'identity', 'angle_between',
]
