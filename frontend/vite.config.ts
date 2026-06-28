import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: ["mac-mini.local", "mac-mini-giuseppe-luvara.local", "192.168.1.62"],
    // Proxy verso il backend Django in dev.
    proxy: {
      "/api": "http://backend:8000",
      "/media": "http://backend:8000",
      "/healthz": "http://backend:8000",
    },
  },
});
