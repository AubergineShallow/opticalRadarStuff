import React, { useState } from 'react';
import { Target, ChevronUp, ChevronDown } from 'lucide-react';
import { Track } from '../../types';
import { UI_CONFIG } from '../../constants';

interface TargetListProps {
    tracks: Record<string, Track>;
    onSelectTrack?: (id: string) => void;
    selectedTrackId?: string | null;
}

export function TargetList({ tracks, onSelectTrack, selectedTrackId }: TargetListProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const trackList = Object.values(tracks);

    return (
        <div className="bg-black/50 border border-amber-500/40 p-3 rounded-xl w-96 backdrop-blur-md pointer-events-auto flex flex-col gap-2 shadow-[0_0_20px_rgba(255,165,0,0.15)] transition-all duration-300 hover:shadow-[0_0_30px_rgba(255,165,0,0.25)]">
            <div className={`flex items-center justify-between px-2 ${isMinimized ? '' : 'border-b border-amber-500/20 pb-2'}`}>
                <div className="flex items-center gap-2 text-amber-400 font-bold">
                    <Target className="w-4 h-4" /> <span>TARGETS ({trackList.length})</span>
                </div>

                <div className="flex items-center gap-2">
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
                                        // Vector2 destructuring
                                        const [vE, vN] = track.velocity;
                                        const [pE, pN] = track.position;

                                        // Calculate Speed (2D)
                                        const speed = Math.sqrt(vE ** 2 + vN ** 2);

                                        // Calculate Heading (Azimuth)
                                        let heading = Math.atan2(vE, vN) * (180 / Math.PI);
                                        if (heading < 0) heading += 360;

                                        // Approximation of Lat/Lon from ENU for display hints only
                                        const REF_LAT = UI_CONFIG.INITIAL_VIEW_STATE.latitude;
                                        const REF_LON = UI_CONFIG.INITIAL_VIEW_STATE.longitude;
                                        const lat = REF_LAT + (pN / 111111);
                                        const lon = REF_LON + (pE / (111111 * Math.cos(REF_LAT * Math.PI / 180)));

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
                                                    {speed.toFixed(1)} <span className="text-gray-600 text-[9px]">m/s</span>
                                                </td>
                                                <td className="p-2 text-right text-white">
                                                    {heading.toFixed(0)}°
                                                </td>
                                                <td className="p-2 text-right text-gray-300">
                                                    <div className="flex flex-col text-[10px] leading-tight opacity-90">
                                                        <span title="Approximate Lat/Lon">{lat.toFixed(5)}, {lon.toFixed(5)}</span>
                                                        <span className="text-[9px] text-gray-500">[{pE.toFixed(0)}, {pN.toFixed(0)}]</span>
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
