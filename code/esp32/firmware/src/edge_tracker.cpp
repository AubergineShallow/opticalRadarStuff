
// edge_tracker.cpp - see edge_tracker.h
#include "edge_tracker.h"
#include <math.h>
#include <string.h>

EdgeTracker::EdgeTracker(int required_hits, uint32_t max_missed_ms, float assoc_deg)
    : required_hits_(required_hits), max_missed_ms_(max_missed_ms),
      assoc_deg_(assoc_deg), next_id_(1) {
    memset(tracks_, 0, sizeof(tracks_));
}

int EdgeTracker::findNearest(float az, float el) const {
    int best = -1;
    float best_dist = assoc_deg_;
    for (int i = 0; i < EDGE_MAX_TRACKS; i++) {
        if (!tracks_[i].used) continue;
        float d_az = fabsf(tracks_[i].az - az);
        if (d_az > 180.0f) d_az = 360.0f - d_az;  // wrap
        float d_el = fabsf(tracks_[i].el - el);
        float dist = sqrtf(d_az * d_az + d_el * d_el);
        if (dist < best_dist) {
            best_dist = dist;
            best = i;
        }
    }
    return best;
}

int EdgeTracker::allocSlot() const {
    for (int i = 0; i < EDGE_MAX_TRACKS; i++) {
        if (!tracks_[i].used) return i;
    }
    return -1;  // full; detection is dropped this frame
}

void EdgeTracker::cleanup(uint32_t now_ms) {
    for (int i = 0; i < EDGE_MAX_TRACKS; i++) {
        if (tracks_[i].used && (now_ms - tracks_[i].last_seen_ms) > max_missed_ms_) {
            memset(&tracks_[i], 0, sizeof(EdgeTrack));
        }
    }
}

void EdgeTracker::update(const Detection& det, uint32_t now_ms) {
    if (det.valid) {
        int idx = findNearest(det.azimuth, det.elevation);
        if (idx >= 0) {
            EdgeTrack& t = tracks_[idx];
            t.az = det.azimuth;
            t.el = det.elevation;
            t.angular_size = det.angular_size;
            t.last_seen_ms = now_ms;
            if (t.hits < 1000000) t.hits++;
            if (t.hits >= required_hits_) t.active = true;
        } else {
            int slot = allocSlot();
            if (slot >= 0) {
                EdgeTrack& t = tracks_[slot];
                t.used = true;
                t.active = false;
                t.id = next_id_;
                next_id_ = (uint8_t)((next_id_ % 250) + 1);  // keep inside uint8
                t.az = det.azimuth;
                t.el = det.elevation;
                t.angular_size = det.angular_size;
                t.hits = 1;
                t.last_seen_ms = now_ms;
            }
        }
    }
    cleanup(now_ms);
}

void EdgeTracker::ageOnly(uint32_t now_ms) {
    cleanup(now_ms);
}
