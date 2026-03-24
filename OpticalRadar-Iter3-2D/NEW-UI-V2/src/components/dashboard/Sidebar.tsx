import React from 'react';
import { Home, Video, Thermometer, MapPin, Shield } from 'lucide-react';
import { clsx } from 'clsx';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
  const tabs = [
    { id: 'overview', label: 'Overview', icon: Home },
    { id: 'live', label: 'Live Footage', icon: Video },
    { id: 'environment', label: 'Environment', icon: Thermometer },
    { id: 'position', label: 'Position Vector', icon: MapPin },
  ];

  return (
    <aside className="w-64 bg-[#0a162d]/55 backdrop-blur-md border-r border-white/10 p-6 flex flex-col gap-4 shrink-0">
      <div className="pb-6 border-b border-white/10 mb-2">
        <div className="flex items-center gap-3 mb-2">
          <Shield className="w-8 h-8 text-primary" />
          <h2 className="text-2xl font-bold text-white">SmartShield</h2>
        </div>
        <p className="text-sm text-muted leading-relaxed">
          Smart Location Environmental Monitoring and Alert System
        </p>
      </div>

      <nav className="flex flex-col gap-2">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                "w-full text-left px-4 py-3 rounded-xl flex items-center gap-3 transition-all duration-200",
                isActive 
                  ? "bg-gradient-to-br from-primary/20 to-blue-500/20 text-white shadow-[inset_0_0_0_1px_rgba(92,200,255,0.22)]" 
                  : "text-slate-300 hover:bg-white/10 hover:text-white hover:translate-x-1"
              )}
            >
              <Icon className="w-5 h-5" />
              <span className="font-medium">{tab.label}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
