

import React, { useState } from 'react';
import { Power, Activity, Cpu, Server, ChevronUp, ChevronDown } from 'lucide-react';
import { SystemStatus } from '../../types';

interface SystemHealthProps {
    status: SystemStatus;
}

export function SystemHealth({ status }: SystemHealthProps) {
    const [isMinimized, setIsMinimized] = useState(false);

    // Guard against undefined status properties during initial load/mock switch
    const fps = status?.server_fps ?? 0;
    const cpu = status?.cpu_percent ?? 0;
    const mem = status?.memory_percent ?? 0;
    const uptime = status?.uptime_seconds ?? 0;

    return (
        <div className="bg-black/80 border border-green-500/30 p-2 rounded w-64 backdrop-blur pointer-events-auto shadow-[0_0_15px_rgba(0,255,0,0.1)] transition-all duration-200">
            <div className={`flex items-center justify-between px-2 ${isMinimized ? '' : 'border-b border-green-500/30 pb-2 mb-2'}`}>
                <div className="flex items-center gap-2 text-green-400">
                    <Activity className="w-4 h-4" />
                    <span className="font-bold tracking-wider text-sm">SYSTEM HEALTH</span>
                </div>
                <button
                    onClick={() => setIsMinimized(!isMinimized)}
                    className="text-green-500/70 hover:text-green-400 transition-colors p-1 hover:bg-green-500/10 rounded"
                >
                    {isMinimized ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                </button>
            </div>

            {!isMinimized && (
                <div className="space-y-2 text-sm text-gray-300 font-mono px-2">
                    <div className="flex justify-between items-center">
                        <span className="flex items-center gap-2"><Server className="w-3 h-3 text-gray-500" /> FPS</span>
                        <span className="text-green-300">{fps.toFixed(1)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                        <span className="flex items-center gap-2"><Cpu className="w-3 h-3 text-gray-500" /> CPU</span>
                        <span className={cpu > 80 ? "text-red-400" : "text-green-300"}>
                            {cpu.toFixed(1)}%
                        </span>
                    </div>
                    <div className="flex justify-between items-center">
                        <span className="flex items-center gap-2"><Power className="w-3 h-3 text-gray-500" /> MEM</span>
                        <span>{mem.toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between items-center pt-2 border-t border-white/10 mt-2">
                        <span className="text-xs text-gray-500">UPTIME</span>
                        <span className="text-xs">{(uptime / 60).toFixed(0)} MIN</span>
                    </div>
                </div>
            )}
        </div>
    );
}
