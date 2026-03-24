"""
sensors.py
PURPOSE: Read environmental sensors (DHT22, PIR, fire alarm, HC-SR04) on RPi GPIO.

Falls back to mock values when hardware is unavailable (e.g. running on
a laptop for testing, or when sensors are not wired).
"""

import time
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class SensorReading:
    """Snapshot of all environmental sensor values."""
    temperature_c: float = 0.0
    humidity_pct: float = 0.0
    pir_active: bool = False
    fire_alarm: bool = False
    distance_cm: float = 0.0
    timestamp: float = 0.0


class SensorReader:
    """
    Polls environmental sensors attached to RPi GPIO pins.

    Sensors:
        - DHT22: Temperature + Humidity (1-wire on a single GPIO)
        - HC-SR501 PIR: Motion detection (digital input)
        - Fire Alarm button: Normally-open switch (digital input)
        - HC-SR04: Ultrasonic distance (trigger + echo pins)

    Usage:
        reader = SensorReader(dht_pin=4, pir_pin=17, ...)
        reader.start()
        ...
        reading = reader.get_reading()
        reader.stop()
    """

    def __init__(
        self,
        dht_pin: int = 4,
        pir_pin: int = 17,
        fire_pin: int = 27,
        trigger_pin: int = 23,
        echo_pin: int = 24,
        poll_interval: float = 1.0,
        mock: bool = False
    ):
        self.dht_pin = dht_pin
        self.pir_pin = pir_pin
        self.fire_pin = fire_pin
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.poll_interval = poll_interval
        self.mock = mock

        self._reading = SensorReading()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Hardware handles (set in start)
        self._gpio = None
        self._dht_device = None

    def start(self) -> bool:
        """Start sensor polling. Returns True if successful."""
        if self.mock:
            print("[SensorReader] Mock mode — using simulated values")
            self._running = True
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            return True

        # Try to import GPIO libraries (RPi only)
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # PIR: digital input
            GPIO.setup(self.pir_pin, GPIO.IN)
            # Fire alarm: digital input with pull-down
            GPIO.setup(self.fire_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            # Ultrasonic
            GPIO.setup(self.trigger_pin, GPIO.OUT)
            GPIO.setup(self.echo_pin, GPIO.IN)
            GPIO.output(self.trigger_pin, False)
            time.sleep(0.05)  # Settle

            print("[SensorReader] GPIO initialized")
        except (ImportError, RuntimeError) as e:
            print(f"[SensorReader] GPIO unavailable ({e}), falling back to mock")
            self.mock = True

        # Try to import DHT library
        if not self.mock:
            try:
                import adafruit_dht
                import board
                pin = getattr(board, f"D{self.dht_pin}", None)
                if pin:
                    self._dht_device = adafruit_dht.DHT11(pin)
                    print("[SensorReader] DHT11 initialized")
                else:
                    print(f"[SensorReader] Unknown board pin D{self.dht_pin}")
            except (ImportError, RuntimeError) as e:
                print(f"[SensorReader] DHT library unavailable ({e})")

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._dht_device:
            try:
                self._dht_device.exit()
            except Exception:
                pass
        if self._gpio and not self.mock:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
        print("[SensorReader] Stopped")

    def get_reading(self) -> SensorReading:
        """Get the latest sensor reading (thread-safe)."""
        with self._lock:
            return SensorReading(
                temperature_c=self._reading.temperature_c,
                humidity_pct=self._reading.humidity_pct,
                pir_active=self._reading.pir_active,
                fire_alarm=self._reading.fire_alarm,
                distance_cm=self._reading.distance_cm,
                timestamp=self._reading.timestamp
            )

    # ---- Internal polling ----

    def _poll_loop(self) -> None:
        """Background thread: poll sensors periodically."""
        import math
        while self._running:
            try:
                if self.mock:
                    reading = self._poll_mock()
                else:
                    reading = self._poll_hardware()
                reading.timestamp = time.time()
                with self._lock:
                    self._reading = reading
            except Exception as e:
                print(f"[SensorReader] Poll error: {e}")
            time.sleep(self.poll_interval)

    def _poll_mock(self) -> SensorReading:
        """Generate simulated sensor data for testing."""
        import math
        t = time.time()
        return SensorReading(
            temperature_c=25.0 + 5.0 * math.sin(t / 30.0),
            humidity_pct=60.0 + 15.0 * math.cos(t / 45.0),
            pir_active=(int(t) % 10 < 3),
            fire_alarm=False,
            distance_cm=50.0 + 30.0 * math.sin(t / 20.0),
        )

    def _poll_hardware(self) -> SensorReading:
        """Read real hardware sensors."""
        reading = SensorReading()

        # DHT11 (Temperature + Humidity)
        if self._dht_device:
            try:
                reading.temperature_c = self._dht_device.temperature or 0.0
                reading.humidity_pct = self._dht_device.humidity or 0.0
            except Exception:
                pass  # DHT11 is notoriously flaky, skip on error

        # PIR
        if self._gpio:
            try:
                reading.pir_active = bool(self._gpio.input(self.pir_pin))
            except Exception:
                pass

        # Fire alarm
        if self._gpio:
            try:
                reading.fire_alarm = bool(self._gpio.input(self.fire_pin))
            except Exception:
                pass

        # Ultrasonic HC-SR04
        reading.distance_cm = self._read_ultrasonic()

        return reading

    def _read_ultrasonic(self) -> float:
        """Read distance from HC-SR04. Returns cm, or 0.0 on failure."""
        if not self._gpio:
            return 0.0

        try:
            GPIO = self._gpio

            # Send 10µs trigger pulse
            GPIO.output(self.trigger_pin, True)
            time.sleep(0.00001)
            GPIO.output(self.trigger_pin, False)

            # Wait for echo start (timeout 0.1s)
            start_time = time.time()
            timeout = start_time + 0.1
            while GPIO.input(self.echo_pin) == 0:
                start_time = time.time()
                if start_time > timeout:
                    return 0.0

            # Wait for echo end
            end_time = time.time()
            timeout = end_time + 0.1
            while GPIO.input(self.echo_pin) == 1:
                end_time = time.time()
                if end_time > timeout:
                    return 0.0

            # Calculate distance: speed of sound ~34300 cm/s, round trip
            elapsed = end_time - start_time
            distance_cm = (elapsed * 34300.0) / 2.0

            # Sanity clamp (HC-SR04 range: 2cm – 400cm)
            if distance_cm < 2.0 or distance_cm > 400.0:
                return 0.0

            return round(distance_cm, 1)
        except Exception:
            return 0.0
