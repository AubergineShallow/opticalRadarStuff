"""
gps.py
PURPOSE: Read GPS data from GPS module.
"""

import time
import threading
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class GPSFix:
    """GPS fix data."""
    latitude: float  # Degrees
    longitude: float  # Degrees
    altitude: float  # Meters
    timestamp: float  # Unix timestamp
    
    speed: float = 0.0  # m/s
    heading: float = 0.0  # Degrees
    
    fix_quality: int = 0  # 0=no fix, 1=GPS, 2=DGPS
    satellites: int = 0
    hdop: float = 99.0  # Horizontal dilution of precision


class GPSReader:
    """
    GPS data reader.
    
    Uses serial connection to GPS module (e.g., NEO-6M).
    Parses NMEA sentences (GGA, RMC).
    """
    
    def __init__(
        self,
        port: str = "/dev/serial0",
        baudrate: int = 9600,
        mock: bool = False
    ):
        """
        Initialize GPS reader.
        
        Args:
            port: Serial port path
            baudrate: Serial baud rate
            mock: Use mock data instead of real GPS
        """
        self.port = port
        self.baudrate = baudrate
        self.mock = mock
        
        self._serial = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        self._latest_fix: Optional[GPSFix] = None
        self._lock = threading.Lock()
        
        # Mock data for testing
        self._mock_lat = 37.7749
        self._mock_lon = -122.4194
        self._mock_alt = 10.0
    
    def start(self) -> bool:
        """
        Start GPS reader.
        
        Returns:
            True if successful
        """
        if self.mock:
            self._running = True
            self._thread = threading.Thread(target=self._mock_loop, daemon=True)
            self._thread.start()
            return True
        
        try:
            import serial
            self._serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=1
            )
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"GPS start failed: {e}")
            return False
    
    def stop(self) -> None:
        """Stop GPS reader."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._serial:
            self._serial.close()
            self._serial = None
    
    def _read_loop(self) -> None:
        """Main read loop for real GPS."""
        while self._running:
            try:
                line = self._serial.readline().decode('ascii', errors='ignore').strip()
                self._parse_nmea(line)
            except Exception:
                time.sleep(0.1)
    
    def _mock_loop(self) -> None:
        """Mock GPS loop for testing."""
        while self._running:
            # Add small random movement
            import random
            self._mock_lat += random.gauss(0, 0.00001)
            self._mock_lon += random.gauss(0, 0.00001)
            
            with self._lock:
                self._latest_fix = GPSFix(
                    latitude=self._mock_lat,
                    longitude=self._mock_lon,
                    altitude=self._mock_alt,
                    timestamp=time.time(),
                    fix_quality=1,
                    satellites=8,
                    hdop=1.2
                )
            
            time.sleep(0.1)
    
    def _parse_nmea(self, sentence: str) -> None:
        """Parse NMEA sentence."""
        if not sentence.startswith('$'):
            return
        
        try:
            # Check checksum
            if '*' in sentence:
                data, checksum = sentence[1:].split('*')
                calc_checksum = 0
                for c in data:
                    calc_checksum ^= ord(c)
                if int(checksum, 16) != calc_checksum:
                    return
            else:
                data = sentence[1:]
            
            parts = data.split(',')
            msg_type = parts[0]
            
            if msg_type.endswith('GGA'):
                self._parse_gga(parts)
            elif msg_type.endswith('RMC'):
                self._parse_rmc(parts)
                
        except Exception:
            pass
    
    def _parse_gga(self, parts: list) -> None:
        """Parse GGA sentence (position fix)."""
        if len(parts) < 11:
            return
        
        try:
            lat = self._parse_coord(parts[2], parts[3])
            lon = self._parse_coord(parts[4], parts[5])
            fix_quality = int(parts[6]) if parts[6] else 0
            satellites = int(parts[7]) if parts[7] else 0
            hdop = float(parts[8]) if parts[8] else 99.0
            altitude = float(parts[9]) if parts[9] else 0.0
            
            with self._lock:
                self._latest_fix = GPSFix(
                    latitude=lat,
                    longitude=lon,
                    altitude=altitude,
                    timestamp=time.time(),
                    fix_quality=fix_quality,
                    satellites=satellites,
                    hdop=hdop
                )
        except (ValueError, IndexError):
            pass
    
    def _parse_rmc(self, parts: list) -> None:
        """Parse RMC sentence (speed and heading)."""
        if len(parts) < 9:
            return
        
        try:
            if parts[2] != 'A':  # A = valid, V = invalid
                return
            
            speed_knots = float(parts[7]) if parts[7] else 0.0
            heading = float(parts[8]) if parts[8] else 0.0
            
            with self._lock:
                if self._latest_fix:
                    self._latest_fix.speed = speed_knots * 0.514444  # knots to m/s
                    self._latest_fix.heading = heading
        except (ValueError, IndexError):
            pass
    
    def _parse_coord(self, value: str, direction: str) -> float:
        """Parse NMEA coordinate to decimal degrees."""
        if not value or not direction:
            return 0.0
        
        # Format: DDDMM.MMMM
        if '.' in value:
            point_idx = value.index('.')
            degrees = int(value[:point_idx-2])
            minutes = float(value[point_idx-2:])
        else:
            degrees = int(value[:-2])
            minutes = float(value[-2:])
        
        result = degrees + minutes / 60.0
        
        if direction in ('S', 'W'):
            result = -result
        
        return result
    
    def get_fix(self) -> Optional[GPSFix]:
        """Get latest GPS fix."""
        with self._lock:
            return self._latest_fix
    
    def get_position(self) -> Optional[Tuple[float, float, float]]:
        """Get latest position (lat, lon, alt)."""
        fix = self.get_fix()
        if fix:
            return (fix.latitude, fix.longitude, fix.altitude)
        return None
    
    def has_fix(self) -> bool:
        """Check if we have a valid GPS fix."""
        fix = self.get_fix()
        return fix is not None and fix.fix_quality > 0
    
    @property
    def is_running(self) -> bool:
        return self._running
