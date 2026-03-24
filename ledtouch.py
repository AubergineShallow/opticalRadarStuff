from gpiozero import Button, LED
from time import sleep

# --- SETUP ---
touch = Button(5, pull_up=False)
led = LED(17) # Telling the Pi the LED is on GPIO 17

print("--- TOUCH LED CONTROL ---")

try:
    while True:
        if touch.is_pressed:
            led.on()
            print("👉 TOUCHED! -> LED ON ", end="\r")
        else:
            led.off()
            print("  Released -> LED OFF", end="\r")
        sleep(0.1)
except KeyboardInterrupt:
    led.off()