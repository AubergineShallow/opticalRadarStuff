import React, { useState } from 'react';
import { useAppStore } from '../store';
import { SystemHealth } from './hud/SystemHealth';
import { TargetList } from './hud/TargetList';
import { SensorList } from './hud/SensorList';

export default function HUD() {
    // Note: 'nodes' was checked in store definitions and seems to exist, 
    // but just in case, we'll verify store.ts if needed.
    // Based on previous hooks.ts, useAppStore extracts { updateNode, setRays, etc }.
    // We assume 'nodes' (the dictionary of NodeHealth) is exposed in the store state.
    const { updateSystemStatus, setTracks, selectTrack, selectedTrackId, system, tracks, nodes } = useAppStore();

    // Local state for UI selections
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

    return (
        <div className="w-full h-full relative p-4 pointer-events-none">

            {/* Top Right: System Health */}
            <div className="absolute top-4 right-4 flex flex-col items-end gap-2 pointer-events-auto">
                {/* Use 'system' here as observed in the file view, assuming it matches SystemStatus type */}
                <SystemHealth status={system} />
            </div>

            {/* Top Left: Lists (Targets & Sensors) */}
            <div className="absolute top-4 left-4 flex flex-col gap-4 pointer-events-auto">
                <TargetList
                    tracks={tracks}
                    selectedTrackId={selectedTrackId}
                    onSelectTrack={selectTrack}
                />

                <SensorList
                    nodes={nodes || {}} // Handle case where nodes might be undefined initially
                    selectedNodeId={selectedNodeId}
                    onSelectNode={setSelectedNodeId}
                />
            </div>
        </div>
    );
}