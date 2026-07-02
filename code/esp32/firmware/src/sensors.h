
// sensors.h - GNSS (NEO-6M/M8N/M9N) and IMU (MPU-6050 / BNO08x) drivers.
//
// GNSS gives lat/lon/alt; IMU gives roll/pitch/yaw. Together they form the pose
// carried in the LoRa ANNOUNCE. Both can share one I2C bus (see config.h) to
// conserve the ESP32-CAM's scarce free pins; a UART NEO-6M is also supported.
#pragma once

#include <stdint.h>

struct Pose {
    bool has_fix;       // GNSS lock acquired
    double lat, lon;    // degrees
    float alt;          // metres
    float roll, pitch, yaw;  // degrees
};

class Gnss {
public:
    bool begin();       // opens UART or I2C per config
    void poll();        // feed the parser; call frequently
    bool hasFix() const;
    double lat() const;
    double lon() const;
    float alt() const;
};

class Imu {
public:
    bool begin();       // shares the I2C bus (Wire) with the GNSS if I2C GNSS
    void update();      // read + complementary-filter; call every loop
    float roll() const { return roll_; }
    float pitch() const { return pitch_; }
    float yaw() const { return yaw_; }

private:
    float roll_ = 0, pitch_ = 0, yaw_ = 0;
    uint32_t last_us_ = 0;
    bool ok_ = false;
};
