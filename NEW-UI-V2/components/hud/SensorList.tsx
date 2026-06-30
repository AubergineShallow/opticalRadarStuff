import React, { useState } from 'react';
import { Camera, ChevronUp, ChevronDown } from 'lucide-react';
import { NodeHealth } from '../../types';
import { UI_CONFIG } from '../../constants';

interface SensorListProps {
    nodes: Record<string, NodeHealth>;
    onSelectNode?: (id: string) => void;
    selectedNodeId?: string | null;
}

export function SensorList({ nodes, onSelectNode, selectedNodeId }: SensorListProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const nodeList = Object.values(nodes);

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
                                    const [pE, pN, pU] = node.location || [0, 0, 0]; // Fallback if undefined

                                    const { sensor_config, display_lat, display_lon } = node;
                                    const config = sensor_config || {};

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
                                                    <span>{display_lat?.toFixed(4) ?? '—'}</span>
                                                    <span>{display_lon?.toFixed(4) ?? '—'}</span>
                                                    <span className="text-[9px] text-gray-500">ALT: {pU.toFixed(0)}m</span>
                                                </div>
                                            </td>
                                            <td className="p-2 text-right text-white">
                                                <div className="flex flex-col text-[10px]">
                                                    <span>AZ: {config.azimuth_deg ?? '-'}°</span>
                                                    <span>EL: {config.elevation_deg ?? '-'}°</span>
                                                </div>
                                            </td>
                                            <td className="p-2 text-right text-gray-400">
                                                <div className="flex flex-col text-[10px]">
                                                    <span>H: {config.hfov_deg ?? '-'}°</span>
                                                    <span>V: {config.vfov_deg ?? '-'}°</span>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
