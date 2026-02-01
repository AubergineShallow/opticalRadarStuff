import React from 'react';

interface TopBarProps {
    time: string;
}

export function TopBar({ time }: TopBarProps) {
    return (
        <div className="flex justify-between items-start pointer-events-auto w-full">
            <div className="bg-black/60 border-l-4 border-green-500 p-3 pr-6 rounded-r backdrop-blur">
                <h1 className="text-xl font-bold text-green-500 tracking-widest">OPTICA_RADAR // CIC</h1>
                <div className="text-xs text-green-500/60 font-mono mt-1 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                    STATUS: ACTIVE MONITORING
                </div>
            </div>

            <div className="bg-black/60 p-3 pl-6 rounded-l backdrop-blur text-right border-r-4 border-green-500/50">
                <div className="text-2xl font-bold font-mono text-white">{time}</div>
                <div className="text-xs text-gray-400 font-mono tracking-wider">ZULU / UTC</div>
            </div>
        </div>
    );
}