import React from 'react';
import { Layers, Zap, Box, Route, Rotate3d } from 'lucide-react';
import { useAppStore } from '../../store';

/**
 * Layer / view controls. These toggles drive store flags (showRays, showVoxels,
 * showHistory, is3DMode) that the deck.gl layers already consume — previously
 * there was no UI to reach them, so the ray/voxel/trail layers could never be
 * turned off and the map was permanently 3D. Keyboard shortcuts (R/V/T/P) are
 * wired up in HUD.
 */
interface ToggleButtonProps {
    active: boolean;
    onClick: () => void;
    icon: React.ReactNode;
    label: string;
    hotkey: string;
    activeColor: string; // tailwind text/border color classes when active
}

function ToggleButton({ active, onClick, icon, label, hotkey, activeColor }: ToggleButtonProps) {
    return (
        <button
            onClick={onClick}
            aria-pressed={active}
            title={`${label} (${hotkey})`}
            className={`flex items-center justify-between gap-3 px-2 py-1.5 rounded font-mono text-xs border transition-colors ${
                active
                    ? `${activeColor} bg-white/5`
                    : 'text-gray-500 border-white/10 hover:text-gray-300 hover:border-white/20'
            }`}
        >
            <span className="flex items-center gap-2">
                {icon}
                {label}
            </span>
            <span className="flex items-center gap-2">
                <span className="text-[9px] text-gray-600 border border-white/10 rounded px-1">{hotkey}</span>
                <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-current' : 'bg-gray-700'}`} />
            </span>
        </button>
    );
}

export function LayerControls() {
    const showRays = useAppStore(s => s.showRays);
    const showVoxels = useAppStore(s => s.showVoxels);
    const showHistory = useAppStore(s => s.showHistory);
    const is3DMode = useAppStore(s => s.is3DMode);
    const toggleLayer = useAppStore(s => s.toggleLayer);
    const toggle3D = useAppStore(s => s.toggle3D);

    return (
        <div className="bg-black/80 border border-white/15 p-2 rounded w-52 backdrop-blur pointer-events-auto flex flex-col gap-1.5 shadow-[0_0_15px_rgba(255,255,255,0.05)]">
            <div className="flex items-center gap-2 text-gray-300 font-bold px-1 pb-1 border-b border-white/10">
                <Layers className="w-4 h-4" />
                <span className="text-sm tracking-wider">LAYERS</span>
            </div>
            <ToggleButton
                active={showRays} onClick={() => toggleLayer('rays')}
                icon={<Zap className="w-3.5 h-3.5" />} label="Rays" hotkey="R"
                activeColor="text-cyan-400 border-cyan-500/40"
            />
            <ToggleButton
                active={showVoxels} onClick={() => toggleLayer('voxels')}
                icon={<Box className="w-3.5 h-3.5" />} label="Voxels" hotkey="V"
                activeColor="text-red-400 border-red-500/40"
            />
            <ToggleButton
                active={showHistory} onClick={() => toggleLayer('history')}
                icon={<Route className="w-3.5 h-3.5" />} label="Trails" hotkey="T"
                activeColor="text-amber-400 border-amber-500/40"
            />
            <ToggleButton
                active={is3DMode} onClick={toggle3D}
                icon={<Rotate3d className="w-3.5 h-3.5" />} label="3D View" hotkey="P"
                activeColor="text-green-400 border-green-500/40"
            />
            {/* Non-toggle hotkeys (handled in HUD) — listed for discoverability. */}
            <div className="flex items-center justify-between px-1 pt-1 border-t border-white/10 text-[9px] font-mono text-gray-600">
                <span><span className="border border-white/10 rounded px-1">C</span> center selection</span>
                <span><span className="border border-white/10 rounded px-1">ESC</span> deselect</span>
            </div>
        </div>
    );
}
