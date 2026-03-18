#!/usr/bin/env python3
"""Quick camera diagnostic script for Raspberry Pi."""
import os, sys

print("=== Camera Diagnostic ===")

# Check /dev/video devices
print("\n1. Video devices:")
for f in sorted(os.listdir("/dev")):
    if f.startswith("video"):
        print(f"   /dev/{f}")

# Check picamera2
print("\n2. Picamera2:")
try:
    from picamera2 import Picamera2
    info = Picamera2.global_camera_info()
    print(f"   Available: YES")
    print(f"   Cameras: {info}")
except ImportError:
    print("   Available: NO (not installed)")
except Exception as e:
    print(f"   Error: {e}")

# Check OpenCV backends
print("\n3. OpenCV:")
try:
    import cv2
    print(f"   Version: {cv2.__version__}")
    print(f"   Build info backends: {cv2.getBuildInformation().split('Video I/O')[1].split('Parallel')[0][:500] if 'Video I/O' in cv2.getBuildInformation() else 'N/A'}")
    
    # Try opening camera with different backends
    for idx in [0, 1]:
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        print(f"   /dev/video{idx} V4L2: opened={cap.isOpened()}")
        if cap.isOpened():
            ret, frame = cap.read()
            print(f"   /dev/video{idx} V4L2: read={ret}, shape={frame.shape if ret else 'N/A'}")
        cap.release()
except ImportError:
    print("   Available: NO")
except Exception as e:
    print(f"   Error: {e}")

# Check libcamera
print("\n4. libcamera-hello:")
ret = os.system("libcamera-hello --list-cameras 2>&1 | head -20")

print("\n=== Done ===")
