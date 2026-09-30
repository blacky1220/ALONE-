import React from 'react';
import { ChevronRight } from 'lucide-react';
import { Navbar } from './components/Navbar';
import { DashboardPreview } from './components/DashboardPreview';

export const App: React.FC = () => {
  return (
    /* Page Frame: Outer wrapper: min-h-screen w-full bg-[#ededed] p-3 sm:p-4, font-family Inter */
    <div className="min-h-screen w-full bg-[#ededed] p-3 sm:p-4 font-sans antialiased">
      {/* Hero container (clips everything inside): relative w-full h-[calc(100vh-24px)] sm:h-[calc(100vh-32px)] overflow-hidden bg-[#d9d9d9] rounded-2xl sm:rounded-3xl */}
      <div className="relative w-full h-[calc(100vh-24px)] sm:h-[calc(100vh-32px)] overflow-hidden bg-[#d9d9d9] rounded-2xl sm:rounded-3xl flex flex-col justify-between">
        {/* Background Video */}
        <video
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          disableRemotePlayback
          // @ts-ignore
          webkit-playsinline="true"
          x5-playsinline="true"
          poster="https://images.unsplash.com/photo-1557683316-973673baf926?w=1600&q=60"
        >
          <source
            src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260424_064411_9e9d7f84-9277-41f4-ab10-59172d89e6be.mp4"
            type="video/mp4"
          />
        </video>

        {/* Above the video: absolute inset-0 bg-white/10 overlay */}
        <div className="absolute inset-0 bg-white/10 pointer-events-none" />

        {/* Foreground content wrapper: relative z-10 */}
        <div className="relative z-10 flex flex-col h-full justify-between overflow-y-auto sm:overflow-hidden">
          {/* Navbar (floating pill) */}
          <Navbar />

          {/* Hero Content (centered): flex flex-col items-center px-4 pt-10 sm:pt-16 pb-8 sm:pb-12 text-center */}
          <div className="flex flex-col items-center px-4 pt-10 sm:pt-16 pb-8 sm:pb-12 text-center my-auto">
            {/* Badge: inline-flex items-center gap-2 bg-white rounded-full px-4 py-1.5 shadow-sm, 13px — orange dot + "Convix Software" */}
            <div className="inline-flex items-center gap-2 bg-white rounded-full px-4 py-1.5 shadow-sm text-[13px] font-medium text-neutral-800">
              <span className="w-2 h-2 rounded-full bg-[#ef4d23]"></span>
              <span>Convix Software</span>
            </div>

            {/* Headline <h1> with inline style fontSize: clamp(36px, 8vw, 72px); lineHeight: 1.05; fontWeight: 500; letterSpacing: -0.02em, mt-5 sm:mt-6 max-w-4xl */}
            <h1
              className="mt-5 sm:mt-6 max-w-4xl text-[#0b0f1a]"
              style={{
                fontSize: 'clamp(36px, 8vw, 72px)',
                lineHeight: 1.05,
                fontWeight: 500,
                letterSpacing: '-0.02em',
              }}
            >
              Shaping{' '}
              <span
                style={{
                  fontFamily: "'Instrument Serif', serif",
                  fontStyle: 'italic',
                  fontWeight: 400,
                }}
              >
                Agencies
              </span>
              <br />
              of tomorrow
            </h1>

            {/* Subtitle <p> mt-4 sm:mt-6 text-neutral-700 px-2, fontSize: clamp(13px, 3.5vw, 16px): "The All-In-One Software Powering the Future of PR Agencies" */}
            <p
              className="mt-4 sm:mt-6 text-neutral-700 px-2 max-w-xl mx-auto"
              style={{
                fontSize: 'clamp(13px, 3.5vw, 16px)',
              }}
            >
              The All-In-One Software Powering the Future of PR Agencies
            </p>

            {/* CTA button mt-6 sm:mt-8 inline-flex items-center gap-3 bg-[#0b0f1a] text-white rounded-full pl-6 sm:pl-7 pr-2 py-2 sm:py-2.5, 14px */}
            <button
              type="button"
              className="mt-6 sm:mt-8 inline-flex items-center gap-3 bg-[#0b0f1a] text-white rounded-full pl-6 sm:pl-7 pr-2 py-2 sm:py-2.5 text-[14px] font-medium shadow-md hover:bg-neutral-800 transition-all cursor-pointer"
            >
              <span>Get Started</span>
              <span className="w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-white/15 flex items-center justify-center">
                <ChevronRight className="w-4 h-4 text-white stroke-[2.5]" />
              </span>
            </button>
          </div>

          {/* Dashboard Preview: cards bleed off the bottom edge */}
          <div className="mt-auto transform translate-y-6 sm:translate-y-10 lg:translate-y-14">
            <DashboardPreview />
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
