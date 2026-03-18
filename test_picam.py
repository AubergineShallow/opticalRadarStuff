import time
from picamera2 import Picamera2

try:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={'size': (640, 480), 'format': 'RGB888'})
    picam2.configure(config)
    picam2.start()
    print("Camera started successfully.")
    
    # Wait a tiny bit for sensor to warm up
    time.sleep(1.0)
    
    print("Attempting to capture array...")
    img = picam2.capture_array()
    print(f"Captured array shape: {img.shape}")
    
    picam2.stop()
    picam2.close()
    print("Test finished successfully.")
    
except Exception as e:
    print(f"Error during picamera2 test: {e}")
