/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        serif: ['"Instrument Serif"', 'serif'],
      },
      colors: {
        brand: {
          orange: '#ef4d23',
          dark: '#0b0f1a',
          pageBg: '#ededed',
          heroBg: '#d9d9d9',
          trayBg: '#f5f2ee',
        }
      }
    },
  },
  plugins: [],
};
