import React from 'react';

export interface GaugeProps {
  value: number;
  color?: string;
  showLabels?: boolean;
  min?: string | number;
  max?: string | number;
}

export const Gauge: React.FC<GaugeProps> = ({
  value,
  color = '#ef4d23',
  showLabels = false,
  min = '0',
  max = '100',
}) => {
  const totalTicks = 40;
  const clampedValue = Math.min(100, Math.max(0, value));
  const activeTicks = Math.round((clampedValue / 100) * totalTicks);
  const cx = 100;
  const cy = 100;
  const outerR = 80;
  const innerR = 70; // radius (r-10) to r=80

  const ticks = Array.from({ length: totalTicks }, (_, i) => {
    // 40 tick marks spanning a 180° arc (start at angle π, sweep to 2π)
    const angle = Math.PI + (i / (totalTicks - 1)) * Math.PI;
    const x1 = cx + innerR * Math.cos(angle);
    const y1 = cy + innerR * Math.sin(angle);
    const x2 = cx + outerR * Math.cos(angle);
    const y2 = cy + outerR * Math.sin(angle);
    const isActive = i < activeTicks;

    return (
      <line
        key={i}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={isActive ? color : '#d4d4d8'}
        strokeWidth={2.5}
        strokeLinecap="round"
      />
    );
  });

  return (
    <div className="flex flex-col items-center w-full max-w-[260px] mx-auto">
      <svg viewBox="0 0 200 120" className="w-full max-w-[260px] h-auto overflow-visible">
        {ticks}
        <text
          x={100}
          y={105}
          textAnchor="middle"
          fontSize={22}
          fontWeight={600}
          fill="#0b0f1a"
          className="select-none"
        >
          {value}%
        </text>
      </svg>
      {showLabels && (
        <div className="flex justify-between w-full text-[11px] text-neutral-500 font-medium px-2 -mt-1">
          <span>{min}</span>
          <span>{max}</span>
        </div>
      )}
    </div>
  );
};
