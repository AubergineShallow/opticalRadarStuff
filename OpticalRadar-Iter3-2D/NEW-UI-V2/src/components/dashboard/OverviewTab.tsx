import React from 'react';
import { Flame, Activity, Thermometer, Droplets, Camera } from 'lucide-react';

export default function OverviewTab() {
  return (
    <div className="space-y-6">
      {/* Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-5 shadow-lg relative overflow-hidden group">
          <div className="absolute -top-12 -right-12 w-32 h-32 bg-white/5 rounded-full group-hover:bg-white/10 transition-colors"></div>
          <div className="flex items-center gap-2 mb-3">
            <Flame className="w-5 h-5 text-danger" />
            <h3 className="text-sm font-semibold text-slate-200">Fire Alarm State</h3>
          </div>
          <div className="text-3xl font-bold text-danger mb-2">PRESSED</div>
          <div className="text-xs text-muted">Manual emergency trigger activated</div>
        </div>

        <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-5 shadow-lg relative overflow-hidden group">
          <div className="absolute -top-12 -right-12 w-32 h-32 bg-white/5 rounded-full group-hover:bg-white/10 transition-colors"></div>
          <div className="flex items-center gap-2 mb-3">
            <Activity className="w-5 h-5 text-warning" />
            <h3 className="text-sm font-semibold text-slate-200">PIR Motion</h3>
          </div>
          <div className="text-3xl font-bold text-warning mb-2">DETECTED</div>
          <div className="text-xs text-muted">Movement detected near monitored zone</div>
        </div>

        <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-5 shadow-lg relative overflow-hidden group">
          <div className="absolute -top-12 -right-12 w-32 h-32 bg-white/5 rounded-full group-hover:bg-white/10 transition-colors"></div>
          <div className="flex items-center gap-2 mb-3">
            <Thermometer className="w-5 h-5 text-primary" />
            <h3 className="text-sm font-semibold text-slate-200">Temperature</h3>
          </div>
          <div className="text-3xl font-bold text-white mb-2">29.4°C</div>
          <div className="text-xs text-muted">Current room temperature</div>
        </div>

        <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-5 shadow-lg relative overflow-hidden group">
          <div className="absolute -top-12 -right-12 w-32 h-32 bg-white/5 rounded-full group-hover:bg-white/10 transition-colors"></div>
          <div className="flex items-center gap-2 mb-3">
            <Droplets className="w-5 h-5 text-blue-400" />
            <h3 className="text-sm font-semibold text-slate-200">Humidity</h3>
          </div>
          <div className="text-3xl font-bold text-white mb-2">74%</div>
          <div className="text-xs text-muted">Current environmental humidity</div>
        </div>
      </div>

      {/* Cameras */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <CameraPanel title="Camera 1 Feed" id="1" />
        <CameraPanel title="Camera 2 Feed" id="2" />
      </div>

      {/* Logs */}
      <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg">
        <h3 className="text-lg font-semibold text-white mb-4">Recent Alerts</h3>
        <ul className="space-y-0">
          {[
            { time: '14:02:11', msg: 'PIR motion detected near entrance' },
            { time: '14:03:06', msg: 'Manual fire alarm button pressed' },
            { time: '14:04:20', msg: 'Humidity level exceeded configured threshold' },
            { time: '14:05:02', msg: 'Camera vector updated to Zone 3' },
          ].map((log, i) => (
            <li key={i} className="flex justify-between items-center py-3 border-b border-white/10 last:border-0 text-sm">
              <span className="text-primary font-semibold font-mono">{log.time}</span>
              <span className="text-slate-300">{log.msg}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function CameraPanel({ title, id }: { title: string, id: string }) {
  return (
    <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <div className="flex items-center gap-3 text-sm text-blue-200">
          <span>Camera</span>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" className="sr-only peer" defaultChecked />
            <div className="w-11 h-6 bg-white/20 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-gradient-to-br peer-checked:from-sky-400 peer-checked:to-blue-500"></div>
          </label>
        </div>
      </div>
      <div className="w-full h-64 rounded-xl bg-gradient-to-br from-primary/20 to-blue-400/10 border border-dashed border-blue-300/40 flex flex-col items-center justify-center text-blue-100 gap-3">
        <Camera className="w-10 h-10 opacity-80" />
        <div className="font-medium">Live Feed Placeholder</div>
        <p className="text-xs opacity-70">Replace this area with actual camera stream later</p>
        <span className="mt-2 px-3 py-1 rounded-full bg-success/20 text-green-300 text-xs border border-success/30">Camera Active</span>
      </div>
    </div>
  );
}
