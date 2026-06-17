/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'aurora': {
          'green': '#00ff88',
          'yellow': '#ffcc00',
          'red': '#ff4444',
          'blue': '#00aaff',
          'purple': '#aa00ff',
          'dark': '#0a0a0f',
          'dark-light': '#1a1a2e'
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate'
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px currentColor' },
          '100%': { boxShadow: '0 0 20px currentColor, 0 0 30px currentColor' }
        }
      }
    },
  },
  plugins: [],
}
