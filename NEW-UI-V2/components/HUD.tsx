import React, { useEffect, useState } from 'react';
import { useAppStore } from '../store';
import { SystemHealth } from './hud/SystemHealth';
import { TargetList } from './hud/TargetList';
import { SensorList } from './hud/SensorList';
import { TopBar } from './hud/TopBar';
import { LayerControls } from './hud/LayerControls';
import { TrackDetail } from './hud/TrackDetail';
import { NodeDetail } from './hud/NodeDetail';

export default function HUD({ sendCommand }: { sendCommand?: (cmd: string, data?: any) => void }) {
    const {
        selectTrack, selectedTrackId,
        selectNode, selectedNodeId,
        system, tracks, nodes, clusters, activeClusterId,
        toggleLayer, toggle3D,
    } = useAppStore();

    const [time, setTime] = useState<string>('00:00:00');

    useEffect(() => {
        const timer = setInterval(() => {
            const now = new Date();
            setTime(now.toISOString().substring(11, 19));
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    // Keyboard shortcuts for the layer/view toggles. Ignored while typing into a
    // form field (e.g. the New-Domain input) so text entry isn't hijacked.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            const el = e.target as HTMLElement | null;
            const tag = el?.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
            switch (e.key.toLowerCase()) {
                case 'r': toggleLayer('rays'); break;
                case 'v': toggleLayer('voxels'); break;
                case 't': toggleLayer('history'); break;
                case 'p': toggle3D(); break;
                case 'c': {
                    // Center the camera on the current selection (track wins if
                    // both are selected). State is read fresh from the store so
                    // this effect doesn't re-register on every data frame.
                    const s = useAppStore.getState();
                    const track = s.selectedTrackId ? s.tracks[s.selectedTrackId] : undefined;
                    if (track?.display) {
                        s.requestFocus(track.display.lat, track.display.lon);
                        break;
                    }
                    const node = s.selectedNodeId ? s.nodes[s.selectedNodeId] : undefined;
                    if (node?.display_lat !== undefined && node?.display_lon !== undefined) {
                        s.requestFocus(node.display_lat, node.display_lon);
                    }
                    break;
                }
                case 'escape': selectTrack(null); selectNode(null); break;
                default: return;
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [toggleLayer, toggle3D, selectTrack, selectNode]);

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
                        onSelectNode={selectNode}
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

                {/* Bottom Left: selected-track/node detail + layer controls */}
                <div className="absolute bottom-0 left-0 flex flex-col gap-3 pointer-events-none">
                    <TrackDetail />
                    <NodeDetail />
                    <LayerControls />
                </div>
            </div>
        </div>
    );
}
