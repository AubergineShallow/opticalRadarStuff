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
        let changed = false;
        const nextTracks = { ...state.tracks };

        for (const t of newTracks) {
            if (t.state === TrackState.DELETED) {
                if (nextTracks[t.track_id]) {
                    delete nextTracks[t.track_id];
                    changed = true;
                }
            } else {
                const prev = nextTracks[t.track_id];

                // Skip update if position and state haven't changed to avoid unnecessary re-renders
                if (prev &&
                    prev.position[0] === t.position[0] &&
                    prev.position[1] === t.position[1] &&
                    prev.state === t.state) {
                    continue;
                }

                const history = prev?.history ? [...prev.history] : [];
                if (prev) {
                    history.push(prev.position);
                    if (history.length > 30) history.shift(); // Max 30 points
                }

                nextTracks[t.track_id] = { ...t, history };
                changed = true;
            }
        }

        return changed ? { tracks: nextTracks } : state;
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