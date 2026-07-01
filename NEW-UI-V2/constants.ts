
import { NodeHealthStatus } from "./types";

export const UI_CONFIG = {
    // Map Defaults (San Francisco)
    INITIAL_VIEW_STATE: {
        latitude: 37.7749,
        longitude: -122.4194,
        zoom: 14,
        pitch: 60,
        bearing: 0
    },
    // Reference Origin for ENU conversions (Matches Initial View)
    COORDINATE_ORIGIN: [-122.4194, 37.7749, 0] as [number, number, number],

    // Visualization Settings
    RAY_LENGTH_METERS: 5000,
    VOXEL_SIZE_METERS: 10,
    TRACK_POINT_RADIUS: 20,
    NODE_POINT_RADIUS: 5,

    // Colors [R, G, B, A]
    COLORS: {
        NODE_HEALTHY: [0, 255, 65] as [number, number, number],
        NODE_ISSUE: [255, 0, 0] as [number, number, number],
        RAY_DEFAULT: [0, 255, 255, 50] as [number, number, number, number],
        TRACK_DEFAULT: [255, 0, 0] as [number, number, number],
        TEXT_LABEL: [255, 255, 255] as [number, number, number],
    },

    // Offline / Free Map Style (CartoDB Dark Matter)
    OFFLINE_MAP_STYLE: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
};

export const Env = {
    // Default to localhost:5000/ws for WebSocket
    WS_URL: 'ws://localhost:5000/ws',
    // Check URL param ?mock=true
    ENABLE_MOCK_DATA: false
};

export const STATUS_COLORS = {
    [NodeHealthStatus.HEALTHY]: "text-green-500",
    [NodeHealthStatus.DEGRADED]: "text-yellow-500",
    [NodeHealthStatus.FAILING]: "text-orange-500",
    [NodeHealthStatus.OFFLINE]: "text-red-500",
};
