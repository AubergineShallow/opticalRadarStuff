import React from 'react';
import { Crosshair, X, Gauge, Compass, Move3d, Activity, Locate, Ruler } from 'lucide-react';
import { useAppStore } from '../../store';
import { TrackState } from '../../types';

const STATE_LABEL: Record<number, string> = {
    [TrackState.TENTATIVE]: 'TENTATIVE',
    [TrackState.CONFIRMED]: 'CONFIRMED',
    [TrackState.LOST]: 'LOST',
    [TrackState.DELETED]: 'DELETED',
};

const STATE_COLOR: Record<number, string> = {
    [TrackState.TENTATIVE]: 'text-yellow-400',
    [TrackState.CONFIRMED]: 'text-green-400',
    [TrackState.LOST]: 'text-orange-400',
    [TrackState.DELETED]: 'text-red-400',
};

function Stat({ icon, label, value, unit }: { icon: React.ReactNode; label: string; value: string; unit?: string }) {
    return (
        <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-gray-400 text-[11px]">{icon}{label}</span>
            <span className="text-gray-100 font-mono text-xs">
                {value}{unit && <span className="text-gray-500 text-[9px] ml-0.5">{unit}</span>}
            </span>
        </div>
    );
}

/**
 * Detail card for the currently-selected track. Selecting a track (in the list
 * or on the map) previously only highlighted it; this surfaces its full state so
 * an operator can read velocity, heading, confidence and lifecycle at a glance.
 */
export function TrackDetail() {
    const selectedTrackId = useAppStore(s => s.selectedTrackId);
    const tracks = useAppStore(s => s.tracks);
    const selectTrack = useAppStore(s => s.selectTrack);
    const requestFocus = useAppStore(s => s.requestFocus);

    if (!selectedTrackId) return null;
    const track = tracks[selectedTrackId];
    if (!track) return null;

    const d = track.display;
    const [pE, pN, pU] = track.position;
    const [vE, vN, vU] = track.velocity;
    const stateLabel = STATE_LABEL[track.state] ?? 'UNKNOWN';
    const stateColor = STATE_COLOR[track.state] ?? 'text-gray-400';

    return (
        <div className="bg-black/85 border border-amber-500/40 p-3 rounded w-72 backdrop-blur pointer-events-auto shadow-[0_0_20px_rgba(255,165,0,0.15)]">
            <div className="flex items-center justify-between border-b border-amber-500/20 pb-2 mb-2">
                <div className="flex items-center gap-2 text-amber-400 font-bold">
                    <Crosshair className="w-4 h-4" />
                    <span className="tracking-wider">TRACK T-{track.track_id}</span>
                </div>
                <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-mono ${stateColor}`}>{stateLabel}</span>
                    {d && (
                        <button
                            onClick={() => requestFocus(d.lat, d.lon)}
                            title="Center map on track (C)"
                            className="text-gray-500 hover:text-amber-300 transition-colors p-0.5 hover:bg-white/10 rounded"
                        >
                            <Locate className="w-4 h-4" />
                        </button>
                    )}
                    <button
                        onClick={() => selectTrack(null)}
                        title="Deselect (Esc)"
                        className="text-gray-500 hover:text-white transition-colors p-0.5 hover:bg-white/10 rounded"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </div>

            <div className="space-y-1.5">
                <Stat icon={<Gauge className="w-3 h-3" />} label="Speed"
                    value={d ? d.speed_ms.toFixed(1) : '—'} unit="m/s" />
                <Stat icon={<Compass className="w-3 h-3" />} label="Heading"
                    value={d ? d.heading_deg.toFixed(0) : '—'} unit="°" />
                <Stat icon={<Activity className="w-3 h-3" />} label="Confidence"
                    value={(track.confidence * 100).toFixed(0)} unit="%" />
                <Stat icon={<Move3d className="w-3 h-3" />} label="Altitude"
                    value={pU.toFixed(0)} unit="m" />
                {/* Server-fused size from sensor angular sizes; 0 = no estimate. */}
                <Stat icon={<Ruler className="w-3 h-3" />} label="Est. Size"
                    value={track.physical_size && track.physical_size > 0
                        ? track.physical_size.toFixed(1) : '—'}
                    unit="m" />
            </div>

            <div className="mt-2 pt-2 border-t border-white/10 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] font-mono text-gray-400">
                <span>E {pE.toFixed(1)}</span>
                <span>vE {vE.toFixed(1)}</span>
                <span>N {pN.toFixed(1)}</span>
                <span>vN {vN.toFixed(1)}</span>
                <span>U {pU.toFixed(1)}</span>
                <span>vU {vU.toFixed(1)}</span>
            </div>

            {d && (
                <div className="mt-2 pt-2 border-t border-white/10 text-[10px] text-gray-500 font-mono">
                    ~{d.lat.toFixed(5)}, {d.lon.toFixed(5)}
                    <span className="text-gray-600"> (approx)</span>
                </div>
            )}
            {track.cluster_id && (
                <div className="mt-1 text-[10px] text-gray-500 font-mono">
                    DOMAIN: <span className="text-gray-300">{track.cluster_id}</span>
                </div>
            )}
        </div>
    );
}
