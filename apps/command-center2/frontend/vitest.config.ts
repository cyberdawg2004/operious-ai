import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: { environment: "jsdom", setupFiles: ["./test/setup.ts"] },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
      react: path.resolve(__dirname, "../../../node_modules/react"),
      "react-dom": path.resolve(__dirname, "../../../node_modules/react-dom"),
    },
  },
});
