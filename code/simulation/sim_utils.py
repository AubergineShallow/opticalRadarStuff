

"""
sim_utils.py
PURPOSE: Helper math for the simulation.
"""

import math
import numpy as np
from typing import Tuple


def degrees_to_radians(degrees: float) -> float:
    """Convert degrees to radians."""
    return degrees * (math.pi / 180.0)


def radians_to_degrees(radians: float) -> float:
    """Convert radians to degrees."""
    return radians * (180.0 / math.pi)


def enu_to_azel(
    target_e: float, target_n: float, target_u: float,
    camera_e: float, camera_n: float, camera_u: float
) -> Tuple[float, float]:
    """
    Calculate azimuth and elevation from camera to target.
    
    Args:
        target_e, target_n, target_u: Target position in ENU
        camera_e, camera_n, camera_u: Camera position in ENU
    
    Returns:
        Tuple of (azimuth, elevation) in degrees
    """
    de = target_e - camera_e
    dn = target_n - camera_n
    du = target_u - camera_u
    
    horizontal_dist = math.sqrt(de * de + dn * dn)
    
    # Azimuth from North, clockwise
    azimuth = math.degrees(math.atan2(de, dn))
    if azimuth < 0:
        azimuth += 360.0
    
    # Elevation from horizon
    elevation = math.degrees(math.atan2(du, horizontal_dist))
    
    return (azimuth, elevation)


def generate_circular_positions(
    radius: float,
    count: int,
    center: Tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> np.ndarray:
    """
    Generate positions in a circle.
    
    Args:
        radius: Circle radius
        count: Number of positions
        center: Circle center (e, n, u)
    
    Returns:
        Array of positions (count, 3)
    """
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    positions = np.zeros((count, 3))
    
    for i, angle in enumerate(angles):
        positions[i, 0] = center[0] + radius * np.cos(angle)
        positions[i, 1] = center[1] + radius * np.sin(angle)
        positions[i, 2] = center[2]
    
    return positions


def generate_figure_eight(
    size: float,
    t: float,
    speed: float = 1.0,
    center: Tuple[float, float, float] = (0.0, 0.0, 50.0)
) -> Tuple[float, float, float]:
    """
    Generate position on a figure-8 path.
    
    Args:
        size: Path size
        t: Time parameter
        speed: Speed multiplier
        center: Path center
    
    Returns:
        Position (e, n, u)
    """
    theta = t * speed
    
    e = center[0] + size * np.sin(theta)
    n = center[1] + size * np.sin(theta) * np.cos(theta)
    u = center[2]
    
    return (e, n, u)


def add_noise(
    value: float,
    std_dev: float = 0.1
) -> float:
    """Add Gaussian noise to a value."""
    return value + np.random.normal(0, std_dev)


def add_position_noise(
    position: np.ndarray,
    std_dev: float = 1.0
) -> np.ndarray:
    """Add Gaussian noise to a position."""
    return position + np.random.normal(0, std_dev, size=position.shape)
