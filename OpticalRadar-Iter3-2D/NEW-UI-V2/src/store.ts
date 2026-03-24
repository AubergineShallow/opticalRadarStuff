import { create } from 'zustand';
import { Track, Ray, Voxel, NodeHealth, SystemStatus, TrackState } from './types';

interface AppState {
    // Data State
    tracks: Record<string, Track>;
    rays: Ray[];
    voxels: Voxel[]; // Sparse array of active voxels
    nodes: Record<string, NodeHealth>;
    system: SystemStatus;

    // UI State
    selectedTrackId: string | null;
    selectedNodeId: string | null;

    showRays: boolean; // default true
    showVoxels: boolean; // default true
    showHistory: boolean;

    // Actions
    setTracks: (tracks: Track[]) => void;
    setRays: (rays: Ray[]) => void;
    setVoxels: (voxels: Voxel[]) => void;
    updateNode: (node: NodeHealth) => void;
    updateSystemStatus: (status: SystemStatus) => void;

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

    selectedTrackId: null,
    selectedNodeId: null,

    showRays: true,
    showVoxels: true,
    showHistory: true,

    // Actions
    setTracks: (newTracks) => set((state) => {
        const tracks = { ...state.tracks };
        newTracks.forEach(t => {
            if (t.state === TrackState.DELETED) {
                delete tracks[t.track_id];
            } else {
                const prev = tracks[t.track_id];
                const history = prev?.history || [];
                // Only push if position changed significantly to avoid crowding, or just push.
                if (prev) {
                    history.push(prev.position);
                    if (history.length > 30) history.shift(); // Max 30 points
                }
                tracks[t.track_id] = { ...t, history };
            }
        });
        return { tracks };
    }),

    setRays: (rays) => set({ rays }),

    setVoxels: (voxels) => set({ voxels }),

    updateNode: (node) => set((state) => ({
        nodes: { ...state.nodes, [node.node_id]: node }
    })),

    updateSystemStatus: (status) => set({ system: status }),

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
        system: DEFAULT_SYSTEM_STATUS
    })
}));
