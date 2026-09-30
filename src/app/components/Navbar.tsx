import React, { useState } from 'react';
import { ChevronDown, ChevronRight, ShoppingCart, Menu, X } from 'lucide-react';

export const Navbar: React.FC = () => {
  const [open, setOpen] = useState(false);

  // 8 circles at radius 10 around center (16,16) plus center circle, all r=3.5, viewBox 32x32
  const flowerPetals = Array.from({ length: 8 }, (_, i) => {
    const angle = (i * 2 * Math.PI) / 8;
    const cx = 16 + 10 * Math.cos(angle);
    const cy = 16 + 10 * Math.sin(angle);
    return <circle key={i} cx={cx} cy={cy} r={3.5} fill="#ef4d23" />;
  });

  return (
    <div className="flex justify-center pt-4 sm:pt-6 px-3 sm:px-4 w-full relative z-30">
      <nav className="bg-white rounded-full shadow-sm border border-neutral-200 pl-2 pr-2 py-2 w-full max-w-[760px] relative flex items-center justify-between">
        {/* Logo (left, shrink-0): orange #ef4d23 8-petal flower SVG */}
        <a href="#" className="flex items-center shrink-0 pl-1" aria-label="Home">
          <svg
            viewBox="0 0 32 32"
            className="w-7 h-7 sm:w-8 sm:h-8 shrink-0"
            aria-label="Convix Software Logo"
          >
            {flowerPetals}
            <circle cx={16} cy={16} r={3.5} fill="#ef4d23" />
          </svg>
        </a>

        {/* Desktop links (hidden md:flex, gap-6, 14px) */}
        <div className="hidden md:flex items-center gap-6 text-[14px]">
          <a
            href="#home"
            className="inline-flex items-center gap-2 font-medium text-neutral-900 hover:text-black transition-colors"
          >
            <span className="w-[1.5px] h-[1.5px] rounded-full bg-black inline-block"></span>
            <span>Home</span>
          </a>
          <a
            href="#features"
            className="font-normal text-neutral-600 hover:text-neutral-900 transition-colors"
          >
            Features
          </a>
          <a
            href="#about"
            className="font-normal text-neutral-600 hover:text-neutral-900 transition-colors"
          >
            About
          </a>
          <button
            type="button"
            className="inline-flex items-center gap-1 font-medium text-[#ef4d23] hover:text-[#d94119] transition-colors cursor-pointer"
          >
            <span>Pages</span>
            <ChevronDown className="w-3.5 h-3.5 stroke-[2.5]" />
          </button>
        </div>

        {/* Right cluster (ml-auto) */}
        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          {/* ShoppingCart icon (hidden on mobile) */}
          <button
            type="button"
            aria-label="Shopping Cart"
            className="hidden md:flex items-center justify-center p-1.5 text-neutral-700 hover:text-black transition-colors rounded-full"
          >
            <ShoppingCart className="w-4 h-4" />
          </button>

          {/* Orange #ef4d23 rounded-full button */}
          <button
            type="button"
            className="inline-flex items-center bg-[#ef4d23] text-white rounded-full pl-3.5 sm:pl-4 pr-1.5 py-1.5 text-xs sm:text-[14px] font-medium hover:bg-[#d94119] transition-colors shadow-sm cursor-pointer"
          >
            <span className="hidden sm:inline">Get early access</span>
            <span className="sm:hidden">Early access</span>
            <span className="w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-white/20 flex items-center justify-center ml-2">
              <ChevronRight className="w-3.5 h-3.5 text-white stroke-[2.5]" />
            </span>
          </button>

          {/* Mobile-only Menu (lucide) hamburger button (md:hidden) */}
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-label="Toggle menu"
            className="md:hidden flex items-center justify-center p-1.5 text-neutral-700 hover:text-black rounded-full focus:outline-none cursor-pointer"
          >
            {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

        {/* Dropdown panel when open */}
        {open && (
          <div className="absolute top-full left-2 right-2 mt-2 bg-white rounded-2xl shadow-lg border border-neutral-200 p-3 z-20 md:hidden flex flex-col gap-2.5">
            <a
              href="#home"
              onClick={() => setOpen(false)}
              className="inline-flex items-center gap-2 text-[14px] font-medium text-neutral-900 px-2 py-1.5 rounded-lg hover:bg-neutral-50"
            >
              <span className="w-[1.5px] h-[1.5px] rounded-full bg-black inline-block"></span>
              <span>Home</span>
            </a>
            <a
              href="#features"
              onClick={() => setOpen(false)}
              className="text-[14px] font-normal text-neutral-600 hover:text-neutral-900 px-2 py-1.5 rounded-lg hover:bg-neutral-50"
            >
              Features
            </a>
            <a
              href="#about"
              onClick={() => setOpen(false)}
              className="text-[14px] font-normal text-neutral-600 hover:text-neutral-900 px-2 py-1.5 rounded-lg hover:bg-neutral-50"
            >
              About
            </a>
            <div className="flex items-center justify-between text-[14px] font-medium text-[#ef4d23] px-2 py-1.5 rounded-lg hover:bg-neutral-50 cursor-pointer">
              <span>Pages</span>
              <ChevronDown className="w-3.5 h-3.5 stroke-[2.5]" />
            </div>
            <div className="pt-2 border-t border-neutral-100 flex items-center justify-between text-neutral-700 text-[14px] px-2 py-1.5">
              <span>Shopping Cart</span>
              <ShoppingCart className="w-4 h-4" />
            </div>
          </div>
        )}
      </nav>
    </div>
  );
};
