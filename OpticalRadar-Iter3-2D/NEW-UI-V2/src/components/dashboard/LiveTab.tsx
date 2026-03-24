import React from 'react';
import { Video } from 'lucide-react';

export default function LiveTab() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <LivePanel title="Live Camera Feed 1" />
      <LivePanel title="Live Camera Feed 2" />
    </div>
  );
}

function LivePanel({ title }: { title: string }) {
  return (
    <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg h-[600px] flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <div className="flex items-center gap-3 text-sm text-blue-200">
          <span>Live</span>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" className="sr-only peer" defaultChecked />
            <div className="w-11 h-6 bg-white/20 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-gradient-to-br peer-checked:from-sky-400 peer-checked:to-blue-500"></div>
          </label>
        </div>
      </div>
      <div className="flex-1 rounded-xl bg-gradient-to-br from-primary/20 to-blue-400/10 border border-dashed border-blue-300/40 flex flex-col items-center justify-center text-blue-100 gap-3">
        <Video className="w-12 h-12 opacity-80" />
        <div className="font-medium text-lg">Camera Stream Here</div>
        <p className="text-sm opacity-70">Use your real Raspberry Pi camera URL later</p>
        <span className="mt-2 px-4 py-1.5 rounded-full bg-success/20 text-green-300 text-sm border border-success/30 font-medium tracking-wide">STREAMING</span>
      </div>
    </div>
  );
}
