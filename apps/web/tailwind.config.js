/** @type {import('tailwindcss').Config} */
const v = (n) => `rgb(var(--${n}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v('bg'), surface: v('surface'), sunken: v('sunken'), line: v('line'),
        ink: v('ink'), muted: v('muted'), rail: v('rail'), 'rail-ink': v('rail-ink'),
        brand: v('brand'), 'brand-ink': v('brand-ink'), 'brand-soft': v('brand-soft'),
        warn: v('warn'), 'warn-soft': v('warn-soft'),
        danger: v('danger'), 'danger-soft': v('danger-soft'),
        ok: v('ok'), 'ok-soft': v('ok-soft'),
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', 'system-ui', 'sans-serif'],
        sans: ['"Hanken Grotesk Variable"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'monospace'],
      },
      borderRadius: { card: '10px' },
    },
  },
  plugins: [],
}
