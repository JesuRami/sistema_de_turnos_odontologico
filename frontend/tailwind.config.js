/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Tokens mínimos de clínica (sin kit genérico — frontend-design).
        dental: {
          50: "#eef7f6",
          600: "#0e7c7b",
          900: "#083f3e"
        },
        enamel: "#f7f5ef"
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"]
      }
    }
  },
  plugins: []
};
