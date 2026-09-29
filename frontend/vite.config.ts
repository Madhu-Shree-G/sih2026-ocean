import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

export default defineConfig({
  plugins: [react(), cesium()],
  resolve: {
    alias: {
      // Must mirror the "paths" entry in tsconfig.json: TypeScript resolves
      // the alias for typechecking, but the bundler needs it independently.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so the backend CORS allow-list stays tight.
      //
      // The port is overridable because 8000 is a popular default and another
      // service can already hold it. Proxying into whatever happens to answer
      // on 8000 fails as a wall of 404s that look like frontend bugs, so make
      // the target explicit rather than assumed:
      //   VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: { target: "es2020", chunkSizeWarningLimit: 4000 },
});
