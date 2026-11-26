import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./browser",
  workers: 1,
  retries: 0,
  timeout: 45_000,
  use: {
    baseURL: "http://127.0.0.1:4187/spy-volatility-forecasting/",
    channel: process.platform === "win32" ? "msedge" : undefined,
    viewport: { width: 1440, height: 980 },
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 4187 --strictPort",
    url: "http://127.0.0.1:4187/spy-volatility-forecasting/",
    reuseExistingServer: false,
    timeout: 45_000,
  },
});
