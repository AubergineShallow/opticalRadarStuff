
import React, { useState } from 'react';
import { ClusterInfo } from '../../types';
import { useAppStore } from '../../store';

interface TopBarProps {
    time: string;
    clusters?: Record<string, ClusterInfo>;
    activeClusterId?: string | null;
    sendCommand?: (cmd: string, data?: any) => void;
}

export function TopBar({ time, clusters = {}, activeClusterId, sendCommand }: TopBarProps) {
    const [newClusterName, setNewClusterName] = useState('');
    const [isCreating, setIsCreating] = useState(false);
    const setActiveCluster = useAppStore(s => s.setActiveCluster);

    const handleCreateCluster = () => {
        if (newClusterName.trim() && sendCommand) {
            sendCommand('CREATE_CLUSTER', { cluster_id: newClusterName.trim() });
            setNewClusterName('');
            setIsCreating(false);
        }
    };

    return (
        <div className="flex justify-between items-start pointer-events-auto w-full">
            <div className="bg-black/60 border-l-4 border-green-500 p-3 pr-6 rounded-r backdrop-blur flex items-center gap-6">
                <div>
                    <h1 className="text-xl font-bold text-green-500 tracking-widest">OPTICA_RADAR // CIC</h1>
                    <div className="text-xs text-green-500/60 font-mono mt-1 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                        STATUS: ACTIVE MONITORING
                    </div>
                </div>

                <div className="border-l border-green-500/30 pl-6 flex items-center gap-4">
                    <span className="text-sm font-mono text-gray-400">DOMAIN:</span>
                    <select
                        className="bg-black/80 text-green-400 border border-green-500/50 rounded px-3 py-1 font-mono text-sm outline-none focus:border-green-400"
                        value={activeClusterId || ''}
                        onChange={(e) => {
                            // Update the active domain; the WebSocket hook subscribes
                            // to the matching room when activeClusterId changes (P3.5).
                            setActiveCluster(e.target.value || null);
                        }}
                    >
                        <option value="" disabled>Select Domain</option>
                        {Object.keys(clusters || {}).map(id => (
                            <option key={id} value={id}>{id}</option>
                        ))}
                    </select>

                    {isCreating ? (
                        <div className="flex items-center gap-2">
                            <input
                                type="text"
                                className="bg-black/80 text-white border border-green-500/50 rounded px-2 py-1 font-mono text-sm w-32 outline-none focus:border-green-400"
                                placeholder="Cluster ID"
                                value={newClusterName}
                                onChange={(e) => setNewClusterName(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleCreateCluster()}
                            />
                            <button
                                className="text-xs font-mono bg-green-500/20 text-green-400 px-2 py-1 rounded hover:bg-green-500/40"
                                onClick={handleCreateCluster}
                            >
                                ADD
                            </button>
                            <button
                                className="text-xs font-mono text-gray-400 hover:text-white"
                                onClick={() => setIsCreating(false)}
                            >
                                X
                            </button>
                        </div>
                    ) : (
                        <button
                            className="text-xs font-mono border border-green-500/30 text-green-400/80 px-2 py-1 rounded hover:bg-green-500/20 hover:text-green-400 transition-colors"
                            onClick={() => setIsCreating(true)}
                        >
                            + NEW
                        </button>
                    )}
                </div>
            </div>

            <div className="bg-black/60 p-3 pl-6 rounded-l backdrop-blur text-right border-r-4 border-green-500/50">
                <div className="text-2xl font-bold font-mono text-white">{time}</div>
                <div className="text-xs text-gray-400 font-mono tracking-wider">ZULU / UTC</div>
            </div>
        </div>
    );
}
