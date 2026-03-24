"""
rpi_node.py
PURPOSE: Main orchestrator for Raspberry Pi camera node.
"""

import time
import socket
import signal
import sys
import os
import threading
import cv2
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
from typing import Optional

_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.config import load as load_config
from common.constants import UDP_PORT, TARGET_FPS, PROTOCOL_VERSION
from common.protocol import TelemetryPacket, MotionVector as ProtocolMotionVector, AnnouncePacket

from .vision import VisionSystem, VisionConfig
from .gps import GPSReader
from .imu import IMUReader


class RPiNode:
    """
    Main camera node orchestrator.
    
    Workflow:
        1. Capture frame (Vision)
        2. Detect motion (Vision)
        3. Get position (GPS)
        4. Get orientation (IMU)
        5. Pack and send packet (Network)
        
    Health Flags:
        bit 0: GPS fix
        bit 1: Camera OK
        bit 2: IMU OK
    """
    
    def __init__(
        self,
        camera_id: str,
        server_address: str = "127.0.0.1",
        server_port: int = UDP_PORT,
        config_path: Optional[str] = None,
        mock: bool = False
    ):
        """
        Initialize camera node.
        
        Args:
            camera_id: Unique camera identifier
            server_address: Server IP address
            server_port: Server UDP port
            config_path: Path to config.yaml
            mock: Use mock sensors
        """
        self.camera_id = camera_id
        self.server_address = server_address
        self.server_port = server_port
        self.mock = mock
        
        # Load config
        self.config = load_config(config_path)
        
        # Initialize components
        self.vision = VisionSystem(VisionConfig(
            fps=TARGET_FPS
        ))
        
        # GNSS and kinematic sensor disabled as they are fixed/static
        self.gps = None
        self.imu = None

        # Additional Local Sensors (PIR, Touch, DHT11)
        # Hardcoding based on network project files for now,
        # since we know these are the components attached.
        self.hardware = LocalHardwareManager(
            enable_pir=True,
            enable_touch=True,
            enable_dht=True
        )
        
        # Network
        self._socket: Optional[socket.socket] = None
        
        # State
        self._running = False
        self._sequence = 0
        self._frame_count = 0
        self._last_announce_time = 0.0
        
        # New: Mode & Streaming
        self.mode = "tracking"  # "tracking" or "stream"
        self._latest_rgb_frame = None  # Buffer for streaming
        self._stream_lock = threading.Lock()
        
        # Embedded HTTP Server
        self._http_server = None
        self._http_thread = None
    
    def start(self) -> bool:
        """
        Start all components.
        
        Returns:
            True if successful
        """
        print(f"Starting RPi Node: {self.camera_id}")
        
        # Clock sanity check — RPi without RTC may boot at epoch
        MIN_SANE_EPOCH = 1704067200  # 2024-01-01 00:00:00 UTC
        now = time.time()
        if now < MIN_SANE_EPOCH:
            print(f"WARNING: System clock appears wrong (epoch={now:.0f}). "
                  "Packets will be rejected by server. Waiting for NTP sync...")
            for attempt in range(30):
                time.sleep(1)
                if time.time() >= MIN_SANE_EPOCH:
                    print(f"Clock synchronized after {attempt + 1}s.")
                    break
            else:
                print("ERROR: Clock still invalid after 30s. "
                      "Ensure NTP is available or install an RTC (DS3231). "
                      "Proceeding anyway — server may reject packets.")
        
        # Start sensors
        if not self.vision.start():
            print("Warning: Vision system failed to start")
        
        if self.gps and not self.gps.start():
            print("Warning: GPS failed to start")
        
        if self.imu and not self.imu.start():
            print("Warning: IMU failed to start")

        try:
            self.hardware.start()
        except Exception as e:
            print(f"Warning: Hardware manager failed to start: {e}")
        
        # Create UDP socket
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except Exception as e:
            print(f"Socket creation failed: {e}")
            return False
        
        self._running = True
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        print(f"Node started, sending to {self.server_address}:{self.server_port}")
        
        # Send initial burst of announcements
        for _ in range(3):
            self._send_announce()
            time.sleep(0.1)
        self._last_announce_time = time.time()  # Prevent redundant re-announce on first loop
            
        # Start HTTP Server
        self._start_http_server()
            
        return True
    
    def _start_http_server(self):
        """Start the embedded HTTP server to provide API and stream."""
        node_instance = self
        
        class StreamingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                # Handle Mode Toggle API
                if self.path.startswith('/set_mode'):
                    from urllib.parse import urlparse, parse_qs
                    query = parse_qs(urlparse(self.path).query)
                    new_mode = query.get('mode', [''])[0]
                    if new_mode in ['tracking', 'stream']:
                        node_instance.mode = new_mode
                        # Send 200 OK
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(f"Mode set to {new_mode}\n".encode('utf-8'))
                        print(f"Mode changed to: {new_mode}")
                    else:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"Invalid mode")
                    return
                
                # Handle Stream API
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Age', 0)
                    self.send_header('Cache-Control', 'no-cache, private')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
                    self.end_headers()
                    try:
                        print(f"Client connected to stream: {self.client_address}")
                        while node_instance._running:
                            # Only serve stream if in stream mode (to save CPU when tracking)
                            if node_instance.mode != "stream":
                                time.sleep(0.5)
                                continue
                            
                            with node_instance._stream_lock:
                                frame = node_instance._latest_rgb_frame
                                
                            if frame is None:
                                time.sleep(0.05)
                                continue
                                
                            ret, buffer = cv2.imencode('.jpg', frame)
                            if not ret:
                                time.sleep(0.05)
                                continue
                                
                            jpg_bytes = buffer.tobytes()
                            
                            self.wfile.write(b'--FRAME\r\n')
                            self.send_header('Content-Type', 'image/jpeg')
                            self.send_header('Content-Length', len(jpg_bytes))
                            self.end_headers()
                            self.wfile.write(jpg_bytes)
                            self.wfile.write(b'\r\n')
                            
                            # Limit frame rate slightly to save bandwidth
                            time.sleep(1.0 / 15.0) 
                    except Exception as e:
                        print(f"Removed streaming client {self.client_address}: {str(e)}")
                else:
                    self.send_error(404)
                    self.end_headers()

        class StreamingServer(socketserver.ThreadingMixIn, HTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        address = ('', 8000)
        try:
            self._http_server = StreamingServer(address, StreamingHandler)
            print("HTTP server started on port 8000")
            self._http_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
            self._http_thread.start()
        except Exception as e:
            print(f"Failed to start HTTP server: {e}")
    
    def stop(self) -> None:
        """Stop all components."""
        print("Stopping RPi Node")
        
        self._running = False
        self.vision.stop()
        if self.gps:
            self.gps.stop()
        if self.imu:
            self.imu.stop()
        try:
            self.hardware.stop()
        except:
            pass
        
        if self._http_server:
            self._http_server.shutdown()
            self._http_server.server_close()
        
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.stop()
    
    def _get_health_flags(self) -> int:
        """Calculate health flags byte."""
        flags = 0
        
        # Bit 0: GPS signal/fix
        if self.gps and self.gps.has_fix():
            flags |= 0x01
        
        # Bit 1: Camera OK
        if self.vision.is_running:
            flags |= 0x02
        
        # Bit 2: IMU OK
        if self.imu and self.imu.is_running:
            flags |= 0x04

        # Additional Sensors
        try:
            pir_motion, touch = self.hardware.get_digital_state()
            temp, hum = self.hardware.get_climate()

            # Bit 3: PIR Motion Detected
            if pir_motion:
                flags |= 0x08

            # Bit 4: Touch Detected
            if touch:
                flags |= 0x10

            # Bit 5: Temp/Humidity OK (non-zero reading)
            if temp != 0.0 or hum != 0.0:
                flags |= 0x20
        except Exception:
            pass

        return flags
        
    def _send_announce(self) -> bool:
        """Send announce packet with configuration."""
        if not self._socket:
            return False
            
        try:
            packet = AnnouncePacket(
                camera_id=self.camera_id,
                timestamp=time.time(),
                fov_horizontal=self.vision.config.horizontal_fov,
                fov_vertical=self.vision.config.vertical_fov,
                resolution_width=self.vision.config.resolution[0],
                resolution_height=self.vision.config.resolution[1],
                fps=self.vision.config.fps
            )
            
            data = packet.pack()
            self._socket.sendto(data, (self.server_address, self.server_port))
            return True
        except Exception as e:
            print(f"Announce failed: {e}")
            return False
    
    def process_frame(self) -> bool:
        """
        Process one frame.
        
        Returns:
            True if packet was sent
        """
        self._frame_count += 1
        
        # 1. Capture and detect motion
        frame, vectors = self.vision.get_frame_and_vectors(bgr_out=(self.mode == "stream"))
        
        # In stream mode, save the frame for the HTTP server
        if self.mode == "stream" and frame is not None:
            with self._stream_lock:
                self._latest_rgb_frame = frame

        # DEBUG: Print vector count
        if len(vectors) > 0:
            print(f"Motion Frame: Detected {len(vectors)} motion vectors")
        else:
            if self._frame_count % 30 == 0:
                print(f"Frame {self._frame_count}: No motion detected")
        
        # 2. Get GPS position
        if self.gps:
            gps_fix = self.gps.get_fix()
            if gps_fix:
                lat, lon = gps_fix.latitude, gps_fix.longitude
                alt = gps_fix.altitude  # Protocol-required field; unused in 2D tracking
            else:
                lat, lon, alt = 0.0, 0.0, 0.0
        else:
            lat, lon, alt = 0.0, 0.0, 0.0
        
        # 3. Get IMU orientation
        if self.imu:
            orientation = self.imu.get_quaternion()
            if orientation is None:
                orientation = (1.0, 0.0, 0.0, 0.0)
        else:
            orientation = (1.0, 0.0, 0.0, 0.0)
        
        # 4. Build packet
        protocol_vectors = []
        for v in vectors:
            protocol_vectors.append(ProtocolMotionVector(
                azimuth=v.azimuth,
                elevation=v.elevation,
                intensity=v.intensity,
                class_id=v.class_id
            ))
        
        packet = TelemetryPacket(
            version=PROTOCOL_VERSION,
            camera_id=self.camera_id,
            timestamp=time.time(),
            sequence_number=self._sequence,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            orientation=orientation,
            health_flags=self._get_health_flags(),
            mode=1 if self.mode == "stream" else 0,
            vectors=protocol_vectors
        )
        
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        
        # 5. Send packet
        return self._send_packet(packet)
        
    def _send_packet(self, packet: TelemetryPacket) -> bool:
        """Send packet to server."""
        if not self._socket:
            return False
        
        try:
            data = packet.pack()
            self._socket.sendto(data, (self.server_address, self.server_port))
            return True
        except Exception as e:
            print(f"Send failed: {e}")
            return False
    
    def run(self, target_fps: float = TARGET_FPS) -> None:
        """
        Main run loop.
        
        Args:
            target_fps: Target frames per second
        """
        if not self.start():
            print("Failed to start node")
            return
        
        frame_time = 1.0 / target_fps
        
        while self._running:
            frame_start = time.time()
            
            # Periodic announcement (every 5 seconds)
            if time.time() - self._last_announce_time > 5.0:
                self._send_announce()
                self._last_announce_time = time.time()
            
            if self.mode == "tracking" or self.mode == "stream":
                # process_frame handles capturing, processing, telemetry, and stream buffer updating
                self.process_frame()
            else:
                print(f"Unknown mode: {self.mode}")
                time.sleep(1.0)
            
            # Rate limiting
            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        print("Node stopped")
    
    def get_stats(self) -> dict:
        """Get node statistics."""
        gps_fix = self.gps.get_fix() if self.gps else None
        orientation = self.imu.get_orientation() if self.imu else None
        
        return {
            'camera_id': self.camera_id,
            'frame_count': self._frame_count,
            'sequence': self._sequence,
            'gps_fix': gps_fix.fix_quality if gps_fix else 0,
            'satellites': gps_fix.satellites if gps_fix else 0,
            'roll': orientation.roll if orientation else 0,
            'pitch': orientation.pitch if orientation else 0,
            'yaw': orientation.yaw if orientation else 0,
            'health_flags': self._get_health_flags()
        }


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="OpticalRadar Camera Node")
    parser.add_argument("--id", "-i", default="cam01", help="Camera ID")
    parser.add_argument("--server", "-s", default="127.0.0.1", help="Server address")
    parser.add_argument("--port", "-p", type=int, default=UDP_PORT, help="Server port")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--mock", "-m", action="store_true", help="Use mock sensors")
    parser.add_argument("--mode", default="tracking", choices=["tracking", "stream"], help="Operating mode")
    
    args = parser.parse_args()
    
    node = RPiNode(
        camera_id=args.id,
        server_address=args.server,
        server_port=args.port,
        config_path=args.config,
        mock=args.mock
    )
    node.mode = args.mode
    
    node.run()


if __name__ == "__main__":
    main()
