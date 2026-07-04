import { create } from 'zustand';
import { Track, Ray, Voxel, NodeHealth, SystemStatus, TrackState, ClusterInfo, Vector3 } from './types';

// How many recent positions to retain per track for the motion-trail overlay.
// ~60 frames ≈ 2 s of history at 30 Hz; bounded so memory can't grow forever.
export const MAX_TRAIL_POINTS = 60;

interface AppState {
    // Data State
    tracks: Record<string, Track>;
    trails: Record<string, Vector3[]>; // bounded position history per track
    rays: Ray[];
    voxels: Voxel[]; // Sparse array of active voxels
    nodes: Record<string, NodeHealth>;
    system: SystemStatus;
    // Per-node self-calibration status (uncalibrated/converging/converged/diverged),
    // pushed by the backend inside SYSTEM_STATUS (P1.5). Surfaced in the sensor list.
    calibration: Record<string, string>;

    // Cluster / domain state (P3.5)
    clusters: Record<string, ClusterInfo>;
    activeClusterId: string | null;
    pendingNodeIds: string[];

    // UI State
    selectedTrackId: string | null;
    selectedNodeId: string | null;
    is3DMode: boolean; // default true
    showRays: boolean; // default true
    showVoxels: boolean; // default true
    showHistory: boolean; // motion trails
    // One-shot camera focus request, consumed by the Map. `seq` increments on
    // every request so focusing the same target twice still re-triggers the
    // camera effect (a plain position object would compare equal-by-value).
    focusRequest: { latitude: number; longitude: number; seq: number } | null;

    // Actions
    setTracks: (tracks: Track[]) => void;
    setRays: (rays: Ray[]) => void;
    setVoxels: (voxels: Voxel[]) => void;
    updateNode: (node: NodeHealth) => void;
    updateSystemStatus: (status: SystemStatus) => void;
    setCalibration: (calibration: Record<string, string>) => void;

    setClusters: (clusters: Record<string, ClusterInfo>) => void;
    setActiveCluster: (id: string | null) => void;
    setPendingNodes: (ids: string[]) => void;

    selectTrack: (id: string | null) => void;
    selectNode: (id: string | null) => void;
    toggleLayer: (layer: 'rays' | 'voxels' | 'history') => void;
    toggle3D: () => void;
    requestFocus: (latitude: number, longitude: number) => void;
    reset: () => void;
}

const DEFAULT_SYSTEM_STATUS: SystemStatus = {
    server_fps: 0,
    total_tracks: 0,
    total_voxels: 0,
    uptime_seconds: 0,
    cpu_percent: 0,
    memory_percent: 0,
};

export const useAppStore = create<AppState>((set) => ({
    // Initial State
    tracks: {},
    trails: {},
    rays: [],
    voxels: [],
    nodes: {},
    system: DEFAULT_SYSTEM_STATUS,
    calibration: {},

    clusters: {},
    activeClusterId: null,
    pendingNodeIds: [],

    selectedTrackId: null,
    selectedNodeId: null,
    is3DMode: true,
    showRays: true,
    showVoxels: true,
    showHistory: true,
    focusRequest: null,

    // Actions
    setTracks: (newTracks) => set((state) => {
        // Full-replace: the backend sends the complete current track list for the
        // subscribed cluster every frame, so rebuild the map from scratch. Merging
        // into the previous map left "zombie" tracks on screen forever, because a
        // track that disappears server-side is simply absent from later updates
        // (no per-track DELETED event is emitted).
        const tracks: Record<string, Track> = {};
        // Motion trails: append each live track's current position to a bounded
        // ring buffer, and drop the trail of any track that has disappeared so
        // trails can't accumulate for dead tracks (mirrors the zombie-track fix).
        const trails: Record<string, Vector3[]> = {};
        newTracks.forEach(t => {
            if (t.state === TrackState.DELETED) return;
            const key = t.track_id.toString();
            tracks[t.track_id] = t;
            const prev = state.trails[key] || [];
            const next = prev.length >= MAX_TRAIL_POINTS
                ? [...prev.slice(prev.length - MAX_TRAIL_POINTS + 1), t.position]
                : [...prev, t.position];
            trails[key] = next;
        });
        return { tracks, trails };
    }),

    setRays: (rays) => set({ rays }),

    setVoxels: (voxels) => set({ voxels }),

    updateNode: (node) => set((state) => ({
        nodes: { ...state.nodes, [node.node_id]: node }
    })),

    updateSystemStatus: (status) => set({ system: status }),

    setCalibration: (calibration) => set({ calibration }),

    setClusters: (clusters) => set((state) => {
        // Auto-select the first cluster as the active domain if none is chosen yet.
        const ids = Object.keys(clusters);
        const activeClusterId = state.activeClusterId ?? (ids.length > 0 ? ids[0] : null);
        return { clusters, activeClusterId };
    }),

    setActiveCluster: (id) => set({ activeClusterId: id }),

    setPendingNodes: (ids) => set({ pendingNodeIds: ids }),

    selectTrack: (id) => set({ selectedTrackId: id }),

    selectNode: (id) => set({ selectedNodeId: id }),

    toggleLayer: (layer) => set((state) => {
        switch (layer) {
            case 'rays': return { showRays: !state.showRays };
            case 'voxels': return { showVoxels: !state.showVoxels };
            case 'history': return { showHistory: !state.showHistory };
            default: return {};
        }
    }),

    toggle3D: () => set((state) => ({ is3DMode: !state.is3DMode })),

    requestFocus: (latitude, longitude) => set((state) => ({
        focusRequest: { latitude, longitude, seq: (state.focusRequest?.seq ?? 0) + 1 }
    })),

    reset: () => set({
        tracks: {},
        trails: {},
        rays: [],
        voxels: [],
        nodes: {},
        system: DEFAULT_SYSTEM_STATUS,
        calibration: {},
        clusters: {},
        activeClusterId: null,
        pendingNodeIds: []
    })
}));
