/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['IBM Plex Mono', 'monospace'],
        sans: ['IBM Plex Sans', 'sans-serif'],
      },
      colors: {
        pyra: {
          bg:       '#0d0f11',
          surface:  '#12151a',
          surface2: '#171b22',
          border:   '#1f2530',
          border2:  '#252d38',
          text:     '#d4dce8',
          dim:      '#5a6878',
          muted:    '#3a4558',
          fire:     '#ff4d1a',
          amber:    '#f59e0b',
          safe:     '#22c55e',
          info:     '#38bdf8',
          critical: '#ef4444',
        }
      }
    },
  },
  plugins: [],
}
