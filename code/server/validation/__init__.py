
"""Validation subsystem - calibration validation and ground truth comparison."""

from .calibration_validator import (
    CalibrationValidator, CalibrationObservation, CameraCalibrationState,
    ConvergenceState, ValidationResult
)
from .ground_truth import (
    GroundTruthValidator, GroundTruthEntry, GroundTruthSource,
    DetectionComparison, ValidationStats
)

__all__ = [
    # Calibration
    'CalibrationValidator', 'CalibrationObservation', 'CameraCalibrationState',
    'ConvergenceState', 'ValidationResult',
    
    # Ground Truth
    'GroundTruthValidator', 'GroundTruthEntry', 'GroundTruthSource',
    'DetectionComparison', 'ValidationStats',
]
