// detector.cpp - see detector.h
#include "detector.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

Detector::Detector(int width, int height, float fov_h_deg, float fov_v_deg,
                   uint8_t threshold, int min_pixels)
    : w_(width), h_(height), fov_h_(fov_h_deg), fov_v_(fov_v_deg),
      thresh_(threshold), min_pixels_(min_pixels), prev_(nullptr), have_prev_(false) {}

Detector::~Detector() {
    if (prev_) free(prev_);
}

bool Detector::begin() {
    prev_ = (uint8_t*)malloc((size_t)w_ * h_);
    return prev_ != nullptr;
}

void Detector::pixelToAngles(float cx, float cy, float& az, float& el) const {
    // Match rpi/vision.py::_pixel_to_angles: normalise to [-0.5,0.5], invert Y,
    // scale by the field of view. Result is a CAMERA-RELATIVE bearing.
    float nx = (cx / (float)w_) - 0.5f;
    float ny = 0.5f - (cy / (float)h_);  // image Y grows downward
    az = nx * fov_h_;
    el = ny * fov_v_;
}

Detection Detector::process(const uint8_t* frame) {
    Detection d = {false, 0.0f, 0.0f, 0.0f, 0};
    if (!prev_) return d;

    if (!have_prev_) {
        memcpy(prev_, frame, (size_t)w_ * h_);
        have_prev_ = true;
        return d;  // need two frames to diff
    }

    // Accumulate centroid + bounding box of all changed pixels (single blob).
    long count = 0;
    double sum_x = 0.0, sum_y = 0.0;
    int min_x = w_, min_y = h_, max_x = -1, max_y = -1;

    for (int y = 0; y < h_; y++) {
        const int row = y * w_;
        for (int x = 0; x < w_; x++) {
            int cur = frame[row + x];
            int diff = cur - (int)prev_[row + x];
            if (diff < 0) diff = -diff;
            if (diff >= thresh_) {
                count++;
                sum_x += x;
                sum_y += y;
                if (x < min_x) min_x = x;
                if (x > max_x) max_x = x;
                if (y < min_y) min_y = y;
                if (y > max_y) max_y = y;
            }
        }
    }

    // Roll the current frame into prev for the next diff.
    memcpy(prev_, frame, (size_t)w_ * h_);

    if (count < min_pixels_) return d;

    float cx = (float)(sum_x / (double)count);
    float cy = (float)(sum_y / (double)count);
    pixelToAngles(cx, cy, d.azimuth, d.elevation);

    int bw = max_x - min_x + 1;
    int bh = max_y - min_y + 1;
    int max_dim = bw > bh ? bw : bh;
    d.angular_size = ((float)max_dim / (float)w_) * fov_h_;  // rough cone size
    d.pixels = (int)count;
    d.valid = true;
    return d;
}
