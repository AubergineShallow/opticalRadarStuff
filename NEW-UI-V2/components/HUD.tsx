

import React, { useState, useEffect } from 'react';
import { useAppStore } from '../store';
import { SystemHealth } from './hud/SystemHealth';
import { TargetList } from './hud/TargetList';
import { SensorList } from './hud/SensorList';
import { TopBar } from './hud/TopBar';

export default function HUD({ sendCommand }: { sendCommand?: (cmd: string, data?: any) => void }) {
    const { updateSystemStatus, setTracks, selectTrack, selectedTrackId, system, tracks, nodes, clusters, activeClusterId } = useAppStore();

    // Local state for UI selections
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [time, setTime] = useState<string>('00:00:00');

    useEffect(() => {
        const timer = setInterval(() => {
            const now = new Date();
            setTime(now.toISOString().substring(11, 19));
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    return (
        <div className="w-full h-full relative p-4 pointer-events-none flex flex-col">

            {/* Top Bar with Domain Selector */}
            <div className="w-full pointer-events-auto z-50">
                <TopBar
                    time={time}
                    clusters={clusters}
                    activeClusterId={activeClusterId}
                    sendCommand={sendCommand}
                />
            </div>

            <div className="flex-1 relative w-full mt-4">
                {/* Top Right: System Health */}
                <div className="absolute top-0 right-0 flex flex-col items-end gap-2 pointer-events-auto">
                    <SystemHealth status={system} />
                </div>

                {/* Top Left: Lists (Targets & Sensors) */}
                <div className="absolute top-0 left-0 flex flex-col gap-4 pointer-events-auto">
                    <TargetList
                        tracks={tracks}
                        selectedTrackId={selectedTrackId}
                        onSelectTrack={selectTrack}
                    />

                    <SensorList
                        nodes={nodes || {}}
                        selectedNodeId={selectedNodeId}
                        onSelectNode={setSelectedNodeId}
                        onAssignNode={(nodeId) => {
                            if (sendCommand && activeClusterId) {
                                sendCommand('ASSIGN_NODE', {
                                    node_id: nodeId,
                                    cluster_id: activeClusterId
                                });
                            }
                        }}
                    />
                </div>
            </div>
        </div>
    );
}
