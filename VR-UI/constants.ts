/**
 * VR-UI configuration.
 *
 * COORDINATE_ORIGIN must match the server's `reference.origin_lat/lon/alt`
 * (common/config.py) and NEW-UI-V2's COORDINATE_ORIGIN — the one-origin rule
 * in geometry-conventions. When deploying to a new site change all of them.
 */

export const VR_CONFIG = {
    // ENU reference origin (WGS84). Server default: San Francisco.
    COORDINATE_ORIGIN: { lat: 37.7749, lon: -122.4194, alt: 0.0 },

    // Rendering caps — every collection bounded (quality-standards). The
    // server already caps its broadcasts; these are the client-side defense.
    MAX_RENDER_TRACKS: 128,
    MAX_RENDER_RAYS: 512,
    MAX_RENDER_VOXELS: 2048,
    MAX_TRAIL_POINTS: 60,          // ≈2 s at 30 Hz, same as NEW-UI-V2
    MAX_LABELS: 64,

    // Shorter than NEW-UI-V2's 5000 m so rays don't dwarf the tabletop.
    RAY_LENGTH_METERS: 2000,
    VOXEL_SIZE_METERS: 10,
    GRID_RADIUS_METERS: 1000,

    // Track glyph sizing (ENU metres, before tabletop scaling).
    TRACK_MIN_RADIUS_M: 8,
    TRACK_MAX_RADIUS_M: 60,
    TRACK_HIT_RADIUS_M: 50,        // invisible pick sphere for the controller ray
    VELOCITY_VECTOR_SECONDS: 2.0,  // arrow = position + velocity * this

    NODE_RADIUS_M: 10,
    STALE_NODE_SECONDS: 10,        // same threshold the 2D sensor list uses

    TABLETOP: {
        DEFAULT_SCALE: 1 / 1000,   // 2 km of world → 2 m table
        MIN_SCALE: 1 / 20000,
        MAX_SCALE: 1 / 50,
        HEIGHT_M: 0.75,            // table height above the local floor
        DISTANCE_M: 1.2,           // in front of the user at session start
    },

    HUD: {
        // Target designators are drawn on a head-centered dome at this radius
        // (comfortable vergence distance for far-field annotation) at constant
        // ANGULAR size — a 2 km target rendered 1:1 would be invisible.
        DOME_RADIUS_M: 20,
        MARKER_ANGULAR_DEG: 2.5,       // designator width as seen by the user
        LABEL_ANGULAR_DEG: 9,          // label width
        LEADER_MIN_SPEED_MS: 2,        // hide velocity leader below this
        // Off-screen indicator ring (camera-local, at 1 m in front)
        EDGE_RING_X: 0.40,
        EDGE_RING_Y: 0.28,
        MAX_EDGE_ARROWS: 8,
        // Ground reference grid shown in VR / flat fallback (hidden when the
        // session has real passthrough)
        GROUND_GRID_RADIUS_M: 30,
    },

    // Intercept (CBDR) warning — computed ON THE HEADSET from broadcast
    // track kinematics + the local geo pose (threat.ts). A track is flagged
    // when it is actively closing and its predicted miss distance at closest
    // approach is small (constant bearing, decreasing range).
    THREAT: {
        MIN_CLOSING_MS: 2,        // must be closing at least this fast
        TCA_MAX_S: 60,            // ...and arriving within this horizon
        MISS_DISTANCE_M: 75,      // ...with a predicted miss inside this
        EMA_TAU_S: 0.4,           // per-track smoothing of the raw verdict
        ENTER_EMA: 0.6,           // hysteresis: flag above this...
        EXIT_EMA: 0.3,            // ...clear below this
        FLASH_HZ: 3,
    },

    // Depth cues for HUD designators (range is otherwise only a number):
    // size attenuation around a reference range, opacity fade for far
    // targets, and true-depth placement once inside the dome radius (real
    // stereopsis + motion parallax take over close-in).
    DEPTH: {
        REF_RANGE_M: 500,         // designator has nominal size at this range
        SIZE_EXP: 0.35,           // attenuation curve (perceptual, not linear)
        SIZE_MIN: 0.65,
        SIZE_MAX: 1.6,
        FADE_START_M: 2000,
        FADE_RANGE_M: 8000,
        MIN_OPACITY: 0.5,
    },

    // Operator geo feed
    GEO_STALE_SECONDS: 10,

    COLORS: {
        BACKGROUND: 0x02040a,
        GRID: 0x0a3a2a,
        GRID_MAJOR: 0x0f5c3f,
        TRACK_CONFIRMED: 0xff2020,
        TRACK_TENTATIVE: 0xffaa00,
        TRACK_LOST: 0x808080,
        TRACK_SELECTED: 0x00ffff,
        TRAIL: 0xff6060,
        RAY: 0x00ffff,
        VOXEL_COLD: 0x2040ff,
        VOXEL_HOT: 0xff4000,
        NODE_HEALTHY: 0x00ff41,
        NODE_DEGRADED: 0xffff00,
        NODE_FAILING: 0xff8000,
        NODE_OFFLINE: 0xff0000,
        NODE_STALE: 0x606060,
        LABEL: '#ffffff',
        HUD_ACCENT: '#00ff41',
        POINTER: 0x00ff41,
    },
};

export const Env = {
    // Server WebSocket (matches server.ws_port). On the headset pass
    // ?ws=ws://<server-ip>:5000/ws — localhost only works for desktop dev.
    WS_URL: 'ws://localhost:5000/ws',

    // GeoTether companion app on the tethered phone. 192.168.42.129 is the
    // stock Android USB-tethering gateway; override with ?geo=ws://<ip>:8790
    // (or ?geo=off to disable and use ?lat/?lon/?alt/?heading instead).
    GEO_WS_URL: 'ws://192.168.42.129:8790',
};
