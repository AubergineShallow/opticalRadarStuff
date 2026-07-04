/**
 * VR-UI application state — zustand *vanilla* store (no React in this
 * frontend; the render loop reads state imperatively via getState() and the
 * scene layer subscribes for change detection).
 *
 * Conventions carried over from NEW-UI-V2/store.ts (each fixed a real bug):
 *  - Track list is FULL-REPLACE per frame (server sends the complete list;
 *    no per-track delete events) — merging leaves zombie tracks.
 *  - Trails are bounded (MAX_TRAIL_POINTS) and pruned for vanished tracks.
 *  - Selection lives here, never component/scene-local.
 */

import { createStore } from 'zustand/vanilla';
import {
    Track, Ray, Voxel, NodeHealth, SystemStatus, TrackState, ClusterInfo,
    Vector3, GeoPose, ViewMode,
} from './types';
import { VR_CONFIG } from './constants';

export const MAX_TRAIL_POINTS = VR_CONFIG.MAX_TRAIL_POINTS;

export interface VRState {
    // Data state (mirrors the server broadcast)
    tracks: Record<string, Track>;
    trails: Record<string, Vector3[]>;
    rays: Ray[];
    voxels: Voxel[];
    nodes: Record<string, NodeHealth>;
    system: SystemStatus;
    calibration: Record<string, string>;
    clusters: Record<string, ClusterInfo>;
    activeClusterId: string | null;

    // Connection state
    serverConnected: boolean;
    serverReconnectAttempt: number;
    geoConnected: boolean;
    mockMode: boolean;

    // Operator geodetic pose (from the GeoTether phone app / manual / mock)
    geoPose: GeoPose | null;
    // Compass heading captured at the last "align" action; null = not aligned.
    // WORLD mode yaws the whole ENU scene by this so that scene-north matches
    // true north for a user who faced `heading` at align time.
    alignmentHeadingDeg: number | null;

    // View state
    viewMode: ViewMode;
    tabletopScale: number;
    tabletopYawDeg: number;
    tabletopCenterEnu: Vector3;   // ENU point rendered at the table anchor
    showRays: boolean;            // tabletop layers
    showVoxels: boolean;
    showTrails: boolean;
    showCompass: boolean;         // HUD-mode layers
    showNodeMarkers: boolean;
    showLabels: boolean;
    hudVisible: boolean;          // the floating data panel

    // Selection (store-owned — see conventions above)
    selectedTrackId: string | null;

    // Actions
    setTracks: (tracks: Track[]) => void;
    setRays: (rays: Ray[]) => void;
    setVoxels: (voxels: Voxel[]) => void;
    updateNode: (node: NodeHealth) => void;
    updateSystemStatus: (status: SystemStatus) => void;
    setCalibration: (calibration: Record<string, string>) => void;
    setClusters: (clusters: Record<string, ClusterInfo>) => void;
    setActiveCluster: (id: string | null) => void;
    setServerConnected: (connected: boolean, attempt?: number) => void;
    setGeoConnected: (connected: boolean) => void;
    setGeoPose: (pose: GeoPose | null) => void;
    setAlignmentHeading: (deg: number | null) => void;
    setViewMode: (mode: ViewMode) => void;
    setTabletopScale: (scale: number) => void;
    setTabletopYaw: (deg: number) => void;
    setTabletopCenter: (enu: Vector3) => void;
    resetTabletop: () => void;
    toggleLayer: (layer: 'rays' | 'voxels' | 'trails' | 'compass' | 'nodes' | 'labels') => void;
    toggleHud: () => void;
    selectTrack: (id: string | null) => void;
}

const DEFAULT_SYSTEM_STATUS: SystemStatus = {
    server_fps: 0,
    total_tracks: 0,
    total_voxels: 0,
    uptime_seconds: 0,
    cpu_percent: 0,
    memory_percent: 0,
};

