// detector.h - Frame-difference motion detection on a grayscale frame.
//
// Mirrors the intent of code/rpi/vision.py: diff against the previous frame,
// threshold, and reduce the changed region to a single camera-relative bearing
// (azimuth/elevation) plus an apparent angular size. The ESP32 does a cheap
// single-blob centroid rather than full contouring.
#pragma once

#include <stdint.h>

struct Detection {
    bool valid;
    float azimuth;       // camera-relative, degrees (within +/- FOV/2)
    float elevation;     // degrees
    float angular_size;  // degrees (bbox max dimension mapped through FOV)
    int pixels;          // changed-pixel count (detection strength)
};

class Detector {
public:
    Detector(int width, int height, float fov_h_deg, float fov_v_deg,
             uint8_t threshold, int min_pixels);
    ~Detector();

    bool begin();  // allocates the previous-frame buffer (false on OOM)

    // frame: `width*height` grayscale bytes. Returns a Detection (valid=false
    // on the first frame or when motion is below min_pixels).
    Detection process(const uint8_t* frame);

private:
    int w_, h_;
    float fov_h_, fov_v_;
    uint8_t thresh_;
    int min_pixels_;
    uint8_t* prev_;
    bool have_prev_;

    void pixelToAngles(float cx, float cy, float& az, float& el) const;
};
