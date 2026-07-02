
// sensors.cpp - see sensors.h
#include "sensors.h"
#include "../include/config.h"

#include <Arduino.h>
#include <Wire.h>
#include <TinyGPSPlus.h>
#include <math.h>

// --------------------------------------------------------------------------
// GNSS
// --------------------------------------------------------------------------
static TinyGPSPlus s_gps;

#if USE_GNSS_I2C
// Read up to `max` bytes from a u-blox DDC (I2C) module and feed the parser.
static void gnss_i2c_pump(int max_bytes) {
    // Bytes-available is a 16-bit count at registers 0xFD/0xFE.
    Wire.beginTransmission(GNSS_I2C_ADDR);
    Wire.write(0xFD);
    if (Wire.endTransmission(false) != 0) return;
    if (Wire.requestFrom(GNSS_I2C_ADDR, 2) != 2) return;
    int hi = Wire.read();
    int lo = Wire.read();
    int avail = (hi << 8) | lo;
    if (avail <= 0) return;
    if (avail > max_bytes) avail = max_bytes;

    // Stream comes from register 0xFF.
    int remaining = avail;
    while (remaining > 0) {
        int chunk = remaining > 32 ? 32 : remaining;
        Wire.beginTransmission(GNSS_I2C_ADDR);
        Wire.write(0xFF);
        if (Wire.endTransmission(false) != 0) return;
        int got = Wire.requestFrom(GNSS_I2C_ADDR, chunk);
        for (int i = 0; i < got; i++) {
            int c = Wire.read();
            if (c >= 0 && c != 0xFF) s_gps.encode((char)c);
        }
        remaining -= got;
        if (got < chunk) break;
    }
}
#else
static HardwareSerial s_gnss_serial(GNSS_UART_NUM);
#endif

bool Gnss::begin() {
#if USE_GNSS_I2C
    // Wire is initialised once by whoever calls first (Imu or here); safe to
    // call again with the configured pins.
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    return true;
#else
    s_gnss_serial.begin(GNSS_BAUD, SERIAL_8N1, GNSS_RX_PIN, GNSS_TX_PIN);
    return true;
#endif
}

void Gnss::poll() {
#if USE_GNSS_I2C
    gnss_i2c_pump(64);
#else
    while (s_gnss_serial.available() > 0) {
        s_gps.encode((char)s_gnss_serial.read());
    }
#endif
}

bool Gnss::hasFix() const { return s_gps.location.isValid() && s_gps.location.age() < 5000; }
double Gnss::lat() const { return s_gps.location.lat(); }
double Gnss::lon() const { return s_gps.location.lng(); }
float Gnss::alt() const { return s_gps.altitude.isValid() ? (float)s_gps.altitude.meters() : 0.0f; }

// --------------------------------------------------------------------------
// IMU (MPU-6050). For a BNO08x you would read its absolute quaternion instead
// and skip the complementary filter; the interface stays the same.
// --------------------------------------------------------------------------
static const uint8_t MPU_PWR_MGMT_1 = 0x6B;
static const uint8_t MPU_ACCEL_XOUT_H = 0x3B;

static bool mpu_write(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(IMU_I2C_ADDR);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

static bool mpu_read(uint8_t reg, uint8_t* buf, int n) {
    Wire.beginTransmission(IMU_I2C_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    int got = Wire.requestFrom(IMU_I2C_ADDR, n);
    for (int i = 0; i < got && i < n; i++) buf[i] = Wire.read();
    return got == n;
}

bool Imu::begin() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    ok_ = mpu_write(MPU_PWR_MGMT_1, 0x00);  // wake from sleep
    last_us_ = micros();
    return ok_;
}

void Imu::update() {
    if (!ok_) return;
    uint8_t b[14];
    if (!mpu_read(MPU_ACCEL_XOUT_H, b, 14)) return;

    int16_t ax = (b[0] << 8) | b[1];
    int16_t ay = (b[2] << 8) | b[3];
    int16_t az = (b[4] << 8) | b[5];
    // b[6..7] = temperature (skipped)
    int16_t gx = (b[8] << 8) | b[9];
    int16_t gy = (b[10] << 8) | b[11];
    int16_t gz = (b[12] << 8) | b[13];

    // Scale: accel +/-2g -> /16384 g; gyro +/-250 dps -> /131 dps.
    float axg = ax / 16384.0f, ayg = ay / 16384.0f, azg = az / 16384.0f;
    float gxd = gx / 131.0f, gyd = gy / 131.0f, gzd = gz / 131.0f;

    uint32_t now = micros();
    float dt = (now - last_us_) / 1000000.0f;
    last_us_ = now;
    if (dt <= 0 || dt > 0.5f) dt = 0.0f;  // guard against first-call / stalls

    // Accel-derived roll/pitch (degrees).
    float roll_acc = atan2f(ayg, azg) * 57.29578f;
    float pitch_acc = atan2f(-axg, sqrtf(ayg * ayg + azg * azg)) * 57.29578f;

    // Complementary filter blends gyro integration with the accel reference.
    const float alpha = 0.98f;
    roll_ = alpha * (roll_ + gxd * dt) + (1.0f - alpha) * roll_acc;
    pitch_ = alpha * (pitch_ + gyd * dt) + (1.0f - alpha) * pitch_acc;
    // No magnetometer on the MPU-6050: yaw is gyro-integrated and WILL drift.
    // Provision a fixed installation heading, or use a BNO08x for absolute yaw.
    yaw_ += gzd * dt;
    if (yaw_ >= 360.0f) yaw_ -= 360.0f;
    if (yaw_ < 0.0f) yaw_ += 360.0f;
}
