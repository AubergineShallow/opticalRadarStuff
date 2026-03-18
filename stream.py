import io
import time
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
import cv2
from picamera2 import Picamera2

print("Initializing Camera...")
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={'size': (640, 480), 'format': 'RGB888'})
picam2.configure(config)
picam2.start()
time.sleep(1)
print("Camera started.")

class StreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                print(f"Client connected: {self.client_address}")
                while True:
                    img = picam2.capture_array()
                    # picamera2 returns RGB, opencv expects BGR for typical operations, 
                    # but imencode to jpg works fine if we convert it first
                    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    ret, buffer = cv2.imencode('.jpg', img_bgr)
                    frame = buffer.tobytes()
                    
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                print(f"Removed streaming client {self.client_address}: {str(e)}")
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

address = ('', 8000)
server = StreamingServer(address, StreamingHandler)
print("Streaming server started on port 8000")
print("Open http://192.168.1.23:8000 in your browser to view the live feed.")
try:
    server.serve_forever()
except KeyboardInterrupt:
    picam2.stop()
    picam2.close()
