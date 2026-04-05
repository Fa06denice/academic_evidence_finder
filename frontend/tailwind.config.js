/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        bg:       '#0c0e13',
        surface:  '#13151c',
        surface2: '#191c25',
        border:   '#252836',
        muted:    '#6b7280',
        accent:   '#6366f1',
        'accent-hover': '#4f46e5',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    }
  },
  plugins: []
}
