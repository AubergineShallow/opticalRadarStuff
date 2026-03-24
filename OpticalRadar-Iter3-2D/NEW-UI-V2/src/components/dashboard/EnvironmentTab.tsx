import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const tempData = [
  { time: '10:00', value: 27.8 },
  { time: '10:05', value: 28.1 },
  { time: '10:10', value: 28.6 },
  { time: '10:15', value: 28.9 },
  { time: '10:20', value: 29.2 },
  { time: '10:25', value: 29.4 },
];

const humData = [
  { time: '10:00', value: 68 },
  { time: '10:05', value: 69 },
  { time: '10:10', value: 70 },
  { time: '10:15', value: 72 },
  { time: '10:20', value: 73 },
  { time: '10:25', value: 74 },
];

export default function EnvironmentTab() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg">
        <h3 className="text-lg font-semibold text-white mb-6">Temperature Trend</h3>
        <div className="h-80 bg-white/5 rounded-xl p-4">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={tempData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
              <XAxis dataKey="time" stroke="#d6deea" tick={{fill: '#d6deea'}} />
              <YAxis stroke="#d6deea" tick={{fill: '#d6deea'}} domain={['dataMin - 1', 'dataMax + 1']} />
              <Tooltip 
                contentStyle={{ backgroundColor: 'rgba(15, 23, 42, 0.9)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff' }}
                itemStyle={{ color: '#facc15' }}
              />
              <Legend />
              <Line type="monotone" dataKey="value" name="Temperature (°C)" stroke="#facc15" strokeWidth={3} dot={{ r: 4, fill: '#fde68a' }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-lg">
        <h3 className="text-lg font-semibold text-white mb-6">Humidity Trend</h3>
        <div className="h-80 bg-white/5 rounded-xl p-4">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={humData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
              <XAxis dataKey="time" stroke="#d6deea" tick={{fill: '#d6deea'}} />
              <YAxis stroke="#d6deea" tick={{fill: '#d6deea'}} domain={['dataMin - 2', 'dataMax + 2']} />
              <Tooltip 
                contentStyle={{ backgroundColor: 'rgba(15, 23, 42, 0.9)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#fff' }}
                itemStyle={{ color: '#4ade80' }}
              />
              <Legend />
              <Line type="monotone" dataKey="value" name="Humidity (%)" stroke="#4ade80" strokeWidth={3} dot={{ r: 4, fill: '#bbf7d0' }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
