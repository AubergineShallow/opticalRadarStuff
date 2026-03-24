import React from 'react';
import VisualizationMap from '../visualization/Map';
import HUD from '../HUD';

export default function PositionTab() {
  return (
    <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg flex flex-col h-[calc(100vh-140px)]">
      <h3 className="text-lg font-semibold text-white mb-4 shrink-0">Vector Display for Position from Camera</h3>
      
      <div className="flex-1 relative rounded-xl overflow-hidden border border-white/10 bg-black">
        {/* 2D Visualization Layer */}
        <div className="absolute inset-0 z-0">
          <VisualizationMap />
        </div>

        {/* Interface Layer - Pointer events are handled within HUD components */}
        <div className="absolute inset-0 z-10 pointer-events-none">
          <HUD />
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 shrink-0">
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h4 className="text-blue-200 text-sm mb-2">Detected X Position</h4>
          <span className="text-2xl font-bold text-white">280</span>
        </div>
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h4 className="text-blue-200 text-sm mb-2">Detected Y Position</h4>
          <span className="text-2xl font-bold text-white">170</span>
        </div>
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h4 className="text-blue-200 text-sm mb-2">Current Direction</h4>
          <span className="text-2xl font-bold text-white">Right</span>
        </div>
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <h4 className="text-blue-200 text-sm mb-2">Current Zone</h4>
          <span className="text-2xl font-bold text-white">Zone 3</span>
        </div>
      </div>
      
      <div className="text-xs text-muted text-right mt-3 shrink-0">
        This section is connected to real camera tracking coordinates via WebSocket.
      </div>
    </div>
  );
}
