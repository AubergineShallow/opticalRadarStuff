import React from 'react';
import { Camera, X, Cpu, Thermometer, Gauge, Wifi, Clock, Locate } from 'lucide-react';
import { useAppStore } from '../../store';
import { NodeHealthStatus } from '../../types';

const STATUS_LABEL: Record<number, string> = {
    [NodeHealthStatus.HEALTHY]: 'HEALTHY',
    [NodeHealthStatus.DEGRADED]: 'DEGRADED',
    [NodeHealthStatus.FAILING]: 'FAILING',
    [NodeHealthStatus.OFFLINE]: 'OFFLINE',
};

const STATUS_COLOR: Record<number, string> = {
    [NodeHealthStatus.HEALTHY]: 'text-green-400',
    [NodeHealthStatus.DEGRADED]: 'text-yellow-400',
    [NodeHealthStatus.FAILING]: 'text-orange-400',
    [NodeHealthStatus.OFFLINE]: 'text-red-400',
};

const CALIB_COLOR: Record<string, string> = {
    converged: 'text-green-400',
    converging: 'text-yellow-400',
    diverged: 'text-red-400',
    uncalibrated: 'text-gray-500',
};

function Stat({ icon, label, value, unit, valueClass }: {
    icon: React.ReactNode; label: string; value: string; unit?: string; valueClass?: string;
}) {
    return (
        <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-gray-400 text-[11px]">{icon}{label}</span>
            <span className={`font-mono text-xs ${valueClass ?? 'text-gray-100'}`}>
                {value}{unit && <span className="text-gray-500 text-[9px] ml-0.5">{unit}</span>}
            </span>
        </div>
    );
}

/** Compact "3s ago / 2m ago" formatter for the last-seen age. */
function formatAge(ageSec: number): string {
    if (ageSec < 0) return 'now';
    if (ageSec < 60) return `${ageSec.toFixed(0)}s ago`;
    if (ageSec < 3600) return `${(ageSec / 60).toFixed(0)}m ago`;
    return `${(ageSec / 3600).toFixed(1)}h ago`;
}

/**
 * Detail card for the currently-selected sensor node. The backend has always
 * sent fps/cpu/temp/ip in NODE_UPDATE, but the sensor list only had room for
 * position/status/calibration — this surfaces the rest, mirroring TrackDetail.
 */
export function NodeDetail() {
    const selectedNodeId = useAppStore(s => s.selectedNodeId);
    const nodes = useAppStore(s => s.nodes);
    const calibration = useAppStore(s => s.calibration);
    const selectNode = useAppStore(s => s.selectNode);
    const requestFocus = useAppStore(s => s.requestFocus);

    if (!selectedNodeId) return null;
    const node = nodes[selectedNodeId];
    if (!node) return null;

    const statusLabel = STATUS_LABEL[node.status] ?? 'UNKNOWN';
    const statusColor = STATUS_COLOR[node.status] ?? 'text-gray-400';
    const calib = calibration[node.node_id];
    const ageSec = node.last_seen > 0 ? Date.now() / 1000 - node.last_seen : NaN;
    const stale = !Number.isNaN(ageSec) && ageSec > 10;
    const [pE, pN, pU] = node.location || [0, 0, 0];

    return (
        <div className="bg-black/85 border border-cyan-500/40 p-3 rounded w-72 backdrop-blur pointer-events-auto shadow-[0_0_20px_rgba(0,255,255,0.12)]">
            <div className="flex items-center justify-between border-b border-cyan-500/20 pb-2 mb-2">
                <div className="flex items-center gap-2 text-cyan-400 font-bold">
                    <Camera className="w-4 h-4" />
                    <span className="tracking-wider">{node.node_id}</span>
                </div>
                <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-mono ${stale ? 'text-gray-500' : statusColor}`}>
                        {stale ? 'STALE' : statusLabel}
                    </span>
                    {node.display_lat !== undefined && node.display_lon !== undefined && (
                        <button
                            onClick={() => requestFocus(node.display_lat!, node.display_lon!)}
                            title="Center map on node (C)"
                            className="text-gray-500 hover:text-cyan-300 transition-colors p-0.5 hover:bg-white/10 rounded"
                        >
                            <Locate className="w-4 h-4" />
                        </button>
                    )}
                    <button
                        onClick={() => selectNode(null)}
                        title="Deselect (Esc)"
                        className="text-gray-500 hover:text-white transition-colors p-0.5 hover:bg-white/10 rounded"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </div>

            <div className="space-y-1.5">
                <Stat icon={<Gauge className="w-3 h-3" />} label="Frame Rate"
                    value={node.fps.toFixed(0)} unit="fps" />
                <Stat icon={<Cpu className="w-3 h-3" />} label="CPU"
                    value={node.cpu_usage.toFixed(0)} unit="%"
                    valueClass={node.cpu_usage > 80 ? 'text-red-400' : 'text-gray-100'} />
                <Stat icon={<Thermometer className="w-3 h-3" />} label="Temperature"
                    value={node.temp_c.toFixed(0)} unit="°C"
                    valueClass={node.temp_c > 75 ? 'text-red-400' : 'text-gray-100'} />
                <Stat icon={<Wifi className="w-3 h-3" />} label="Address"
                    value={node.ip_address || '—'} />
                <Stat icon={<Clock className="w-3 h-3" />} label="Last Seen"
                    value={Number.isNaN(ageSec) ? '—' : formatAge(ageSec)}
                    valueClass={stale ? 'text-yellow-400' : 'text-gray-100'} />
            </div>

            <div className="mt-2 pt-2 border-t border-white/10 grid grid-cols-3 gap-x-3 gap-y-1 text-[10px] font-mono text-gray-400">
                <span>E {pE.toFixed(1)}</span>
                <span>N {pN.toFixed(1)}</span>
                <span>U {pU.toFixed(1)}</span>
            </div>

            <div className="mt-2 pt-2 border-t border-white/10 flex items-center justify-between text-[10px] font-mono">
                <span className="text-gray-500">
                    CALIB: <span className={calib ? (CALIB_COLOR[calib] ?? 'text-gray-300') : 'text-gray-600'}>
                        {calib ? calib.toUpperCase() : '—'}
                    </span>
                </span>
                {node.cluster_id && (
                    <span className="text-gray-500">
                        DOMAIN: <span className="text-gray-300">{node.cluster_id}</span>
                    </span>
                )}
            </div>
        </div>
    );
}
