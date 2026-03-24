import time
import board
import adafruit_dht

# Initialize the DHT11 sensor.
# Note: We use board.D4 to specify GPIO 4.
# If you used a different GPIO pin, change the number here!
dhtDevice = adafruit_dht.DHT11(board.D4)

print("--- CLIMATE SENSOR DASHBOARD ---")
print("Waking up sensor (takes 2 seconds)...")
print("Press Ctrl+C to exit.\n")

try:
    while True:
        try:
            # Tell the sensor to take a reading
            temperature_c = dhtDevice.temperature
            humidity = dhtDevice.humidity

            # Print the data cleanly
            print(f"Temp: {temperature_c:.1f}°C  |  Humidity: {humidity}%")

        except RuntimeError as error:
            # DHT sensors are hard to read and will frequently fail.
            # This try/except block catches those errors and just tries again.
            print(f"Reading error: {error.args[0]} - Retrying...")
            time.sleep(2.0)
            continue
        except Exception as error:
            dhtDevice.exit()
            raise error

        # MUST wait at least 2 seconds before asking for data again
        time.sleep(2.0)

except KeyboardInterrupt:
    print("\n\nDashboard closed. Cleaning up...")
    dhtDevice.exit()