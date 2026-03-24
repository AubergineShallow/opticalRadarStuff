"""
vision.py
PURPOSE: Camera capture and motion detection for Raspberry Pi.
"""

import time
import math
import numpy as np
from typing import List, Tuple, Optional, Callable
from dataclasses import dataclass


@dataclass
class MotionVector:
    """Detected motion vector."""
    azimuth: float  # Degrees [0, 360)
    elevation: float = 0.0  # Degrees — always 0 in 2D fork
    intensity: int = 0  # [0, 255]
    class_id: int = 0  # Object class


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
        self._picam2 = None
        self._prev_frame = None
        self._running = False
        self._backend = None  # 'picamera2', 'opencv', or None
        
        # Precompute trigonometric constants for rectilinear projection
        self._half_h_tan = math.tan(math.radians(self.config.horizontal_fov / 2))
        self._half_v_tan = math.tan(math.radians(self.config.vertical_fov / 2))

        # Try to import OpenCV
        try:
            import cv2
            self._cv2 = cv2
        except ImportError:
            self._cv2 = None
        
        # Try to import picamera2
        try:
            from picamera2 import Picamera2
            self._Picamera2 = Picamera2
        except ImportError:
            self._Picamera2 = None
        
        self._enabled = (self._cv2 is not None) or (self._Picamera2 is not None)
        if not self._enabled:
            print("Warning: Neither OpenCV nor picamera2 available, using mock vision")
    
    def start(self) -> bool:
        """
        Start the camera.
        
        Tries picamera2 first (native libcamera support), then falls back
        to OpenCV V4L2.
        
        Returns:
            True if successful
        """
        if not self._enabled:
            self._running = True
            return True
        
        # Try picamera2 first (best support on modern RPi OS)
        if self._Picamera2 is not None:
            try:
                self._picam2 = self._Picamera2()
                cam_config = self._picam2.create_preview_configuration(
                    main={"size": self.config.resolution, "format": "RGB888"}
                )
                self._picam2.configure(cam_config)
                self._picam2.start()
                self._backend = 'picamera2'
                self._running = True
                print(f"Camera started via picamera2 at {self.config.resolution}")
                return True
            except Exception as e:
                print(f"picamera2 start failed: {e}, trying OpenCV...")
                self._picam2 = None
        
        # Fallback to OpenCV V4L2
        if self._cv2 is not None:
            try:
                self._camera = self._cv2.VideoCapture(self.config.camera_index, self._cv2.CAP_V4L2)
                self._camera.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.config.resolution[0])
                self._camera.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.config.resolution[1])
                self._camera.set(self._cv2.CAP_PROP_FPS, self.config.fps)
                
                if self._camera.isOpened():
                    self._backend = 'opencv'
                    self._running = True
                    print(f"Camera started via OpenCV V4L2 at {self.config.resolution}")
                    return True
                else:
                    self._camera.release()
                    self._camera = None
            except Exception as e:
                print(f"OpenCV camera start failed: {e}")
        
        print("ERROR: All camera backends failed.")
        return False
    
    def stop(self) -> None:
        """Stop the camera."""
        self._running = False
        if self._picam2:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
            self._picam2 = None
        if self._camera:
            self._camera.release()
            self._camera = None
        self._prev_frame = None
        self._backend = None
    
    def capture_frame(self, bgr_out: bool = True) -> Optional[np.ndarray]:
        """
        Capture a single frame.
        
        Args:
            bgr_out: If True, returns BGR frame. If False, avoids converting RGB to BGR if possible.

        Returns:
            Frame as numpy array or None
        """
        if not self._enabled:
            # Return mock frame
            return np.random.randint(0, 255, (*self.config.resolution[::-1], 3), dtype=np.uint8)
        
        if self._backend == 'picamera2' and self._picam2:
            try:
                # picamera2 returns RGB
                frame_rgb = self._picam2.capture_array()
                if bgr_out and self._cv2 is not None:
                    return self._cv2.cvtColor(frame_rgb, self._cv2.COLOR_RGB2BGR)
                return frame_rgb
            except Exception:
                return None
        
        if self._backend == 'opencv' and self._camera:
            ret, frame = self._camera.read()
            if not ret:
                return None
            if not bgr_out and self._cv2 is not None:
                # OpenCV returns BGR, convert to RGB if not requesting BGR
                return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
            return frame
        
        return None
    
    def detect_motion(self, frame: np.ndarray, is_bgr: bool = True) -> List[MotionVector]:
        """
        Detect motion in frame.
        
        Args:
            frame: Current frame
            is_bgr: Whether the input frame is BGR format
        
        Returns:
            List of motion vectors
        """
        if not self._enabled:
            return self._mock_detect_motion()
        
        cv2 = self._cv2
        
        # Convert to grayscale
        if is_bgr:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

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
            
            # Convert pixel to angles
            azimuth, elevation = self._pixel_to_angles(cx, cy)
            
            # Intensity based on area
            intensity = min(255, int(area / 100))
            
            vectors.append(MotionVector(
                azimuth=azimuth,
                elevation=0.0,  # 2D fork: no elevation
                intensity=intensity
            ))
        
        return vectors
    
    def _mock_detect_motion(self) -> List[MotionVector]:
        """Generate mock motion vectors for testing."""
        # Simulate occasional detections
        if np.random.random() < 0.3:
            return [
                MotionVector(
                    azimuth=np.random.uniform(0, 360),
                    elevation=0.0,  # 2D fork: no elevation
                    intensity=np.random.randint(50, 200)
                )
            ]
        return []
    
    def _pixel_to_angles(self, px: int, py: int) -> Tuple[float, float]:
        """
        Convert pixel coordinates to azimuth/elevation using
        rectilinear (pinhole camera) projection model.
        
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
        
        # Rectilinear projection: atan(nx * 2 * tan(fov/2))
        # This is the standard pinhole camera model, correcting for
        # the ~2.8° error at edges that the linear approximation introduces.
        azimuth = math.degrees(math.atan(2 * nx * self._half_h_tan))
        elevation = math.degrees(math.atan(2 * ny * self._half_v_tan))
        
        return (azimuth, elevation)
    
    def get_frame_and_vectors(self, bgr_out: bool = True) -> Tuple[Optional[np.ndarray], List[MotionVector]]:
        """
        Capture frame and detect motion in one call.
        
        Args:
            bgr_out: Whether to return the frame in BGR format

        Returns:
            Tuple of (frame, vectors)
        """
        frame = self.capture_frame(bgr_out=bgr_out)
        if frame is None:
            return None, []
        
        vectors = self.detect_motion(frame, is_bgr=bgr_out)
        return frame, vectors
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
