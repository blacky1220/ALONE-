import React, { useState } from 'react';
import { ChevronDown, TrendingDown, TrendingUp, X } from 'lucide-react';
import { Gauge } from './Gauge';

export const DashboardPreview: React.FC = () => {
  const [toggleCard1, setToggleCard1] = useState<'Impressions' | 'Clicks'>('Impressions');
  const [toggleCard3, setToggleCard3] = useState<'Video Clicks' | 'Video Starts'>('Video Clicks');

  return (
    <div className="px-3 sm:px-4 w-full">
      {/* Wrapper: bg-[#f5f2ee] rounded-3xl p-4 sm:p-6 w-full max-w-[880px] mx-auto */}
      <div className="bg-[#f5f2ee] rounded-3xl p-4 sm:p-6 w-full max-w-[880px] mx-auto shadow-sm">
        {/* Grid: grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
          {/* Card 1 — Clicks (white, rounded-2xl, p-5) */}
          <div className="bg-white rounded-2xl p-5 flex flex-col justify-between shadow-sm border border-neutral-100/70">
            <div>
              {/* Header: orange "Clicks" + neutral "This Month" (13px) */}
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-[#ef4d23] font-medium">Clicks</span>
                <span className="text-neutral-500">This Month</span>
              </div>

              {/* Big number "6,896" (28px, weight 600) + red pill bg-red-50 text-red-600 rounded-full px-2 py-0.5 with TrendingDown icon "-3,382 (33%)" (11px) */}
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[28px] font-semibold text-neutral-900 leading-tight">
                  6,896
                </span>
                <span className="inline-flex items-center gap-0.5 bg-red-50 text-red-600 rounded-full px-2 py-0.5 text-[11px] font-medium">
                  <TrendingDown className="w-3 h-3 stroke-[2.5]" />
                  <span>-3,382 (33%)</span>
                </span>
              </div>

              {/* Small caption "Compared to yesterday" */}
              <p className="text-[11px] text-neutral-400 mt-1">Compared to yesterday</p>

              {/* Centered "Month Target achieved" label */}
              <p className="text-[12px] text-neutral-600 text-center font-medium mt-3 mb-1">
                Month Target achieved
              </p>

              {/* Gauge at 92% in #ef4d23, with end labels "389K" / "425K" */}
              <Gauge value={92} color="#ef4d23" showLabels={true} min="389K" max="425K" />
            </div>

            {/* Toggle pill bottom: bg-neutral-100 rounded-full p-1 flex — "Impressions" active (white card + shadow) / "Clicks" inactive */}
            <div className="bg-neutral-100 rounded-full p-1 flex mt-4">
              <button
                type="button"
                onClick={() => setToggleCard1('Impressions')}
                className={`flex-1 py-1 px-3 text-xs font-medium rounded-full text-center transition-all cursor-pointer ${
                  toggleCard1 === 'Impressions'
                    ? 'bg-white shadow-sm text-neutral-900'
                    : 'text-neutral-500 hover:text-neutral-800'
                }`}
              >
                Impressions
              </button>
              <button
                type="button"
                onClick={() => setToggleCard1('Clicks')}
                className={`flex-1 py-1 px-3 text-xs font-medium rounded-full text-center transition-all cursor-pointer ${
                  toggleCard1 === 'Clicks'
                    ? 'bg-white shadow-sm text-neutral-900'
                    : 'text-neutral-500 hover:text-neutral-800'
                }`}
              >
                Clicks
              </button>
            </div>
          </div>

          {/* Card 2 — Form (white, rounded-2xl, p-5, flex flex-col gap-3) */}
          <div className="bg-white rounded-2xl p-5 flex flex-col justify-between gap-3 shadow-sm border border-neutral-100/70">
            <div className="flex flex-col gap-3">
              {/* Dropdown 1: Show figures for -> This month */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] text-neutral-700 font-medium">
                  Show figures for
                </label>
                <button
                  type="button"
                  className="flex items-center justify-between w-full border border-neutral-200 rounded-lg px-3 py-2 text-xs text-neutral-800 bg-white hover:border-neutral-300 transition-colors text-left"
                >
                  <span>This month</span>
                  <ChevronDown className="w-3.5 h-3.5 text-neutral-400 stroke-[2]" />
                </button>
              </div>

              {/* Dropdown 2: Compare period by -> Month-to-date (MTD) */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] text-neutral-700 font-medium">
                  Compare period by
                </label>
                <button
                  type="button"
                  className="flex items-center justify-between w-full border border-neutral-200 rounded-lg px-3 py-2 text-xs text-neutral-800 bg-white hover:border-neutral-300 transition-colors text-left"
                >
                  <span>Month-to-date (MTD)</span>
                  <ChevronDown className="w-3.5 h-3.5 text-neutral-400 stroke-[2]" />
                </button>
              </div>

              {/* Input 1: Ste targets (This month) -> 10 */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] text-neutral-700 font-medium">
                  Ste targets (This month)
                </label>
                <div className="flex items-center border border-neutral-200 rounded-lg px-3 py-1.5 bg-white focus-within:border-neutral-400">
                  <span className="text-xs text-neutral-400 mr-2 font-mono">#</span>
                  <input
                    type="text"
                    defaultValue="10"
                    className="w-full text-xs text-neutral-800 outline-none bg-transparent"
                  />
                </div>
              </div>

              {/* Input 2: Ste targets (This year) -> 100 */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] text-neutral-700 font-medium">
                  Ste targets (This year)
                </label>
                <div className="flex items-center border border-neutral-200 rounded-lg px-3 py-1.5 bg-white focus-within:border-neutral-400">
                  <span className="text-xs text-neutral-400 mr-2 font-mono">#</span>
                  <input
                    type="text"
                    defaultValue="100"
                    className="w-full text-xs text-neutral-800 outline-none bg-transparent"
                  />
                </div>
              </div>
            </div>

            {/* Footer: orange #ef4d23 "Save" button (rounded-lg px-5 py-2), underlined "Cancel", X icon pushed to right (ml-auto) */}
            <div className="flex items-center gap-3 pt-1">
              <button
                type="button"
                className="bg-[#ef4d23] text-white text-xs font-medium rounded-lg px-5 py-2 hover:bg-[#d94119] transition-colors shadow-sm cursor-pointer"
              >
                Save
              </button>
              <button
                type="button"
                className="text-xs text-neutral-600 underline hover:text-neutral-900 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                aria-label="Close"
                className="ml-auto text-neutral-400 hover:text-neutral-700 transition-colors p-1 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Card 3 — Video Starts (white, rounded-2xl, p-5) */}
          <div className="bg-white rounded-2xl p-5 flex flex-col justify-between shadow-sm border border-neutral-100/70">
            <div>
              {/* Header: orange "Video Starts" + "today" */}
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-[#ef4d23] font-medium">Video Starts</span>
                <span className="text-neutral-500">today</span>
              </div>

              {/* Big "0" + neutral pill with TrendingUp + "0" */}
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[28px] font-semibold text-neutral-900 leading-tight">
                  0
                </span>
                <span className="inline-flex items-center gap-0.5 bg-neutral-100 text-neutral-600 rounded-full px-2 py-0.5 text-[11px] font-medium">
                  <TrendingUp className="w-3 h-3 text-neutral-500 stroke-[2.5]" />
                  <span>0</span>
                </span>
              </div>

              {/* "Compared to yesterday" */}
              <p className="text-[11px] text-neutral-400 mt-1">Compared to yesterday</p>

              {/* Gauge at 68% in #9ca3af (no end labels) */}
              <div className="mt-5 mb-1">
                <Gauge value={68} color="#9ca3af" showLabels={false} />
              </div>
            </div>

            {/* Toggle pill: "Video Clicks" active / "Video Starts" */}
            <div className="bg-neutral-100 rounded-full p-1 flex mt-4">
              <button
                type="button"
                onClick={() => setToggleCard3('Video Clicks')}
                className={`flex-1 py-1 px-3 text-xs font-medium rounded-full text-center transition-all cursor-pointer ${
                  toggleCard3 === 'Video Clicks'
                    ? 'bg-white shadow-sm text-neutral-900'
                    : 'text-neutral-500 hover:text-neutral-800'
                }`}
              >
                Video Clicks
              </button>
              <button
                type="button"
                onClick={() => setToggleCard3('Video Starts')}
                className={`flex-1 py-1 px-3 text-xs font-medium rounded-full text-center transition-all cursor-pointer ${
                  toggleCard3 === 'Video Starts'
                    ? 'bg-white shadow-sm text-neutral-900'
                    : 'text-neutral-500 hover:text-neutral-800'
                }`}
              >
                Video Starts
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
