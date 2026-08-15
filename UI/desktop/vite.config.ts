import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  resolve: {
    // Workspace peers: force one copy of the UI runtime shared with
    // @zebra-agent/task-ui so the bundle does not duplicate antd/react.
    dedupe: [
      "react",
      "react-dom",
      "@ant-design/icons",
      "@ant-design/x",
      "@ant-design/x-markdown",
      "antd",
      "antd-style",
      "clsx",
    ],
  },
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: ["es2020", "chrome105", "safari13"],
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
