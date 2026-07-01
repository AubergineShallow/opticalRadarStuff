
import { create } from 'zustand';
import { Track, Ray, Voxel, NodeHealth, SystemStatus, TrackState, ClusterInfo } from './types';

interface AppState {
    // Data State
    tracks: Record<string, Track>;
    rays: Ray[];
    voxels: Voxel[]; // Sparse array of active voxels
    nodes: Record<string, NodeHealth>;
    system: SystemStatus;

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
    showHistory: boolean;

    // Actions
    setTracks: (tracks: Track[]) => void;
    setRays: (rays: Ray[]) => void;
    setVoxels: (voxels: Voxel[]) => void;
    updateNode: (node: NodeHealth) => void;
    updateSystemStatus: (status: SystemStatus) => void;

    setClusters: (clusters: Record<string, ClusterInfo>) => void;
    setActiveCluster: (id: string | null) => void;
    setPendingNodes: (ids: string[]) => void;

    selectTrack: (id: string | null) => void;
    selectNode: (id: string | null) => void;
    toggleLayer: (layer: 'rays' | 'voxels' | 'history') => void;
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
    rays: [],
    voxels: [],
    nodes: {},
    system: DEFAULT_SYSTEM_STATUS,

    clusters: {},
    activeClusterId: null,
    pendingNodeIds: [],

    selectedTrackId: null,
    selectedNodeId: null,
    is3DMode: true,
    showRays: true,
    showVoxels: true,
    showHistory: true,

    // Actions
    setTracks: (newTracks) => set(() => {
        // Full-replace: the backend sends the complete current track list for the
        // subscribed cluster every frame, so rebuild the map from scratch. Merging
        // into the previous map left "zombie" tracks on screen forever, because a
        // track that disappears server-side is simply absent from later updates
        // (no per-track DELETED event is emitted).
        const tracks: Record<string, Track> = {};
        newTracks.forEach(t => {
            if (t.state === TrackState.DELETED) return;
            tracks[t.track_id] = t;
        });
        return { tracks };
    }),

    setRays: (rays) => set({ rays }),

    setVoxels: (voxels) => set({ voxels }),

    updateNode: (node) => set((state) => ({
        nodes: { ...state.nodes, [node.node_id]: node }
    })),

    updateSystemStatus: (status) => set({ system: status }),

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

    reset: () => set({
        tracks: {},
        rays: [],
        voxels: [],
        nodes: {},
        system: DEFAULT_SYSTEM_STATUS,
        clusters: {},
        activeClusterId: null,
        pendingNodeIds: []
    })
}));
