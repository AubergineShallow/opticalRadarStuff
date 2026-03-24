import time
import threading
from typing import Optional, Tuple

class LocalHardwareManager:
    """
    Manages local hardware sensors and actuators (LED, PIR, Touch, DHT11)
    on the Raspberry Pi nodes.

    GPIO Map:
    - LED: GPIO 17
    - PIR Sensor: GPIO 6
    - Touch Sensor: GPIO 5
    - DHT11 (Temp/Hum): GPIO 4 (Note: testtemp.py uses D4, while the table says GPIO 17*. We use board.D4 based on testtemp.py logic)
    """
    def __init__(self, enable_pir: bool = False, enable_touch: bool = False, enable_dht: bool = False):
        self.enable_pir = enable_pir
        self.enable_touch = enable_touch
        self.enable_dht = enable_dht

        self.led = None
        self.pir = None
        self.touch = None
        self.dht = None

        self._running = False
        self._thread = None

        # State
        self.temperature_c: float = 0.0
        self.humidity: float = 0.0
        self.motion_detected: bool = False
        self.touch_detected: bool = False

        self._init_hardware()

    def _init_hardware(self):
        try:
            from gpiozero import Button, LED
            self.led = LED(17)

            if self.enable_pir:
                self.pir = Button(6, pull_up=False)

            if self.enable_touch:
                self.touch = Button(5, pull_up=False)

        except ImportError:
            print("Warning: gpiozero not available. Mocking digital sensors.")
        except Exception as e:
            print(f"Warning: Failed to init digital sensors: {e}")

        if self.enable_dht:
            try:
                import board
                import adafruit_dht
                self.dht = adafruit_dht.DHT11(board.D4)
            except ImportError:
                print("Warning: adafruit_dht or board not available. Mocking DHT11.")
            except Exception as e:
                print(f"Warning: Failed to init DHT11: {e}")

    def start(self):
        """Start background polling thread."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background thread and clean up."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

        if self.led:
            self.led.off()

        if self.dht:
            try:
                self.dht.exit()
            except:
                pass

    def _poll_loop(self):
        """Background loop to read sensors and actuate LED."""
        last_dht_read = 0.0

        while self._running:
            led_should_be_on = False

            # Read PIR
            if self.pir:
                self.motion_detected = self.pir.is_pressed
                if self.motion_detected:
                    led_should_be_on = True

            # Read Touch
            if self.touch:
                self.touch_detected = self.touch.is_pressed
                if self.touch_detected:
                    led_should_be_on = True

            # Actuate LED
            if self.led:
                if led_should_be_on:
                    self.led.on()
                else:
                    self.led.off()

            # Read DHT11 (requires 2s between reads)
            if self.dht and (time.time() - last_dht_read > 2.0):
                try:
                    self.temperature_c = self.dht.temperature
                    self.humidity = self.dht.humidity
                    last_dht_read = time.time()
                except RuntimeError:
                    # Expected behavior for DHT11 reads occasionally
                    pass
                except Exception as e:
                    print(f"DHT11 Error: {e}")

            time.sleep(0.1)

    def get_climate(self) -> Tuple[float, float]:
        """Returns (temperature_c, humidity)."""
        return self.temperature_c, self.humidity

    def get_digital_state(self) -> Tuple[bool, bool]:
        """Returns (motion_detected, touch_detected)."""
        return self.motion_detected, self.touch_detected
