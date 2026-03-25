import socket
import select
import struct
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# ==============================
# NETWORK CONFIGURATION
# ==============================
# Listen for incoming legacy UDP traffic on all interfaces
LOCAL_IP = "0.0.0.0"
PORT_PIR = 20001        # Pi 1 (PIR + Camera)
PORT_TOUCH = 20002      # Pi 2 (Touch + DHT + Camera)
BUFFER_SIZE = 65536

# ==============================
# SERVER BACKEND CONFIGURATION
# ==============================
# Since this script runs ON the server, we forward to localhost
LOCAL_BACKEND_IP = "127.0.0.1"
SERVER_UDP_PORT = 5005     # MUST be 5005 for the Optical Radar backend

# Global variables to store the latest sensor state for packing
sensor_state = {
    "temperature_c": 0.0,
    "humidity_pct": 0.0,
    "pir_active": False,
    "fire_alarm": False,
    "distance_cm": 0.0
}

# Global variables to store the latest JPEG frames for the HTTP stream
latest_frame_pir = None
latest_frame_touch = None

# ==============================
# PROTOCOL TRANSLATOR
# ==============================
def pack_environment_packet(camera_id: str) -> bytes:
    """
    Packs the current sensor_state into the binary EnvironmentPacket (V3)
    expected by code/common/protocol.py
    """
    version = 3
    packet_type = 0x05  # PACKET_TYPE_ENVIRONMENT
    cam_id_bytes = camera_id.encode('utf-8')[:8].ljust(8, b'\x00')
    timestamp = time.time()

    # Pack: version(1) + type(1) + cam_id(8) + timestamp(8)
    data = struct.pack('>BB', version, packet_type)
    data += cam_id_bytes
    data += struct.pack('>d', timestamp)

    # Pack: temp(4) + humidity(4) + pir(1) + fire(1) + distance(4)
    data += struct.pack(
        '>ffBBf',
        float(sensor_state["temperature_c"]),
        float(sensor_state["humidity_pct"]),
        1 if sensor_state["pir_active"] else 0,
        1 if sensor_state["fire_alarm"] else 0,
        float(sensor_state["distance_cm"])
    )
    return data

# ==============================
# HTTP MJPEG VIDEO STREAMER
# ==============================
class CamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/stream_pir.mjpg':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
            self.end_headers()
            while True:
                if latest_frame_pir:
                    try:
                        self.wfile.write(b"--jpgboundary\r\n")
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(latest_frame_pir)))
                        self.end_headers()
                        self.wfile.write(latest_frame_pir)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.05)
                    except Exception:
                        break
        elif self.path == '/stream_touch.mjpg':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
            self.end_headers()
            while True:
                if latest_frame_touch:
                    try:
                        self.wfile.write(b"--jpgboundary\r\n")
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(latest_frame_touch)))
                        self.end_headers()
                        self.wfile.write(latest_frame_touch)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.05)
                    except Exception:
                        break
        else:
            self.send_response(404)
            self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    pass

def start_video_server():
    server = ThreadedHTTPServer(('0.0.0.0', 8000), CamHandler)
    print("Video streams available at: http://localhost:8000/stream_pir.mjpg and /stream_touch.mjpg")
    server.serve_forever()

# Start video streaming in background thread
threading.Thread(target=start_video_server, daemon=True).start()

# ==============================
# SOCKET SETUP
# ==============================
sock_in_pir = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_in_pir.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock_in_pir.bind((LOCAL_IP, PORT_PIR))

sock_in_touch = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_in_touch.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock_in_touch.bind((LOCAL_IP, PORT_TOUCH))

# Outbound socket to talk to the local Backend Server (5005)
sock_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

sockets = [sock_in_pir, sock_in_touch]

print("====================================================")
print(" SERVER-SIDE SMART TRANSLATOR RELAY DASHBOARD ")
print("====================================================")
print(f"Listening for older RPis on ports {PORT_PIR} and {PORT_TOUCH}")
print(f"Translating and forwarding binary packets locally to {LOCAL_BACKEND_IP}:{SERVER_UDP_PORT}\n")

# ==============================
# MAIN LOOP
# ==============================
try:
    while True:
        readable, _, _ = select.select(sockets, [], [])

        for s in readable:
            data, address = s.recvfrom(BUFFER_SIZE)

            # Check if this is a video frame (usually > 1000 bytes)
            if len(data) > 1000:
                # Store the raw JPEG bytes for the HTTP MJPEG streamer
                if s == sock_in_pir:
                    latest_frame_pir = data
                elif s == sock_in_touch:
                    latest_frame_touch = data
                continue

            # Otherwise, process as plain text sensor data
            try:
                message = data.decode('utf-8').strip()
                cam_id = "cam_pi" # Default fallback
                updated = False

                # ---- DHT ----
                if message.startswith("DHT:"):
                    cam_id = "cam_touch"
                    clean_data = message.replace("DHT:", "")
                    try:
                        temp, hum = clean_data.split(",")
                        sensor_state["temperature_c"] = float(temp)
                        sensor_state["humidity_pct"] = float(hum)
                        updated = True
                        print(f"🌡️ [DHT] Temp: {temp}°C | Humidity: {hum}%")
                    except Exception as e:
                        pass

                # ---- TOUCH ----
                elif "TOUCH" in message.upper():
                    cam_id = "cam_touch"
                    if "OFF" in message.upper() or "NO" in message.upper():
                        sensor_state["fire_alarm"] = False
                        updated = True
                    else:
                        sensor_state["fire_alarm"] = True
                        updated = True
                        print(f"👉 [TOUCH ON]")

                # ---- PIR ----
                elif message.startswith("[PIR]"):
                    cam_id = "cam_pir"
                    if "DETECTED" in message.upper():
                        sensor_state["pir_active"] = True
                        updated = True
                        print(f"🚨 [PIR DETECTED]")
                    else:
                        sensor_state["pir_active"] = False
                        updated = True

                # If we successfully parsed a sensor update, translate and forward it!
                if updated:
                    # Translate to binary
                    binary_payload = pack_environment_packet(cam_id)
                    # Forward to the local Optical Radar Backend port 5005
                    sock_out.sendto(binary_payload, (LOCAL_BACKEND_IP, SERVER_UDP_PORT))

            except UnicodeDecodeError:
                pass # Probably a corrupted frame that bypassed the size check, safely ignore

except KeyboardInterrupt:
    print("\nShutting down receiver...")

finally:
    sock_in_pir.close()
    sock_in_touch.close()
    sock_out.close()
