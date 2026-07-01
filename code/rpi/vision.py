
"""
vision.py
PURPOSE: Camera capture and motion detection for Raspberry Pi.
"""

import time
import numpy as np
from typing import List, Tuple, Optional, Callable
from dataclasses import dataclass


@dataclass
class MotionVector:
    """Detected motion vector."""
    azimuth: float  # Degrees [0, 360)
    elevation: float  # Degrees [-90, 90]
    intensity: int  # [0, 255]
    class_id: int = 0  # Object class
    angular_size: float = 0.0  # Degrees [0, 180] — detection's apparent size


@dataclass
class VisionConfig:
    """Vision system configuration."""
    camera_index: int = 0
    resolution: Tuple[int, int] = (640, 480)
    fps: int = 30
    motion_threshold: int = 25
    min_area: int = 500
    blur_size: int = 21
    
    # Field of view
    horizontal_fov: float = 62.2  # Degrees (Pi Camera v2)
    vertical_fov: float = 48.8


class VisionSystem:
    """
    Camera capture and motion detection.
    
    1. Capture frames
    2. Detect motion via frame differencing
    3. Convert pixel positions to angles
    4. Return motion vectors
    """
    
    def __init__(self, config: Optional[VisionConfig] = None):
        """
        Initialize vision system.
        
        Args:
            config: Vision configuration
        """
        self.config = config or VisionConfig()
        
        self._camera = None
        self._prev_frame = None
        self._running = False
        
        # Try to import OpenCV
        try:
            import cv2
            self._cv2 = cv2
            self._enabled = True
        except ImportError:
            self._cv2 = None
            self._enabled = False
            print("Warning: OpenCV not available, using mock vision")
    
    def start(self) -> bool:
        """
        Start the camera.
        
        Returns:
            True if successful
        """
        if not self._enabled:
            self._running = True
            return True
        
        try:
            self._camera = self._cv2.VideoCapture(self.config.camera_index)
            self._camera.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.config.resolution[0])
            self._camera.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.config.resolution[1])
            self._camera.set(self._cv2.CAP_PROP_FPS, self.config.fps)
            
            self._running = self._camera.isOpened()
            return self._running
        except Exception as e:
            print(f"Camera start failed: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the camera."""
        self._running = False
        if self._camera:
            self._camera.release()
            self._camera = None
        self._prev_frame = None
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame.
        
        Returns:
            Frame as numpy array or None
        """
        if not self._enabled:
            # Return mock frame
            return np.random.randint(0, 255, (*self.config.resolution[::-1], 3), dtype=np.uint8)
        
        if not self._camera:
            return None
        
        ret, frame = self._camera.read()
        return frame if ret else None
    
    def detect_motion(self, frame: np.ndarray) -> List[MotionVector]:
        """
        Detect motion in frame.
        
        Args:
            frame: Current frame
        
        Returns:
            List of motion vectors
        """
        if not self._enabled:
            return self._mock_detect_motion()
        
        cv2 = self._cv2
        
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (self.config.blur_size, self.config.blur_size), 0)
        
        # Initialize if first frame
        if self._prev_frame is None:
            self._prev_frame = gray
            return []
        
        # Frame difference
        diff = cv2.absdiff(self._prev_frame, gray)
        self._prev_frame = gray
        
        # Threshold
        _, thresh = cv2.threshold(diff, self.config.motion_threshold, 255, cv2.THRESH_BINARY)
        
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        vectors = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.config.min_area:
                continue
            
            # Get centroid
            M = cv2.moments(contour)
            if M["m00"] == 0:
                continue
            
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            # Get bounding box for angular size calculation
            x, y, w, h = cv2.boundingRect(contour)

            # Use the max of width/height for a conservative "cone" size
            max_dim = max(w, h)
            # Rough angular size based on horizontal FOV
            angular_size = (max_dim / self.config.resolution[0]) * self.config.horizontal_fov

            # Convert pixel to angles
            azimuth, elevation = self._pixel_to_angles(cx, cy)
            
            # Intensity based on area
            intensity = min(255, int(area / 100))
            
            vectors.append(MotionVector(
                azimuth=azimuth,
                elevation=elevation,
                intensity=intensity,
                angular_size=angular_size
            ))
        
        return vectors
    
    def _mock_detect_motion(self) -> List[MotionVector]:
        """Generate mock motion vectors for testing."""
        # Simulate occasional detections
        if np.random.random() < 0.3:
            return [
                MotionVector(
                    azimuth=np.random.uniform(0, 360),
                    elevation=np.random.uniform(-45, 45),
                    intensity=np.random.randint(50, 200),
                    angular_size=np.random.uniform(1.0, 10.0)
                )
            ]
        return []
    
    def _pixel_to_angles(self, px: int, py: int) -> Tuple[float, float]:
        """
        Convert pixel coordinates to azimuth/elevation.
        
        Args:
            px: Pixel X (0 = left)
            py: Pixel Y (0 = top)
        
        Returns:
            Tuple of (azimuth, elevation) in degrees
        """
        width, height = self.config.resolution
        
        # Normalize to [-0.5, 0.5]
        nx = (px / width) - 0.5
        ny = 0.5 - (py / height)  # Invert Y (image Y increases downward)
        
        # Convert to angles
        azimuth = nx * self.config.horizontal_fov
        elevation = ny * self.config.vertical_fov
        
        return (azimuth, elevation)
    
    def get_frame_and_vectors(self) -> Tuple[Optional[np.ndarray], List[MotionVector]]:
        """
        Capture frame and detect motion in one call.
        
        Returns:
            Tuple of (frame, vectors)
        """
        frame = self.capture_frame()
        if frame is None:
            return None, []
        
        vectors = self.detect_motion(frame)
        return frame, vectors
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
