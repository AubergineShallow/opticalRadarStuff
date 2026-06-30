import React, { useState } from 'react';
import { Target, AlertCircle, ChevronUp, ChevronDown } from 'lucide-react';
import { Track } from '../../types';

interface TargetListProps {
    tracks: Record<string, Track>;
    onSelectTrack?: (id: string) => void;
    selectedTrackId?: string | null;
}

export function TargetList({ tracks, onSelectTrack, selectedTrackId }: TargetListProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const trackList = Object.values(tracks);

    return (
        <div className="bg-black/80 border border-amber-500/30 p-2 rounded w-96 backdrop-blur pointer-events-auto flex flex-col gap-2 shadow-[0_0_15px_rgba(255,165,0,0.1)] transition-all duration-200">
            <div className={`flex items-center justify-between px-2 ${isMinimized ? '' : 'border-b border-amber-500/20 pb-2'}`}>
                <div className="flex items-center gap-2 text-amber-400 font-bold">
                    <Target className="w-4 h-4" /> <span>TARGETS ({trackList.length})</span>
                </div>

                <div className="flex items-center gap-2">
                    {/* Warning about coordinate approximation */}
                    <div className="group relative">
                        <AlertCircle className="w-3 h-3 text-gray-500 cursor-help" />
                        <div className="absolute right-0 bottom-full mb-2 w-48 p-2 bg-gray-900 border border-gray-700 text-xs text-gray-400 rounded hidden group-hover:block z-50">
                            Coordinates are ENU-derived approximations relative to origin. Do not use for precise geodetic targeting.
                        </div>
                    </div>

                    <button
                        onClick={() => setIsMinimized(!isMinimized)}
                        className="text-amber-500/70 hover:text-amber-400 transition-colors p-1 hover:bg-amber-500/10 rounded"
                    >
                        {isMinimized ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                    </button>
                </div>
            </div>

            {!isMinimized && (
                <>
                    <div className="max-h-64 overflow-y-auto">
                        <table className="w-full text-xs text-left border-collapse">
                            <thead className="bg-white/5 text-gray-400 sticky top-0 backdrop-blur-md">
                                <tr>
                                    <th className="p-2 font-mono font-normal">ID</th>
                                    <th className="p-2 font-mono font-normal text-right">SPD</th>
                                    <th className="p-2 font-mono font-normal text-right">HDG</th>
                                    <th className="p-2 font-mono font-normal text-right">POS (ENU)</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {trackList.length === 0 ? (
                                    <tr>
                                        <td colSpan={4} className="p-8 text-center text-gray-600 italic">No Active Tracks</td>
                                    </tr>
                                ) : (
                                    trackList.map(track => {
                                        const isSelected = selectedTrackId === track.track_id.toString();
                                        const pU = track.position[2];

                                        // Speed / heading / approx lat-lon are precomputed once
                                        // at WebSocket receipt (P3.2) — no math in render.
                                        const display = track.display;

                                        return (
                                            <tr
                                                key={track.track_id}
                                                className={`
                                                    cursor-pointer transition-colors font-mono group
                                                    ${isSelected ? 'bg-amber-500/20' : 'hover:bg-white/10'}
                                                `}
                                                onClick={() => onSelectTrack?.(track.track_id.toString())}
                                            >
                                                <td className="p-2 text-amber-400 font-bold group-hover:text-amber-300">
                                                    T-{track.track_id}
                                                </td>
                                                <td className="p-2 text-right text-cyan-300">
                                                    {display?.speed_ms.toFixed(1) ?? '—'} <span className="text-gray-600 text-[9px]">m/s</span>
                                                </td>
                                                <td className="p-2 text-right text-white">
                                                    {display?.heading_deg.toFixed(0) ?? '—'}°
                                                </td>
                                                <td className="p-2 text-right text-gray-300">
                                                    <div className="flex flex-col text-[10px] leading-tight opacity-90">
                                                        <span title="Approximate Lat/Lon">{display?.lat.toFixed(4) ?? '—'}, {display?.lon.toFixed(4) ?? '—'}*</span>
                                                        <span className="text-[9px] text-gray-500">ALT: {pU.toFixed(0)}m</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })
                                )}
                            </tbody>
                        </table>
                    </div>
                    <div className="px-2 pb-1 text-[9px] text-gray-600 text-center uppercase tracking-widest">
                        * Coordinates Approx
                    </div>
                </>
            )}
        </div>
    );
}
