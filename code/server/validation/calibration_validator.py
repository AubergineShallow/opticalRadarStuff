
"""
calibration_validator.py
PURPOSE: Validate that calibration is improving, not degrading the system.
"""

import time
import math
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque


class ConvergenceState(Enum):
    """Calibration convergence state."""
    UNKNOWN = "unknown"
    CONVERGING = "converging"
    STABLE = "stable"
    DIVERGING = "diverging"
    OSCILLATING = "oscillating"


class ValidationResult(Enum):
    """Calibration correction validation result."""
    APPROVE = "approve"
    REJECT = "reject"


@dataclass
class CalibrationObservation:
    """Single calibration observation."""
    camera_id: str
    ray_origin: np.ndarray
    ray_direction: np.ndarray
    voxel_position: np.ndarray
    timestamp: float
    residual: float = 0.0


@dataclass
class CameraCalibrationState:
    """Calibration state for a single camera."""
    camera_id: str
    observations: deque = field(default_factory=lambda: deque(maxlen=2000))
    correction_history: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Metrics
    mean_residual: float = 0.0
    std_residual: float = 0.0
    convergence: ConvergenceState = ConvergenceState.UNKNOWN
    score: float = 50.0
    confidence: float = 1.0


class CalibrationValidator:
    """
    Validate calibration corrections before applying.
    
    Methods:
        1. Residual error tracking
        2. Detection consistency (multi-camera)
        3. Ground truth comparison (if available)
        4. Convergence monitoring
    """
    
    def __init__(
        self,
        max_correction_degrees: float = 15.0,
        min_observations: int = 100,
        residual_window: int = 500
    ):
        """
        Initialize validator.
        
        Args:
            max_correction_degrees: Maximum allowed single correction
            min_observations: Minimum observations before validation
            residual_window: Window size for residual calculation
        """
        self.max_correction = max_correction_degrees
        self.min_observations = min_observations
        self.residual_window = residual_window
        
        self._cameras: Dict[str, CameraCalibrationState] = {}
    
    def _get_camera_state(self, camera_id: str) -> CameraCalibrationState:
        """Get or create camera state."""
        if camera_id not in self._cameras:
            self._cameras[camera_id] = CameraCalibrationState(camera_id=camera_id)
        return self._cameras[camera_id]
    
    def add_observation(
        self,
        camera_id: str,
        ray_origin: np.ndarray,
        ray_direction: np.ndarray,
        voxel_position: np.ndarray
    ) -> float:
        """
        Add calibration observation.
        
        Args:
            camera_id: Camera ID
            ray_origin: Ray origin (camera position)
            ray_direction: Ray direction (unit vector)
            voxel_position: Hot voxel center position
        
        Returns:
            Residual distance
        """
        # Calculate ray-to-point distance
        residual = self._point_to_ray_distance(
            voxel_position, ray_origin, ray_direction
        )
        
        obs = CalibrationObservation(
            camera_id=camera_id,
            ray_origin=ray_origin,
            ray_direction=ray_direction,
            voxel_position=voxel_position,
            timestamp=time.time(),
            residual=residual
        )
        
        state = self._get_camera_state(camera_id)
        state.observations.append(obs)
        
        # Update running statistics
        self._update_statistics(state)
        
        return residual
    
    def _point_to_ray_distance(
        self,
        point: np.ndarray,
        ray_origin: np.ndarray,
        ray_direction: np.ndarray
    ) -> float:
        """Calculate distance from point to ray."""
        # Vector from ray origin to point
        v = point - ray_origin
        
        # Project onto ray direction
        t = np.dot(v, ray_direction)
        
        # Closest point on ray
        if t < 0:
            closest = ray_origin
        else:
            closest = ray_origin + t * ray_direction
        
        return float(np.linalg.norm(point - closest))
    
    def _update_statistics(self, state: CameraCalibrationState) -> None:
        """Update running statistics for camera."""
        if len(state.observations) < 10:
            return
        
        # Get recent residuals
        recent = list(state.observations)[-self.residual_window:]
        residuals = [obs.residual for obs in recent]
        
        state.mean_residual = float(np.mean(residuals))
        state.std_residual = float(np.std(residuals))
    
    def calculate_score(self, camera_id: str) -> float:
        """
        Calculate calibration quality score (0-100).
        
        Components:
            - Residual error (40%)
            - Consistency (30%)
            - Convergence (20%)
            - Detection rate (10%)
        """
        state = self._get_camera_state(camera_id)
        
        if len(state.observations) < self.min_observations:
            return 50.0  # Not enough data
        
        # Residual score (lower is better)
        # 0m = 100%, 10m = 0%
        residual_score = max(0, 1.0 - state.mean_residual / 10.0)
        
        # Consistency score (lower std is better)
        # 0m std = 100%, 5m std = 0%
        consistency_score = max(0, 1.0 - state.std_residual / 5.0)
        
        # Convergence score
        convergence_score = {
            ConvergenceState.STABLE: 1.0,
            ConvergenceState.CONVERGING: 0.8,
            ConvergenceState.UNKNOWN: 0.5,
            ConvergenceState.OSCILLATING: 0.3,
            ConvergenceState.DIVERGING: 0.0
        }.get(state.convergence, 0.5)
        
        # Detection rate score (based on observation frequency)
        recent = list(state.observations)[-100:]
        if len(recent) >= 2:
            dt = recent[-1].timestamp - recent[0].timestamp
            rate = len(recent) / max(1, dt)
            detection_score = min(1.0, rate / 30.0)  # 30 pps = 100%
        else:
            detection_score = 0.5
        
        # Weighted score
        score = (
            40 * residual_score +
            30 * consistency_score +
            20 * convergence_score +
            10 * detection_score
        )
        
        state.score = score
        return score
    
    def track_convergence(
        self,
        camera_id: str,
        correction_magnitude: float
    ) -> ConvergenceState:
        """
        Track convergence based on correction history.
        
        Args:
            camera_id: Camera ID
            correction_magnitude: Magnitude of latest correction
        
        Returns:
            Current convergence state
        """
        state = self._get_camera_state(camera_id)
        state.correction_history.append(correction_magnitude)
        
        if len(state.correction_history) < 10:
            state.convergence = ConvergenceState.UNKNOWN
            return state.convergence
        
        recent = list(state.correction_history)[-20:]
        
        # Calculate trend
        decreasing = 0
        increasing = 0
        oscillations = 0
        
        for i in range(1, len(recent)):
            if recent[i] < recent[i-1] * 0.95:
                decreasing += 1
            elif recent[i] > recent[i-1] * 1.05:
                increasing += 1
            
            if i >= 2:
                if (recent[i] > recent[i-1]) != (recent[i-1] > recent[i-2]):
                    oscillations += 1
        
        # Determine state
        if oscillations > len(recent) * 0.6:
            state.convergence = ConvergenceState.OSCILLATING
        elif decreasing > increasing * 2:
            state.convergence = ConvergenceState.CONVERGING
        elif increasing > decreasing * 2:
            state.convergence = ConvergenceState.DIVERGING
        elif max(recent) < 0.5:  # Small corrections
            state.convergence = ConvergenceState.STABLE
        else:
            state.convergence = ConvergenceState.UNKNOWN
        
        return state.convergence
    
    def validate_correction(
        self,
        camera_id: str,
        correction_degrees: float
    ) -> Tuple[ValidationResult, str]:
        """
        Validate a proposed calibration correction.
        
        Args:
            camera_id: Camera ID
            correction_degrees: Magnitude in degrees
        
        Returns:
            Tuple of (result, reason)
        """
        state = self._get_camera_state(camera_id)
        
        # Check 1: Maximum correction
        if correction_degrees > self.max_correction:
            return (
                ValidationResult.REJECT,
                f"Correction too large: {correction_degrees:.1f}° > {self.max_correction}°"
            )
        
        # Check 2: Minimum observations
        if len(state.observations) < self.min_observations:
            return (
                ValidationResult.REJECT,
                f"Insufficient observations: {len(state.observations)} < {self.min_observations}"
            )
        
        # Check 3: Divergence detection
        self.track_convergence(camera_id, correction_degrees)
        if state.convergence == ConvergenceState.DIVERGING:
            # Reduce confidence
            state.confidence *= 0.9
            if state.confidence < 0.3:
                return (
                    ValidationResult.REJECT,
                    "Calibration diverging, confidence too low"
                )
        
        # Check 4: Score threshold
        score = self.calculate_score(camera_id)
        if score < 20 and correction_degrees > 5:
            return (
                ValidationResult.REJECT,
                f"Score too low ({score:.0f}) for large correction"
            )
        
        return (ValidationResult.APPROVE, "OK")
    
    def generate_report(self) -> str:
        """Generate human-readable calibration report."""
        lines = [
            "Calibration Quality Report",
            "=" * 40,
            ""
        ]
        
        for camera_id in sorted(self._cameras.keys()):
            state = self._cameras[camera_id]
            score = self.calculate_score(camera_id)
            
            # Rating
            if score >= 80:
                rating = "EXCELLENT"
            elif score >= 60:
                rating = "GOOD"
            elif score >= 40:
                rating = "FAIR"
            else:
                rating = "POOR"
            
            lines.append(f"CAMERA: {camera_id}")
            lines.append(f"Overall Score: {score:.0f}/100 ({rating})")
            lines.append(f"")
            lines.append(f"Residual Error: {state.mean_residual:.1f}m ± {state.std_residual:.1f}m")
            lines.append(f"Convergence: {state.convergence.value}")
            lines.append(f"Confidence: {state.confidence:.0%}")
            lines.append(f"Observations: {len(state.observations)}")
            lines.append("")
        
        return '\n'.join(lines)
    
    def reset(self, camera_id: Optional[str] = None) -> None:
        """Reset calibration state."""
        if camera_id:
            if camera_id in self._cameras:
                del self._cameras[camera_id]
        else:
            self._cameras.clear()
