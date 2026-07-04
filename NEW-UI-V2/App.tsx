import React, { useMemo } from 'react';
import VisualizationMap from './components/visualization/Map';
import HUD from './components/HUD';
import { useMockData, useWebSocket } from './hooks';
import { Env } from './constants';

export default function App() {
  // Determine mode based on URL search param 'mock'.
  // Defaults to WebSocket mode unless ?mock=true is present.
  const shouldUseMock = useMemo(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      return params.get('mock') === 'true';
    }
    return false;
  }, []);

  // Initialize WebSocket connection if not in mock mode
  const { isConnected, sendCommand, reconnectAttempt } = useWebSocket(Env.WS_URL, !shouldUseMock);

  // Initialize Mock Data if in mock mode
  useMockData(shouldUseMock);

  // Live status label: distinguish the first connect from backoff retries so a
  // user staring at a dead backend can tell the UI is still trying.
  const liveLabel = isConnected
    ? 'LINK ACTIVE'
    : reconnectAttempt > 0 ? `RECONNECTING (${reconnectAttempt})` : 'CONNECTING…';

  return (
    <main className="w-screen h-screen overflow-hidden bg-black text-white relative">
      {/* 3D Visualization Layer */}
      <div className="absolute inset-0 z-0">
        <VisualizationMap />
      </div>

      {/* Interface Layer - Pointer events are handled within HUD components */}
      <div className="absolute inset-0 z-10 pointer-events-none">
        <HUD sendCommand={sendCommand} />

        {/* Connection Status Indicator */}
        {!shouldUseMock && (
          <div className="absolute bottom-4 right-4 pointer-events-auto flex items-center gap-2">
            {/* Offer the built-in simulator when the backend is unreachable so a
                first-time user isn't stranded on an empty black screen. */}
            {!isConnected && (
              <a
                href="?mock=true"
                className="px-3 py-1 rounded-full backdrop-blur-md border bg-amber-500/10 border-amber-500/30 text-amber-400 text-xs font-mono hover:bg-amber-500/25 transition-colors"
              >
                RUN SIM MODE
              </a>
            )}
            <div className={`flex items-center gap-2 px-3 py-1 rounded-full backdrop-blur-md border ${isConnected
                ? 'bg-green-500/10 border-green-500/30 text-green-400'
                : 'bg-red-500/10 border-red-500/30 text-red-400'
              } text-xs font-mono`}>
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500 animate-pulse'}`} />
              {liveLabel}
            </div>
          </div>
        )}

        {shouldUseMock && (
          <div className="absolute bottom-4 right-4 pointer-events-auto flex items-center gap-2">
            <a
              href="?"
              className="px-3 py-1 rounded-full backdrop-blur-md border bg-green-500/10 border-green-500/30 text-green-400 text-xs font-mono hover:bg-green-500/25 transition-colors"
            >
              GO LIVE
            </a>
            <div className="flex items-center gap-2 px-3 py-1 rounded-full backdrop-blur-md border bg-amber-500/10 border-amber-500/30 text-amber-400 text-xs font-mono">
              <div className="w-2 h-2 rounded-full bg-amber-500" />
              SIMULATION MODE
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
