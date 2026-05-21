/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // custom safe-area aware spacing handled via CSS vars
      },
    },
  },
  plugins: [],
};
