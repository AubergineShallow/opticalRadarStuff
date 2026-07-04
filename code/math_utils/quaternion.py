"""
quaternion.py
PURPOSE: Math for describing rotations in 3D space.
"""

import math
from typing import Tuple
import numpy as np


def normalize(q: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """
    Normalize quaternion to unit length.
    
    Args:
        q: Quaternion [w, x, y, z]
    
    Returns:
        Normalized quaternion [w, x, y, z]
    """
    w, x, y, z = q
    mag = math.sqrt(w*w + x*x + y*y + z*z)
    if mag < 1e-10:
        return (1.0, 0.0, 0.0, 0.0)  # Identity
    return (w/mag, x/mag, y/mag, z/mag)


def multiply(q1: Tuple[float, float, float, float], 
             q2: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """
    Multiply two quaternions (q1 * q2).
    
    Quaternion multiplication is NOT commutative.
    q1 * q2 applies q2 first, then q1.
    
    Args:
        q1, q2: Quaternions [w, x, y, z]
    
    Returns:
        Product quaternion [w, x, y, z]
    """
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    
    w = w1*w2 - x1*x2 - y1*y2 - z1*z2
    x = w1*x2 + x1*w2 + y1*z2 - z1*y2
    y = w1*y2 - x1*z2 + y1*w2 + z1*x2
    z = w1*z2 + x1*y2 - y1*x2 + z1*w2
    
    return (w, x, y, z)


def conjugate(q: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """
    Compute conjugate (inverse for unit quaternions).
    
    Args:
        q: Quaternion [w, x, y, z]
    
    Returns:
        Conjugate [w, -x, -y, -z]
    """
    return (q[0], -q[1], -q[2], -q[3])


def rotate_vector(
    v: Tuple[float, float, float],
    q: Tuple[float, float, float, float]
) -> Tuple[float, float, float]:
    """
    Rotate a 3D vector by a quaternion.
    
    v' = q * v * q^(-1)
    
    Args:
        v: Vector [x, y, z]
        q: Rotation quaternion [w, x, y, z]
    
    Returns:
        Rotated vector [x, y, z]
    """
    # Convert vector to quaternion
    v_quat = (0.0, v[0], v[1], v[2])
    
    # q * v * q^(-1)
    q_conj = conjugate(q)
    result = multiply(multiply(q, v_quat), q_conj)
    
    return (result[1], result[2], result[3])


def from_euler(roll: float, pitch: float, yaw: float) -> Tuple[float, float, float, float]:
    """
    Create quaternion from Euler angles (ZYX convention).
    
    Args:
        roll: Rotation around X axis (degrees)
        pitch: Rotation around Y axis (degrees)
        yaw: Rotation around Z axis (degrees)
    
    Returns:
        Quaternion [w, x, y, z]
    """
    # Convert to radians and half angles
    roll_rad = math.radians(roll) / 2
    pitch_rad = math.radians(pitch) / 2
    yaw_rad = math.radians(yaw) / 2
    
    cr = math.cos(roll_rad)
    sr = math.sin(roll_rad)
    cp = math.cos(pitch_rad)
    sp = math.sin(pitch_rad)
    cy = math.cos(yaw_rad)
    sy = math.sin(yaw_rad)
    
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    
    return normalize((w, x, y, z))


def to_euler(q: Tuple[float, float, float, float]) -> Tuple[float, float, float]:
    """
    Convert quaternion to Euler angles (ZYX convention).
    
    Args:
        q: Quaternion [w, x, y, z]
    
    Returns:
        Tuple of (roll, pitch, yaw) in degrees
    """
    w, x, y, z = q
    
    # Roll (X)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    
    # Pitch (Y) - handle gimbal lock
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)
    
    # Yaw (Z)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


def from_axis_angle(
    axis: Tuple[float, float, float],
    angle: float
) -> Tuple[float, float, float, float]:
    """
    Create quaternion from axis-angle representation.
    
    Args:
        axis: Unit vector [x, y, z] (rotation axis)
        angle: Rotation angle in degrees
    
    Returns:
        Quaternion [w, x, y, z]
    """
    # Normalize axis
    ax, ay, az = axis
    mag = math.sqrt(ax*ax + ay*ay + az*az)
    if mag < 1e-10:
        return (1.0, 0.0, 0.0, 0.0)
    
    ax, ay, az = ax/mag, ay/mag, az/mag
    
    half_angle = math.radians(angle) / 2
    sin_half = math.sin(half_angle)
    
    return (math.cos(half_angle), ax * sin_half, ay * sin_half, az * sin_half)


def to_axis_angle(q: Tuple[float, float, float, float]) -> Tuple[Tuple[float, float, float], float]:
    """
    Convert quaternion to axis-angle representation.
    
    Args:
        q: Quaternion [w, x, y, z]
    
    Returns:
        Tuple of (axis [x, y, z], angle in degrees)
    """
    q = normalize(q)
    w, x, y, z = q

    # Canonicalise to the w >= 0 hemisphere (q and -q are the same rotation).
    # Using abs(w) for the angle while keeping the raw x/y/z flipped the axis
    # sign for negative-w quaternions, returning a different rotation.
    if w < 0:
        w, x, y, z = -w, -x, -y, -z

    angle = 2 * math.acos(min(1.0, w))

    sin_half = math.sin(angle / 2)
    if sin_half < 1e-10:
        return ((1.0, 0.0, 0.0), 0.0)

    axis = (x / sin_half, y / sin_half, z / sin_half)

    return (axis, math.degrees(angle))


def slerp(
    q1: Tuple[float, float, float, float],
    q2: Tuple[float, float, float, float],
    t: float
) -> Tuple[float, float, float, float]:
    """
    Spherical linear interpolation between two quaternions.
    
    Args:
        q1: Start quaternion [w, x, y, z]
        q2: End quaternion [w, x, y, z]
        t: Interpolation factor [0, 1]
    
    Returns:
        Interpolated quaternion [w, x, y, z]
    """
    q1 = normalize(q1)
    q2 = normalize(q2)
    
    # Compute dot product
    dot = q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3]
    
    # If dot is negative, negate one quaternion (shorter path)
    if dot < 0:
        q2 = (-q2[0], -q2[1], -q2[2], -q2[3])
        dot = -dot
    
    # Clamp dot to avoid numerical issues
    dot = min(1.0, dot)
    
    # If quaternions are very close, use linear interpolation
    if dot > 0.9995:
        result = tuple(q1[i] + t * (q2[i] - q1[i]) for i in range(4))
        return normalize(result)
    
    # SLERP formula
    theta_0 = math.acos(dot)
    theta = theta_0 * t
    
    sin_theta_0 = math.sin(theta_0)
    sin_theta = math.sin(theta)
    
    s1 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s2 = sin_theta / sin_theta_0
    
    return normalize((
        s1 * q1[0] + s2 * q2[0],
        s1 * q1[1] + s2 * q2[1],
        s1 * q1[2] + s2 * q2[2],
        s1 * q1[3] + s2 * q2[3]
    ))


def identity() -> Tuple[float, float, float, float]:
    """Return identity quaternion (no rotation)."""
    return (1.0, 0.0, 0.0, 0.0)


def angle_between(
    q1: Tuple[float, float, float, float],
    q2: Tuple[float, float, float, float]
) -> float:
    """
    Calculate angle between two quaternions.
    
    Args:
        q1, q2: Quaternions [w, x, y, z]
    
    Returns:
        Angle in degrees
    """
    q1 = normalize(q1)
    q2 = normalize(q2)
    
    dot = abs(q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3])
    dot = min(1.0, dot)
    
    return math.degrees(2 * math.acos(dot))
