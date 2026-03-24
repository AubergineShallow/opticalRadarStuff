import React, { useState } from 'react';
import { useAppStore } from '../store';
import { SystemHealth } from './hud/SystemHealth';
import { TargetList } from './hud/TargetList';
import { SensorList } from './hud/SensorList';

export default function HUD() {
    const { system, tracks, nodes, selectTrack, selectedTrackId } = useAppStore();
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

    return (
        <div className="w-full h-full relative p-4 pointer-events-none">
            <div className="absolute top-4 right-4 flex flex-col items-end gap-2 pointer-events-auto">
                <SystemHealth status={system} />
            </div>
            <div className="absolute top-4 left-4 flex flex-col gap-4 pointer-events-auto">
                <TargetList
                    tracks={tracks}
                    selectedTrackId={selectedTrackId}
                    onSelectTrack={selectTrack}
                />
                <SensorList
                    nodes={nodes || {}}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={setSelectedNodeId}
                />
            </div>
        </div>
    );
}
