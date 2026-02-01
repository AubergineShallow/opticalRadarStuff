"""
calibration.py
PURPOSE: Solve alignment errors with validation steps.
"""

import time
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from math_utils.quaternion import from_axis_angle, multiply, normalize, angle_between

# Import ValidationResult at module level to avoid deferred imports
# Note: This module has its own _LocalCalibrationObservation which differs from
# validation.CalibrationObservation - the local version is optimized for the solver
try:
    from .validation import ValidationResult
except ImportError:
    from server.validation import ValidationResult


@dataclass
class _LocalCalibrationObservation:
    """
    Internal observation for calibration solving.
    
    Note: This differs from validation.CalibrationObservation which tracks
    residuals for quality metrics. This version is optimized for the solver.
    """
    camera_id: str
    ray_direction: np.ndarray
    target_position: np.ndarray
    camera_position: np.ndarray
    timestamp: float


@dataclass
class CalibrationResult:
    """Result of calibration solve."""
    camera_id: str
    correction_quaternion: Tuple[float, float, float, float]
    correction_degrees: float
    residual_before: float
    residual_after: float
    approved: bool = False
    reason: str = ""


class Calibrator:
    """
    Self-calibration solver with validation.
    
    1. ACCUMULATE: Collect (ray, voxel) pairs
    2. SOLVE: Least squares optimization
    3. VALIDATE: Check with validator
    4. APPLY: Blend correction
    """
    
    def __init__(
        self,
        buffer_size: int = 2000,
        solve_interval: float = 10.0,
        blend_factor: float = 0.1,
        validator = None
    ):
        """
        Initialize calibrator.
        
        Args:
            buffer_size: Max observations per camera
            solve_interval: Seconds between solves
            blend_factor: Correction blending factor (0-1)
            validator: CalibrationValidator instance (optional)
        """
        self.buffer_size = buffer_size
        self.solve_interval = solve_interval
        self.blend_factor = blend_factor
        self.validator = validator
        
        # Observation buffers per camera
        self._buffers: Dict[str, deque] = {}
        
        # Current calibration offsets
        self._offsets: Dict[str, Tuple[float, float, float, float]] = {}
        
        # Last solve time per camera
        self._last_solve: Dict[str, float] = {}
    
    def add_observation(
        self,
        camera_id: str,
        ray_direction: np.ndarray,
        target_position: np.ndarray,
        camera_position: np.ndarray
    ) -> None:
        """
        Add calibration observation.
        
        Args:
            camera_id: Camera ID
            ray_direction: Ray direction (unit vector)
            target_position: Hot voxel position
            camera_position: Camera position
        """
        if camera_id not in self._buffers:
            self._buffers[camera_id] = deque(maxlen=self.buffer_size)
        
        obs = _LocalCalibrationObservation(
            camera_id=camera_id,
            ray_direction=np.array(ray_direction),
            target_position=np.array(target_position),
            camera_position=np.array(camera_position),
            timestamp=time.time()
        )
        
        self._buffers[camera_id].append(obs)
        
        # Also send to validator if present
        if self.validator:
            self.validator.add_observation(
                camera_id,
                camera_position,
                ray_direction,
                target_position
            )
    
    def should_solve(self, camera_id: str) -> bool:
        """Check if it's time to solve for this camera."""
        if camera_id not in self._buffers:
            return False
        
        if len(self._buffers[camera_id]) < 100:
            return False
        
        now = time.time()
        last = self._last_solve.get(camera_id, 0)
        
        return (now - last) >= self.solve_interval
    
    def solve(self, camera_id: str) -> Optional[CalibrationResult]:
        """
        Solve for calibration correction.
        
        Uses gradient descent to find rotation that minimizes
        ray-to-target distance.
        
        Args:
            camera_id: Camera ID
        
        Returns:
            CalibrationResult or None
        """
        if camera_id not in self._buffers:
            return None
        
        observations = list(self._buffers[camera_id])
        if len(observations) < 50:
            return None
        
        self._last_solve[camera_id] = time.time()
        
        # Calculate current residual
        residual_before = self._calculate_residual(observations)
        
        # Gradient descent for rotation axis/angle
        best_correction = (1.0, 0.0, 0.0, 0.0)  # Identity
        best_residual = residual_before
        
        # Try small rotations around each axis
        for axis in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
            for angle in [-2, -1, -0.5, 0.5, 1, 2]:  # Degrees
                correction = from_axis_angle(axis, angle)
                
                residual = self._calculate_residual(observations, correction)
                
                if residual < best_residual:
                    best_correction = correction
                    best_residual = residual
        
        # Calculate correction magnitude
        correction_degrees = angle_between(
            (1, 0, 0, 0),
            best_correction
        )
        
        result = CalibrationResult(
            camera_id=camera_id,
            correction_quaternion=best_correction,
            correction_degrees=correction_degrees,
            residual_before=residual_before,
            residual_after=best_residual
        )
        
        # Validate if validator present
        if self.validator:
            vresult, reason = self.validator.validate_correction(
                camera_id, correction_degrees
            )
            result.approved = (vresult == ValidationResult.APPROVE)
            result.reason = reason
        else:
            # Auto-approve small corrections
            result.approved = correction_degrees < 5.0
            result.reason = "OK" if result.approved else "Too large (no validator)"
        
        return result
    
    def _calculate_residual(
        self,
        observations: List[_LocalCalibrationObservation],
        correction: Optional[Tuple[float, float, float, float]] = None
    ) -> float:
        """Calculate mean residual with optional correction applied."""
        from math_utils.quaternion import rotate_vector
        
        total = 0.0
        count = 0
        
        for obs in observations:
            direction = obs.ray_direction
            
            if correction:
                direction = np.array(rotate_vector(tuple(direction), correction))
            
            # Distance from ray to target
            v = obs.target_position - obs.camera_position
            t = np.dot(v, direction)
            closest = obs.camera_position + max(0, t) * direction
            distance = np.linalg.norm(obs.target_position - closest)
            
            total += distance
            count += 1
        
        return total / max(1, count)
    
    def apply_correction(self, result: CalibrationResult) -> bool:
        """
        Apply calibration correction.
        
        Args:
            result: CalibrationResult from solve()
        
        Returns:
            True if applied
        """
        if not result.approved:
            return False
        
        camera_id = result.camera_id
        
        # Get current offset
        current = self._offsets.get(camera_id, (1.0, 0.0, 0.0, 0.0))
        
        # Blend new correction
        # For simplicity, we'll just use SLERP-style blending
        from math_utils.quaternion import slerp
        
        # Compose corrections
        new_offset = multiply(result.correction_quaternion, current)
        
        # Blend with factor
        blended = slerp(current, new_offset, self.blend_factor)
        
        self._offsets[camera_id] = normalize(blended)
        
        return True
    
    def get_offset(
        self,
        camera_id: str
    ) -> Tuple[float, float, float, float]:
        """Get current calibration offset for camera."""
        return self._offsets.get(camera_id, (1.0, 0.0, 0.0, 0.0))
    
    def process(self) -> List[CalibrationResult]:
        """
        Process calibration for all cameras that need it.
        
        Returns:
            List of results
        """
        results = []
        
        for camera_id in list(self._buffers.keys()):
            if self.should_solve(camera_id):
                result = self.solve(camera_id)
                if result:
                    if result.approved:
                        self.apply_correction(result)
                    results.append(result)
        
        return results
