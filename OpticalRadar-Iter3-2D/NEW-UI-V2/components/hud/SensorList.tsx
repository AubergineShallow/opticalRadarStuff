import React, { useState } from 'react';
import { NodeHealthRecord } from '../../../store/types';

interface SensorListProps {
    nodes: Record<string, NodeHealthRecord>;
    selectedNodeId: string | null;
    onSelectNode: (id: string | null) => void;
}

export const SensorList: React.FC<SensorListProps> = ({ nodes, selectedNodeId, onSelectNode }) => {
    // Track in-flight requests to show loading/locked state
    const [pendingNodeId, setPendingNodeId] = useState<string | null>(null);

    const handleToggleMode = async (nodeId: string, ipAddress: string, e: React.MouseEvent) => {
        e.stopPropagation(); // prevent row selection
        
        if (!ipAddress || ipAddress === "unknown" || ipAddress === "") {
            console.error("Unknown IP address for node", nodeId);
            return;
        }

        const node = nodes[nodeId];
        const currentMode = node.mode === 1 ? 'stream' : 'tracking';
        const newMode = currentMode === 'tracking' ? 'stream' : 'tracking';
        
        setPendingNodeId(nodeId);

        try {
            const response = await fetch(`http://${ipAddress}:8000/set_mode?mode=${newMode}`);
            if (!response.ok) {
                console.error("Failed to toggle mode:", response.statusText);
            }
        } catch (error) {
            console.error("Error toggling mode:", error);
        } finally {
            // We stay locked for 1.5 seconds to allow for heartbeat sync
            setTimeout(() => setPendingNodeId(null), 1500);
        }
    };

    return (
        <div className="w-80 bg-slate-900/80 backdrop-blur-md rounded-xl border border-cyan-500/30 overflow-hidden flex flex-col pointer-events-auto shadow-[0_0_15px_rgba(6,182,212,0.15)]">
            <div className="bg-slate-800/80 px-4 py-3 border-b border-cyan-500/30 flex justify-between items-center">
                <h2 className="text-cyan-400 font-bold tracking-widest text-sm flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
                    SENSORS ({Object.keys(nodes).length})
                </h2>
                <button
                    className="text-slate-400 hover:text-cyan-400 transition-colors"
                    onClick={() => onSelectNode(null)}
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="square" strokeLinejoin="miter" strokeWidth={2} d="M5 15l7-7 7 7" />
                    </svg>
                </button>
            </div>

            <div className="max-h-64 overflow-y-auto custom-scrollbar p-2">
                {Object.keys(nodes).length === 0 ? (
                    <div className="text-slate-500 text-xs italic text-center py-4">No Active Sensors</div>
                ) : (
                    <table className="w-full text-xs text-left">
                        <thead className="text-cyan-500/70 uppercase">
                            <tr>
                                <th className="px-2 pb-2">ID</th>
                                <th className="px-2 pb-2 text-right">POS (ENU)</th>
                                <th className="px-2 pb-2 text-right">MODE</th>
                            </tr>
                        </thead>
                        <tbody>
                            {Object.values(nodes).map((node) => {
                                const isSelected = selectedNodeId === node.node_id;
                                const isHealthy = node.status === 0;
                                
                                // Source of truth is now the health record itself
                                const isPending = pendingNodeId === node.node_id;
                                const currentModeNum = node.mode;
                                const currentMode = currentModeNum === 1 ? 'stream' : 'tracking';
                                
                                // Fake coordinates for now since we don't track camera position visually yet
                                const posX = 0.0;
                                const posY = 0.0;

                                return (
                                    <React.Fragment key={node.node_id}>
                                        <tr
                                            onClick={() => onSelectNode(isSelected ? null : node.node_id)}
                                            className={`
                                            cursor-pointer transition-colors border-b border-slate-700/50 last:border-0
                                            ${isSelected ? 'bg-cyan-500/20' : 'hover:bg-slate-800/50'}
                                        `}
                                        >
                                            <td className="px-2 py-3 font-mono">
                                                <div className="flex items-center gap-2">
                                                    <div className={`w-1.5 h-1.5 rounded-full ${isHealthy ? 'bg-green-500' : 'bg-red-500'}`} />
                                                    <span className={isHealthy ? 'text-cyan-300' : 'text-slate-400'}>{node.node_id}</span>
                                                </div>
                                            </td>
                                            <td className="px-2 py-3 text-right font-mono text-slate-300">
                                                <span className="text-[10px]">{posX.toFixed(1)}, {posY.toFixed(1)}</span>
                                            </td>
                                            <td className="px-2 py-3 text-right font-mono">
                                                <button 
                                                    onClick={(e) => handleToggleMode(node.node_id, node.ip_address, e)}
                                                    disabled={isPending || !node.ip_address || node.ip_address === "unknown"}
                                                    className={`px-2 py-1 rounded text-[10px] font-bold uppercase transition-colors ${
                                                        !node.ip_address || node.ip_address === "unknown" 
                                                            ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                                                            : isPending
                                                                ? 'bg-slate-600/50 text-slate-400 border border-slate-500/50 animate-pulse cursor-wait'
                                                                : currentMode === 'stream' 
                                                                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/50 hover:bg-amber-500/30'
                                                                    : 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/50 hover:bg-indigo-500/30'
                                                    }`}
                                                >
                                                    {isPending ? 'Sync...' : (currentMode === 'stream' ? 'Stream' : 'Track')}
                                                </button>
                                            </td>
                                        </tr>
                                        
                                        {/* Camera Stream Expansion Panel */}
                                        {currentMode === 'stream' && (
                                            <tr>
                                                <td colSpan={3} className="px-2 py-2">
                                                    <div className="w-full h-32 bg-black border border-amber-500/30 rounded overflow-hidden relative group">
                                                        <div className="absolute top-1 left-2 z-10 text-[9px] font-mono text-amber-500 bg-black/60 px-1 rounded">LIVE FEED</div>
                                                        <img 
                                                            src={`http://${node.ip_address}:8000/`} 
                                                            alt={`${node.node_id} live stream`}
                                                            className="w-full h-full object-cover"
                                                            onError={(e) => {
                                                                e.currentTarget.style.display = 'none';
                                                                e.currentTarget.parentElement?.classList.add('flex', 'items-center', 'justify-center');
                                                                e.currentTarget.parentElement!.innerHTML = '<span class="text-xs text-slate-500">Stream Unavailable</span>';
                                                            }}
                                                        />
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                        
                                        {/* Original Node ID Details Expansion Panel */}
                                        {isSelected && currentMode !== 'stream' && (
                                            <tr>
                                                <td colSpan={3} className="px-4 pb-3 pt-1 text-[10px] text-slate-400 font-mono bg-black/20">
                                                    <div className="flex justify-between border-t border-slate-700/50 pt-2">
                                                        <div>
                                                            <div>AZ: <span className="text-cyan-300">0.0°</span></div>
                                                            <div>EL: <span className="text-cyan-300">0.0°</span></div>
                                                        </div>
                                                        <div className="text-right">
                                                            <div>FOV: <span className="text-cyan-300">{(node.config as any)?.fov?.toFixed(1) || '62.2'}°</span></div>
                                                            <div>FPS: <span className="text-cyan-300">{node.fps?.toFixed(1) || '0.0'}</span></div>
                                                        </div>
                                                    </div>
                                                    <div className="mt-2 text-right">
                                                        IP: <span className="text-slate-300">{node.ip_address || 'unknown'}</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
};
