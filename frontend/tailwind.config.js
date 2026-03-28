/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['Barlow Condensed', 'sans-serif'],
        body: ['DM Mono', 'monospace'],
      },
      colors: {
        pyra: {
          bg:      '#0a0c0f',
          surface: '#111418',
          border:  '#1e2530',
          muted:   '#2a3240',
          text:    '#c8d4e0',
          dim:     '#5a6a7a',
          fire:    '#ff4e1a',
          amber:   '#f59e0b',
          safe:    '#22c55e',
          info:    '#38bdf8',
        }
      }
    },
  },
  plugins: [],
}