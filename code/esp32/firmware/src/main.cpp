// main.cpp - ESP32-CAM optical tracking edge node.
//
// Pipeline (mirrors the RPi LoRa node):
//   OV2640 grayscale frame -> frame-diff detector -> maturation edge-tracker
//   -> compressed LoRa payloads -> radio backend (Meshtastic / SX127x / WiFi).
// Pose for the ANNOUNCE comes from the GNSS + IMU on the shared I2C bus.
//
// See README.md for wiring, the tight ESP32-CAM pin budget, and how node ids
// map to the server's node_specs.json.

#include <Arduino.h>
#include "esp_camera.h"

#include "../include/config.h"
#include "detector.h"
#include "edge_tracker.h"
#include "sensors.h"
#include "radio.h"

// ---- AI-Thinker ESP32-CAM camera pin map (fixed by the board) --------------
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

static Detector g_detector(FRAME_WIDTH, FRAME_HEIGHT, FOV_HORIZONTAL_DEG,
                           FOV_VERTICAL_DEG, DETECT_THRESHOLD, DETECT_MIN_PIXELS);
static EdgeTracker g_tracker(TRACK_REQUIRED_HITS, TRACK_MAX_MISSED_MS, TRACK_ASSOC_DEG);
static Gnss g_gnss;
static Imu g_imu;
static Radio* g_radio = nullptr;

static uint32_t g_last_announce = 0;
static uint32_t g_last_update_burst = 0;

// Non-blocking update-burst state: index of the next track to consider, or -1
// when idle. One payload is sent per loop() pass, spaced UPDATE_TX_SPACING_MS,
// so the capture/detect/sensor pipeline keeps running between radio sends
// (the old delay(300) stalled the whole node for 0.3s per mature track).
#define UPDATE_TX_SPACING_MS 300
static int g_burst_next = -1;
static uint32_t g_last_update_tx = 0;

static bool cameraInit() {
    camera_config_t c = {};
    c.ledc_channel = LEDC_CHANNEL_0;
    c.ledc_timer = LEDC_TIMER_0;
    c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;
    c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
    c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;
    c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
    c.pin_xclk = XCLK_GPIO_NUM;
    c.pin_pclk = PCLK_GPIO_NUM;
    c.pin_vsync = VSYNC_GPIO_NUM;
    c.pin_href = HREF_GPIO_NUM;
    c.pin_sccb_sda = SIOD_GPIO_NUM;
    c.pin_sccb_scl = SIOC_GPIO_NUM;
    c.pin_pwdn = PWDN_GPIO_NUM;
    c.pin_reset = RESET_GPIO_NUM;
    c.xclk_freq_hz = 20000000;
    c.pixel_format = PIXFORMAT_GRAYSCALE;   // 1 byte/pixel -> cheap frame-diff
    c.frame_size = FRAMESIZE_QQVGA;         // 160x120 (== FRAME_WIDTH/HEIGHT)
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_PSRAM;
    c.grab_mode = CAMERA_GRAB_LATEST;
    return esp_camera_init(&c) == ESP_OK;
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.printf("\n[ESP32-CAM node %d] booting\n", NODE_ID);

    if (!cameraInit())   Serial.println("ERROR: camera init failed");
    if (!g_detector.begin()) Serial.println("ERROR: detector alloc failed (PSRAM?)");
    if (!g_imu.begin())  Serial.println("WARN: IMU init failed (orientation = 0)");
    if (!g_gnss.begin()) Serial.println("WARN: GNSS init failed (no fix)");

    g_radio = getRadio();
    if (!g_radio->begin()) Serial.printf("WARN: radio '%s' begin failed\n", g_radio->name());
    Serial.printf("[ESP32-CAM] radio backend: %s\n", g_radio->name());
}

static void sendAnnounce(uint32_t now) {
    g_last_announce = now;
    if (!g_gnss.hasFix()) {
        // No fix -> no usable pose. A (0,0,0) announce would have the server
        // caching a position in the Gulf of Guinea and building rays from an
        // origin thousands of km outside the grid. Retry next interval.
        Serial.println("[TX] ANNOUNCE skipped (no GNSS fix)");
        return;
    }
    float lat = (float)g_gnss.lat();
    float lon = (float)g_gnss.lon();
    float alt = g_gnss.alt();
    g_radio->sendAnnounce(NODE_ID, lat, lon, alt,
                          g_imu.roll(), g_imu.pitch(), g_imu.yaw());
    Serial.printf("[TX] ANNOUNCE fix=%d lat=%.6f lon=%.6f yaw=%.1f\n",
                  g_gnss.hasFix(), lat, lon, g_imu.yaw());
}

// Advance the current update burst by AT MOST one radio send. Sub-sends stay
// spaced UPDATE_TX_SPACING_MS apart so a Meshtastic Serial Module packetises
// each payload separately (see radio.cpp), but the spacing is now enforced
// across loop() passes instead of a blocking delay().
static void sendMatureTracks(uint32_t now) {
    if (g_burst_next < 0) return;                          // no burst active
    if (now - g_last_update_tx < UPDATE_TX_SPACING_MS) return;

    while (g_burst_next < g_tracker.trackCount()) {
        const EdgeTrack& t = g_tracker.track(g_burst_next++);
        if (!t.used || !t.active) continue;
        g_radio->sendUpdate(NODE_ID, t.id, t.az, t.el, t.angular_size);
        Serial.printf("[TX] UPDATE id=%d az=%.1f el=%.1f\n", t.id, t.az, t.el);
        g_last_update_tx = now;
        return;                                            // one send per pass
    }

    // Walked every track: the burst is complete.
    g_burst_next = -1;
    g_last_update_burst = now;
}

void loop() {
    const uint32_t frame_period = 1000 / DETECT_FPS;
    uint32_t t_start = millis();

    // Keep sensors fresh every loop.
    g_gnss.poll();
    g_imu.update();

    // Capture + detect.
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
        Detection det = g_detector.process(fb->buf);
        esp_camera_fb_return(fb);
        uint32_t now = millis();
        if (det.valid) g_tracker.update(det, now);
        else           g_tracker.ageOnly(now);
    }

    uint32_t now = millis();

    // Periodic pose announce (server needs it to place rays).
    if (now - g_last_announce >= ANNOUNCE_INTERVAL_MS) {
        sendAnnounce(now);
    }

    // Duty-cycled track updates: start a burst when the gap has elapsed, then
    // drain it one non-blocking send per loop pass.
    if (g_burst_next < 0 && now - g_last_update_burst >= UPDATE_MIN_GAP_MS) {
        g_burst_next = 0;
    }
    sendMatureTracks(now);

    // Pace the detection loop.
    uint32_t elapsed = millis() - t_start;
    if (elapsed < frame_period) delay(frame_period - elapsed);
}
