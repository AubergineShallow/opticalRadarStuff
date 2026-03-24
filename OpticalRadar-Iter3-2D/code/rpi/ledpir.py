from gpiozero import Button, LED
from time import sleep

# --- SETUP ---
pir = Button(6, pull_up=False)
led = LED(17) # Telling the Pi the LED is on GPIO 17

print("--- PIR LED CONTROL ---")

try:
    while True:
        if pir.is_pressed:
            led.on()
            print("👤 MOTION! -> LED ON ", end="\r")
        else:
            led.off()
            print("  Quiet... -> LED OFF", end="\r")
        sleep(0.1)
except KeyboardInterrupt:
    led.off()