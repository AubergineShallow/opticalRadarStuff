/**
 * OpticalRadar VR-UI Data Types
 *
 * Wire types mirror NEW-UI-V2/types.ts (which mirrors the server broadcast
 * payloads) — keep the three in sync when the backend contract changes.
 * VR-specific additions live at the bottom (GeoPose, ViewMode).
 */

// Coordinate System: ENU (East-North-Up) in Meters
// Vector3: [x, y, z] or [East, North, Up]
export type Vector3 = [number, number, number];

// Ray: Visual representation of a MotionVector in 3D space
export interface Ray {
    origin: Vector3;       // Camera position (ENU)
    direction: Vector3;    // Normalized direction vector
    intensity: number;     // [0, 255]
    camera_id: string;
    timestamp: number;
    cluster_id?: string;
}

// Voxel: 3D Grid Unit
export interface Voxel {
    x: number; // ENU Center X (Meters)
    y: number; // ENU Center Y (Meters)
    z: number; // ENU Center Z (Meters)
    intensity: number; // [0, 255]
    timestamp: number;
    cluster_id?: string;
}

export enum TrackState {
    TENTATIVE = 0,
    CONFIRMED = 1,
    LOST = 2,
    DELETED = 3,
}

export interface Track {
    track_id: number;
    state: TrackState;
    position: Vector3;      // ENU [East, North, Up]
    velocity: Vector3;      // m/s [vE, vN, vU]
    covariance: number[][]; // 3x3 matrix
    first_seen: number;     // Unix timestamp
    last_seen: number;      // Unix timestamp
    hit_count: number;
    confidence: number;     // [0.0, 1.0]
    predicted_next: Vector3;
    cluster_id?: string;
    // EMA-smoothed physical size estimate in metres (server-side fusion).
    // 0 / absent = no estimate available.
    physical_size?: number;
}

export enum NodeHealthStatus {
    HEALTHY = 0,
    DEGRADED = 1,
    FAILING = 2,
    OFFLINE = 3,
}

export interface SensorConfig {
    azimuth_deg: number;
    elevation_deg: number;
    hfov_deg: number;
    vfov_deg: number;
}

export interface NodeHealth {
    node_id: string;
    status: NodeHealthStatus;
    last_seen: number;     // Unix timestamp
    fps: number;
    cpu_usage: number;     // Percentage [0, 100]
    temp_c: number;        // Celsius
    ip_address: string;
    location: Vector3;     // ENU
    sensor_config?: SensorConfig;
    cluster_id?: string;
}

export interface ClusterInfo {
    cluster_id: string;
    node_ids: string[];
    track_count: number;
    voxel_resolution_m: number;
}

export interface SystemStatus {
    server_fps: number;
    total_tracks: number;
    total_voxels: number;
    uptime_seconds: number;
    cpu_percent: number;
    memory_percent: number;
}

export interface WSMessage {
    type: 'TRACK_UPDATE' | 'VOXEL_UPDATE' | 'RAY_UPDATE' | 'NODE_UPDATE'
        | 'SYSTEM_STATUS' | 'CLUSTER_UPDATE';
    payload: any;
}

// ---------------------------------------------------------------------------
// VR-specific types
// ---------------------------------------------------------------------------

/**
 * Geodetic pose of the operator, streamed by the GeoTether companion app on
 * the tethered Android phone (the Steam Frame has no GNSS of its own).
 * Message on the wire: { "type": "GEO_POSE", "payload": GeoPose }.
 * Altitude is height above the WGS84 ellipsoid (Android Location convention,
 * same as the rest of this project — see geometry-conventions).
 */
export interface GeoPose {
    lat: number;
    lon: number;
    alt: number;                  // m above WGS84 ellipsoid
    accuracy_m: number;           // horizontal 1-sigma
    heading_deg: number;          // TRUE north, clockwise; NaN if compass unavailable
    heading_accuracy_deg: number;
    speed_ms: number;
    timestamp: number;            // Unix float seconds
    provider: string;             // "fused" | "manual" | "mock"
}

export interface GeoWSMessage {
    type: 'GEO_POSE' | 'HELLO';
    payload: any;
}

/**
 * HUD (default): AR/MR overlay — target designators drawn at each track's
 * TRUE bearing/elevation on a head-centered annotation dome (constant
 * angular size, true range on the label), anchored to the real world via
 * the phone's GNSS fix + compass heading. This is the "look at the sky and
 * see the tracks" mode.
 * TABLETOP: miniature of the ENU scene on a virtual table in front of the
 * user (scale/rotate/pan with the controllers) — the CIC-style overview.
 */
export type ViewMode = 'HUD' | 'TABLETOP';
