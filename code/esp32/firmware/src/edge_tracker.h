
// edge_tracker.h - Lightweight maturation tracker (mirror of
// code/rpi/lora_edge_tracker.py). Groups noisy per-frame detections into
// persistent tracks and only reports a track once it has been seen
// REQUIRED_HITS times, so we don't spend LoRa airtime on flicker.
#pragma once

#include <stdint.h>
#include "detector.h"

#define EDGE_MAX_TRACKS 8

struct EdgeTrack {
    bool used;
    bool active;         // mature: seen >= required_hits
    uint8_t id;          // 1..250 (fits the uint8 wire field)
    float az;
    float el;
    float angular_size;
    int hits;
    uint32_t last_seen_ms;
};

class EdgeTracker {
public:
    EdgeTracker(int required_hits, uint32_t max_missed_ms, float assoc_deg);

    // Associate a single detection (or none) into the track set and age out
    // stale tracks. Call every detection frame.
    void update(const Detection& det, uint32_t now_ms);
    void ageOnly(uint32_t now_ms);  // no detection this frame

    int trackCount() const { return EDGE_MAX_TRACKS; }
    const EdgeTrack& track(int i) const { return tracks_[i]; }

private:
    EdgeTrack tracks_[EDGE_MAX_TRACKS];
    int required_hits_;
    uint32_t max_missed_ms_;
    float assoc_deg_;
    uint8_t next_id_;

    int findNearest(float az, float el) const;
    int allocSlot() const;
    void cleanup(uint32_t now_ms);
};