export function createVRStore(overrides: Partial<Pick<VRState,
    'viewMode' | 'tabletopScale' | 'activeClusterId' | 'mockMode' | 'hudVisible'>> = {}) {
    return createStore<VRState>((set) => ({
        tracks: {},
        trails: {},
        rays: [],
        voxels: [],
        nodes: {},
        system: DEFAULT_SYSTEM_STATUS,
        calibration: {},
        clusters: {},
        activeClusterId: overrides.activeClusterId ?? null,

        serverConnected: false,
        serverReconnectAttempt: 0,
        geoConnected: false,
        mockMode: overrides.mockMode ?? false,

        geoPose: null,
        alignmentHeadingDeg: null,

        viewMode: overrides.viewMode ?? 'HUD',
        tabletopScale: overrides.tabletopScale ?? VR_CONFIG.TABLETOP.DEFAULT_SCALE,
        tabletopYawDeg: 0,
        tabletopCenterEnu: [0, 0, 0],
        showRays: true,
        showVoxels: true,
        showTrails: true,
        showCompass: true,
        showNodeMarkers: true,
        showLabels: true,
        hudVisible: overrides.hudVisible ?? true,

        selectedTrackId: null,

        setTracks: (newTracks) => set((state) => {
            // Full-replace + bounded trails, pruned for vanished tracks
            // (mirrors NEW-UI-V2's zombie-track fix).
            const tracks: Record<string, Track> = {};
            const trails: Record<string, Vector3[]> = {};
            newTracks.slice(0, VR_CONFIG.MAX_RENDER_TRACKS).forEach(t => {
                if (t.state === TrackState.DELETED) return;
                const key = t.track_id.toString();
                tracks[key] = t;
                const prev = state.trails[key] || [];
                trails[key] = prev.length >= MAX_TRAIL_POINTS
                    ? [...prev.slice(prev.length - MAX_TRAIL_POINTS + 1), t.position]
                    : [...prev, t.position];
            });
            return { tracks, trails };
        }),

        setRays: (rays) => set({ rays: rays.slice(0, VR_CONFIG.MAX_RENDER_RAYS) }),

        setVoxels: (voxels) => set({ voxels: voxels.slice(0, VR_CONFIG.MAX_RENDER_VOXELS) }),

        updateNode: (node) => set((state) => ({
            nodes: { ...state.nodes, [node.node_id]: node }
        })),

        updateSystemStatus: (status) => set({ system: status }),

        setCalibration: (calibration) => set({ calibration }),

        setClusters: (clusters) => set((state) => {
            // Auto-select the first cluster as the active domain if none chosen.
            const ids = Object.keys(clusters);
            const activeClusterId = state.activeClusterId ?? (ids.length > 0 ? ids[0] : null);
            return { clusters, activeClusterId };
        }),

        setActiveCluster: (id) => set({ activeClusterId: id }),

        setServerConnected: (connected, attempt = 0) =>
            set({ serverConnected: connected, serverReconnectAttempt: attempt }),

        setGeoConnected: (connected) => set({ geoConnected: connected }),

        setGeoPose: (pose) => set({ geoPose: pose }),

        setAlignmentHeading: (deg) => set({ alignmentHeadingDeg: deg }),

        setViewMode: (mode) => set({ viewMode: mode }),

        setTabletopScale: (scale) => set({
            tabletopScale: Math.min(
                VR_CONFIG.TABLETOP.MAX_SCALE,
                Math.max(VR_CONFIG.TABLETOP.MIN_SCALE, scale)
            )
        }),

        setTabletopYaw: (deg) => set({ tabletopYawDeg: deg }),

        setTabletopCenter: (enu) => set({ tabletopCenterEnu: enu }),

        resetTabletop: () => set({
            tabletopScale: VR_CONFIG.TABLETOP.DEFAULT_SCALE,
            tabletopYawDeg: 0,
            tabletopCenterEnu: [0, 0, 0],
        }),

        toggleLayer: (layer) => set((state) => {
            switch (layer) {
                case 'rays': return { showRays: !state.showRays };
                case 'voxels': return { showVoxels: !state.showVoxels };
                case 'trails': return { showTrails: !state.showTrails };
                case 'compass': return { showCompass: !state.showCompass };
                case 'nodes': return { showNodeMarkers: !state.showNodeMarkers };
                case 'labels': return { showLabels: !state.showLabels };
                default: return {};
            }
        }),

        toggleHud: () => set((state) => ({ hudVisible: !state.hudVisible })),

        selectTrack: (id) => set({ selectedTrackId: id }),
    }));
}

export type VRStore = ReturnType<typeof createVRStore>;
