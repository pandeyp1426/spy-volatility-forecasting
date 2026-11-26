import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  base: "/spy-volatility-forecasting/",
  plugins: [react()],
  test: { include: ["src/**/*.test.{ts,tsx}"] },
});
