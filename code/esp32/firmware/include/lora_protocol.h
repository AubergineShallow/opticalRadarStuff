// lora_protocol.h - Byte-exact mirror of code/common/lora_protocol.py.
//
// CRITICAL: these packers must produce the EXACT bytes the Python
// unpack_lora() expects, or the server silently drops the payloads.
//
//   ANNOUNCE (20 bytes): <B B f f f h h h>
//     type=0x01, node_id, lat, lon, alt, roll*100, pitch*100, yaw*100
//   UPDATE   (7 bytes) : <B B B H b B>
//     type=0x02, node_id, track_id, az_u16, el_i8, size_u8
//
// The ESP32 (Xtensa) is little-endian, matching Python's '<' byte order, so
// float32 fields are copied straight through. Integers are written low-byte
// first to stay explicit and portable.
#pragma once

#include <stdint.h>
#include <string.h>
#include <math.h>

#define LORA_MSG_TYPE_ANNOUNCE 0x01
#define LORA_MSG_TYPE_UPDATE   0x02
#define LORA_ANNOUNCE_SIZE     20
#define LORA_UPDATE_SIZE       7

// ---- little-endian primitives ---------------------------------------------
static inline void le_put_u16(uint8_t* p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
}
static inline void le_put_i16(uint8_t* p, int16_t v) { le_put_u16(p, (uint16_t)v); }
static inline void le_put_f32(uint8_t* p, float v) { memcpy(p, &v, 4); } // LE host

// clamp helper matching the Python quantisation
static inline int16_t clamp_i16(long v) {
    if (v < -32768) return -32768;
    if (v > 32767) return 32767;
    return (int16_t)v;
}

// Quantise to an integer the SAME way Python's int() does: truncate toward
// zero (NOT round-to-nearest). Using lroundf here would produce off-by-one
// bytes vs the server and get the payload dropped. Do the arithmetic in double
// to match Python's float precision.
static inline long trunc_toward_zero(double v) { return (long)v; }

// Wrap an angle into [-180,180). The int16 centidegree encoding only spans
// +/-327.67 deg, so a heading (0..360) must be wrapped or it overflows. This is
// lossless for the server (orientation goes through a periodic from_euler()).
static inline double wrap180(double a) {
    a = fmod(a + 180.0, 360.0);
    if (a < 0) a += 360.0;
    return a - 180.0;
}

// Pack an ANNOUNCE. `out` must hold LORA_ANNOUNCE_SIZE bytes. Returns length.
static inline int lora_pack_announce(uint8_t* out, uint8_t node_id,
                                     float lat, float lon, float alt,
                                     float roll_deg, float pitch_deg, float yaw_deg) {
    out[0] = LORA_MSG_TYPE_ANNOUNCE;
    out[1] = node_id;
    le_put_f32(out + 2, lat);
    le_put_f32(out + 6, lon);
    le_put_f32(out + 10, alt);
    le_put_i16(out + 14, clamp_i16(trunc_toward_zero(wrap180((double)roll_deg) * 100.0)));
    le_put_i16(out + 16, clamp_i16(trunc_toward_zero(wrap180((double)pitch_deg) * 100.0)));
    le_put_i16(out + 18, clamp_i16(trunc_toward_zero(wrap180((double)yaw_deg) * 100.0)));
    return LORA_ANNOUNCE_SIZE;
}

// Pack an UPDATE. `out` must hold LORA_UPDATE_SIZE bytes. Returns length.
//   azimuth   in [0,360)  (camera-relative bearing)
//   elevation in [-90,90]
//   angular_size in [0,180]
static inline int lora_pack_update(uint8_t* out, uint8_t node_id, uint8_t track_id,
                                   float azimuth, float elevation, float angular_size) {
    // All quantisation truncates toward zero to match Python's int() exactly.
    double az = fmod((double)azimuth, 360.0);
    if (az < 0) az += 360.0;
    uint16_t az_u16 = (uint16_t)(trunc_toward_zero((az / 360.0) * 65535.0) & 0xFFFF);

    long el = trunc_toward_zero((double)elevation);
    if (el < -128) el = -128;
    if (el > 127) el = 127;

    long sz = trunc_toward_zero(((double)angular_size / 180.0) * 255.0);
    if (sz < 0) sz = 0;
    if (sz > 255) sz = 255;

    out[0] = LORA_MSG_TYPE_UPDATE;
    out[1] = node_id;
    out[2] = track_id;
    le_put_u16(out + 3, az_u16);
    out[5] = (uint8_t)(int8_t)el;
    out[6] = (uint8_t)sz;
    return LORA_UPDATE_SIZE;
}

// ---- CRC-16/CCITT-FALSE (mirror of crc16_ccitt in the Python module) -------
static inline uint16_t lora_crc16_ccitt(const uint8_t* data, int len) {
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

// Frame a payload for a raw serial byte stream: AA 55 | len | payload | crc16(LE).
// Used only by the raw-serial paths (SX127x bridge / some Serial-Module modes).
// `out` must hold len + 5 bytes. Returns framed length.
static inline int lora_frame(uint8_t* out, const uint8_t* payload, uint8_t len) {
    out[0] = 0xAA;
    out[1] = 0x55;
    out[2] = len;
    memcpy(out + 3, payload, len);
    uint16_t crc = lora_crc16_ccitt(payload, len);
    le_put_u16(out + 3 + len, crc);
    return len + 5;
}
