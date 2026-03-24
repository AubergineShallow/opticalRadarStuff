import React, { useMemo, useState } from 'react';
import { useMockData, useWebSocket } from './hooks';
import { Env } from './constants';
import Sidebar from './components/dashboard/Sidebar';
import OverviewTab from './components/dashboard/OverviewTab';
import LiveTab from './components/dashboard/LiveTab';
import EnvironmentTab from './components/dashboard/EnvironmentTab';
import PositionTab from './components/dashboard/PositionTab';

export default function App() {
  const shouldUseMock = useMemo(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.has('mock')) {
        return params.get('mock') === 'true';
      }
      return false; // Default to false to use real server data
    }
    return false;
  }, []);

  const { isConnected } = useWebSocket(Env.WS_URL, !shouldUseMock);
  useMockData(shouldUseMock);

  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="flex min-h-screen text-text-main font-sans">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      
      <main className="flex-1 p-6 h-screen overflow-y-auto">
        <div className="flex justify-between items-center gap-4 mb-6 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">Security Monitoring Dashboard</h1>
            <p className="text-muted text-sm">Smart Location Environmental Monitoring and Alert System</p>
          </div>
          <div className="inline-flex items-center gap-2.5 bg-white/10 border border-white/10 px-4 py-3 rounded-full text-slate-200 shadow-lg backdrop-blur-md">
            <span className="relative flex h-3 w-3">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${shouldUseMock ? 'bg-amber-400' : (isConnected ? 'bg-green-400' : 'bg-red-400')}`}></span>
              <span className={`relative inline-flex rounded-full h-3 w-3 ${shouldUseMock ? 'bg-amber-500' : (isConnected ? 'bg-green-500' : 'bg-red-500')}`}></span>
            </span>
            <span className="font-medium text-sm">
              {shouldUseMock ? 'Simulation Mode' : (isConnected ? 'System Online' : 'System Offline')}
            </span>
          </div>
        </div>

        <div className="animate-in fade-in duration-300">
          {activeTab === 'overview' && <OverviewTab />}
          {activeTab === 'live' && <LiveTab />}
          {activeTab === 'environment' && <EnvironmentTab />}
          {activeTab === 'position' && <PositionTab />}
        </div>
      </main>
    </div>
  );
}
