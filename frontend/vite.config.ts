/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";
import react from "@vitejs/plugin-react";
import svgr from "vite-plugin-svgr";
import { fileURLToPath } from "node:url";

// https://vite.dev/config/
import path from "node:path";
import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
const dirname = typeof __dirname !== "undefined" ? __dirname : path.dirname(fileURLToPath(import.meta.url));

// More info at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon
export default defineConfig(({ mode }) => {
  // Load env from parent directory (where .env is located)
  const env = loadEnv(mode, path.resolve(dirname, ".."), "");

  // Extract port from FRONTEND_HOST (e.g., "http://localhost:5173" -> 5173)
  const frontendPort = env.FRONTEND_HOST ? parseInt(new URL(env.FRONTEND_HOST).port) || 5173 : 5173;

  return {
    plugins: [react(), svgr(), tsconfigPaths()],
    server: {
      port: frontendPort,
      proxy: {
        "/api": {
          target: env.BACKEND_HOST || "http://localhost:8000",
          changeOrigin: true,
          ws: true, // forward WebSocket upgrades (Monitor training socket)
          timeout: 600_000, // 10 min — match XHR timeout
        },
      },
    },
    test: {
      projects: [
        {
          extends: true,
          test: {
            name: "unit",
            include: ["src/**/__tests__/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
            environment: "node",
          },
        },
        {
          extends: true,
          plugins: [
            // The plugin will run tests for the stories defined in your Storybook config
            // See options at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon#storybooktest
            storybookTest({
              configDir: path.join(dirname, ".storybook"),
            }),
          ],
          test: {
            name: "storybook",
            browser: {
              enabled: true,
              headless: true,
              provider: "playwright",
              instances: [
                {
                  browser: "chromium",
                },
              ],
            },
            setupFiles: [".storybook/vitest.setup.ts"],
          },
        },
      ],
    },
  };
});
