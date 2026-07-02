

"""
imu.py
PURPOSE: Read IMU data for camera orientation.
"""

import time
import threading
import math
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class IMUReading:
    """IMU sensor reading."""
    # Accelerometer (m/s²)
    accel_x: float
    accel_y: float
    accel_z: float
    
    # Gyroscope (rad/s)
    gyro_x: float
    gyro_y: float
    gyro_z: float
    
    # Magnetometer (µT)
    mag_x: float = 0.0
    mag_y: float = 0.0
    mag_z: float = 0.0
    
    timestamp: float = 0.0


@dataclass
class Orientation:
    """Computed orientation."""
    roll: float  # Degrees
    pitch: float  # Degrees
    yaw: float  # Degrees
    
    # Quaternion
    qw: float = 1.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0


class IMUReader:
    """
    IMU data reader with sensor fusion.
    
    Supports MPU6050/9250 via I2C.
    Uses complementary filter for orientation.
    """
    
    def __init__(
        self,
        i2c_address: int = 0x68,
        mock: bool = False,
        complementary_alpha: float = 0.96
    ):
        """
        Initialize IMU reader.
        
        Args:
            i2c_address: I2C address (0x68 for MPU6050)
            mock: Use mock data
            complementary_alpha: Complementary filter weight
        """
        self.i2c_address = i2c_address
        self.mock = mock
        self.alpha = complementary_alpha
        
        self._bus = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        self._latest_reading: Optional[IMUReading] = None
        self._orientation: Optional[Orientation] = None
        self._lock = threading.Lock()
        
        # Complementary filter state
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw = 0.0
        self._last_time = 0.0
    
    def start(self) -> bool:
        """Start IMU reader."""
        if self.mock:
            self._running = True
            self._last_time = time.time()
            self._thread = threading.Thread(target=self._mock_loop, daemon=True)
            self._thread.start()
            return True
        
        try:
            import smbus2
            self._bus = smbus2.SMBus(1)
            
            # Wake up MPU6050
            self._bus.write_byte_data(self.i2c_address, 0x6B, 0)
            
            self._running = True
            self._last_time = time.time()
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"IMU start failed: {e}")
            return False
    
    def stop(self) -> None:
        """Stop IMU reader."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._bus:
            self._bus.close()
            self._bus = None
    
    def _read_loop(self) -> None:
        """Main read loop for real IMU."""
        while self._running:
            try:
                reading = self._read_mpu6050()
                if reading:
                    self._update_orientation(reading)
                
                time.sleep(0.01)  # 100 Hz
            except Exception:
                time.sleep(0.1)
    
    def _mock_loop(self) -> None:
        """Mock IMU loop for testing."""
        while self._running:
            # Simulate slight movement
            import random
            
            reading = IMUReading(
                accel_x=random.gauss(0, 0.1),
                accel_y=random.gauss(0, 0.1),
                accel_z=9.81 + random.gauss(0, 0.1),
                gyro_x=random.gauss(0, 0.01),
                gyro_y=random.gauss(0, 0.01),
                gyro_z=random.gauss(0, 0.01),
                timestamp=time.time()
            )
            
            self._update_orientation(reading)
            time.sleep(0.01)
    
    def _read_mpu6050(self) -> Optional[IMUReading]:
        """Read from MPU6050."""
        try:
            # Read accelerometer
            accel_data = self._bus.read_i2c_block_data(self.i2c_address, 0x3B, 6)
            ax = self._bytes_to_int16(accel_data[0], accel_data[1]) / 16384.0 * 9.81
            ay = self._bytes_to_int16(accel_data[2], accel_data[3]) / 16384.0 * 9.81
            az = self._bytes_to_int16(accel_data[4], accel_data[5]) / 16384.0 * 9.81
            
            # Read gyroscope
            gyro_data = self._bus.read_i2c_block_data(self.i2c_address, 0x43, 6)
            gx = self._bytes_to_int16(gyro_data[0], gyro_data[1]) / 131.0 * (math.pi / 180)
            gy = self._bytes_to_int16(gyro_data[2], gyro_data[3]) / 131.0 * (math.pi / 180)
            gz = self._bytes_to_int16(gyro_data[4], gyro_data[5]) / 131.0 * (math.pi / 180)
            
            return IMUReading(
                accel_x=ax, accel_y=ay, accel_z=az,
                gyro_x=gx, gyro_y=gy, gyro_z=gz,
                timestamp=time.time()
            )
        except Exception:
            return None
    
    def _bytes_to_int16(self, high: int, low: int) -> int:
        """Convert two bytes to signed int16."""
        value = (high << 8) | low
        if value >= 0x8000:
            value -= 0x10000
        return value
    
    def _update_orientation(self, reading: IMUReading) -> None:
        """Update orientation using complementary filter."""
        now = reading.timestamp
        dt = now - self._last_time if self._last_time > 0 else 0.01
        self._last_time = now
        
        # Accelerometer-based angles
        accel_roll = math.atan2(reading.accel_y, reading.accel_z)
        accel_pitch = math.atan2(-reading.accel_x, 
                                  math.sqrt(reading.accel_y**2 + reading.accel_z**2))
        
        # Integrate gyroscope
        gyro_roll = self._roll + reading.gyro_x * dt * (180 / math.pi)
        gyro_pitch = self._pitch + reading.gyro_y * dt * (180 / math.pi)
        gyro_yaw = self._yaw + reading.gyro_z * dt * (180 / math.pi)
        
        # Complementary filter
        self._roll = self.alpha * gyro_roll + (1 - self.alpha) * math.degrees(accel_roll)
        self._pitch = self.alpha * gyro_pitch + (1 - self.alpha) * math.degrees(accel_pitch)
        self._yaw = gyro_yaw  # No absolute reference for yaw without magnetometer
        
        # Wrap yaw
        self._yaw = (self._yaw + 180) % 360 - 180
        
        # Convert to quaternion
        qw, qx, qy, qz = self._euler_to_quaternion(self._roll, self._pitch, self._yaw)
        
        with self._lock:
            self._latest_reading = reading
            self._orientation = Orientation(
                roll=self._roll,
                pitch=self._pitch,
                yaw=self._yaw,
                qw=qw, qx=qx, qy=qy, qz=qz
            )
    
    def _euler_to_quaternion(
        self,
        roll: float,
        pitch: float,
        yaw: float
    ) -> Tuple[float, float, float, float]:
        """Convert Euler angles to quaternion."""
        r = math.radians(roll) / 2
        p = math.radians(pitch) / 2
        y = math.radians(yaw) / 2
        
        cr, sr = math.cos(r), math.sin(r)
        cp, sp = math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)
        
        qw = cr * cp * cy + sr * sp * sy
        qx = sr * cp * cy - cr * sp * sy
        qy = cr * sp * cy + sr * cp * sy
        qz = cr * cp * sy - sr * sp * cy
        
        return (qw, qx, qy, qz)
    
    def get_reading(self) -> Optional[IMUReading]:
        """Get latest IMU reading."""
        with self._lock:
            return self._latest_reading
    
    def get_orientation(self) -> Optional[Orientation]:
        """Get computed orientation."""
        with self._lock:
            return self._orientation
    
    def get_quaternion(self) -> Optional[Tuple[float, float, float, float]]:
        """Get orientation as quaternion (w, x, y, z)."""
        orientation = self.get_orientation()
        if orientation:
            return (orientation.qw, orientation.qx, orientation.qy, orientation.qz)
        return None
    
    @property
    def is_running(self) -> bool:
        return self._running
