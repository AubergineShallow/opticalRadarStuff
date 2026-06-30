import React, { useState } from 'react';
import { Camera, ChevronUp, ChevronDown, PlusCircle } from 'lucide-react';
import { NodeHealth } from '../../types';
import { useAppStore } from '../../store';

interface SensorListProps {
    nodes: Record<string, NodeHealth>;
    onSelectNode?: (id: string) => void;
    selectedNodeId?: string | null;
    onAssignNode?: (id: string) => void;
}

export function SensorList({ nodes, onSelectNode, selectedNodeId, onAssignNode }: SensorListProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const nodeList = Object.values(nodes);

    // Pending / unassigned nodes come from the store (P3.6).
    const pendingNodeIds = useAppStore(s => s.pendingNodeIds);
    const activeClusterId = useAppStore(s => s.activeClusterId);

    return (
        <div className="bg-black/80 border border-cyan-500/30 p-2 rounded w-96 backdrop-blur pointer-events-auto flex flex-col gap-2 shadow-[0_0_15px_rgba(0,255,255,0.1)] transition-all duration-200">
            <div className={`flex items-center justify-between px-2 ${isMinimized ? '' : 'border-b border-cyan-500/20 pb-2'}`}>
                <div className="flex items-center gap-2 text-cyan-400 font-bold">
                    <Camera className="w-4 h-4" /> <span>SENSORS ({nodeList.length})</span>
                </div>
                <button
                    onClick={() => setIsMinimized(!isMinimized)}
                    className="text-cyan-500/70 hover:text-cyan-400 transition-colors p-1 hover:bg-cyan-500/10 rounded"
                >
                    {isMinimized ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                </button>
            </div>

            {!isMinimized && (
                <>
                    {/* Pending / unassigned nodes — assign them to the active domain (P3.6) */}
                    {pendingNodeIds.length > 0 && (
                        <div className="border border-amber-500/30 rounded bg-amber-500/5 p-2 flex flex-col gap-1">
                            <div className="text-[10px] font-mono text-amber-400 uppercase tracking-wider">
                                Pending ({pendingNodeIds.length})
                            </div>
                            {pendingNodeIds.map(nodeId => (
                                <div key={nodeId} className="flex items-center justify-between text-xs font-mono text-gray-300">
                                    <span>{nodeId.replace('NODE-', '')}</span>
                                    <button
                                        className="flex items-center gap-1 text-[10px] text-amber-400 border border-amber-500/40 rounded px-2 py-0.5 hover:bg-amber-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
                                        disabled={!onAssignNode || !activeClusterId}
                                        title={activeClusterId ? `Assign to ${activeClusterId}` : 'Select a domain first'}
                                        onClick={() => onAssignNode?.(nodeId)}
                                    >
                                        <PlusCircle className="w-3 h-3" /> Assign
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="max-h-64 overflow-y-auto">
                        <table className="w-full text-xs text-left border-collapse">
                            <thead className="bg-white/5 text-gray-400 sticky top-0 backdrop-blur-md">
                                <tr>
                                    <th className="p-2 font-mono font-normal">ID</th>
                                    <th className="p-2 font-mono font-normal text-right">POS (LLA)</th>
                                    <th className="p-2 font-mono font-normal text-right">ORIENT</th>
                                    <th className="p-2 font-mono font-normal text-right">FOV</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {nodeList.length === 0 ? (
                                    <tr>
                                        <td colSpan={4} className="p-8 text-center text-gray-600 italic">No Active Sensors</td>
                                    </tr>
                                ) : (
                                    nodeList.map(node => {
                                        const isSelected = selectedNodeId === node.node_id;
                                        const pU = (node.location || [0, 0, 0])[2];

                                        // display_lat/lon precomputed at receipt (P3.2);
                                        // sensor_config now typed (no `as any` cast — P3.1).
                                        const config = node.sensor_config;

                                        return (
                                            <tr
                                                key={node.node_id}
                                                className={`
                                                    cursor-pointer transition-colors font-mono group
                                                    ${isSelected ? 'bg-cyan-500/20' : 'hover:bg-white/10'}
                                                `}
                                                onClick={() => onSelectNode?.(node.node_id)}
                                            >
                                                <td className="p-2 text-cyan-400 font-bold group-hover:text-cyan-300">
                                                    {node.node_id.replace('NODE-', '')}
                                                </td>
                                                <td className="p-2 text-right text-gray-300">
                                                    <div className="flex flex-col text-[10px] leading-tight">
                                                        <span>{node.display_lat?.toFixed(4) ?? '—'}</span>
                                                        <span>{node.display_lon?.toFixed(4) ?? '—'}</span>
                                                        <span className="text-[9px] text-gray-500">ALT: {pU.toFixed(0)}m</span>
                                                    </div>
                                                </td>
                                                <td className="p-2 text-right text-white">
                                                    <div className="flex flex-col text-[10px]">
                                                        <span>AZ: {config?.azimuth_deg ?? '—'}°</span>
                                                        <span>EL: {config?.elevation_deg ?? '—'}°</span>
                                                    </div>
                                                </td>
                                                <td className="p-2 text-right text-gray-400">
                                                    <div className="flex flex-col text-[10px]">
                                                        <span>H: {config?.hfov_deg ?? '—'}°</span>
                                                        <span>V: {config?.vfov_deg ?? '—'}°</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })
                                )}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    );
}
