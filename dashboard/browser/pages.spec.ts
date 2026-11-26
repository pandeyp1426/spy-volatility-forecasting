import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import type { Forecast } from "../src/types/public";

const approved: Forecast[] = JSON.parse(readFileSync("public/data/forecasts.json", "utf8")).data.rows;
const latest = approved[0];

test("the public ticker keeps its dark backing and fits its card", async ({page}) => {
  await page.route("**/embed-widget/single-quote/**", route => route.fulfill({
    contentType: "text/html", body: '<body style="color:white;background:transparent">SPY quote</body>',
  }));
  await page.goto("./");
  const card = page.getByRole("region", {name: "SPY market price"});
  const ticker = card.locator("iframe");
  await expect(ticker).toHaveCSS("color-scheme", "light");
  await expect(ticker).toHaveCSS("background-color", await card.evaluate(el => getComputedStyle(el).backgroundColor));
  for (const width of [1440, 375, 320]) {
    await page.setViewportSize({width, height: 850});
    const frame = (await ticker.boundingBox())!;
    const available = await card.evaluate(el => {
      const css = getComputedStyle(el);
      return el.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
    });
    expect(Math.abs(frame.width - available)).toBeLessThan(1);
    const link = (await card.getByRole("link").boundingBox())!;
    expect(link.y).toBeGreaterThanOrEqual(frame.y + frame.height);
  }
});

test("an open tab keeps verified data through a partial release and updates on its next poll", async ({page}) => {
  const manifest = JSON.parse(readFileSync("public/data/manifest.json", "utf8"));
  manifest.generated_at = new Date(Date.parse(manifest.generated_at) + 3_600_000).toISOString();
  const files = new Map<string, string>();
  for (const [key, entry] of Object.entries(manifest.datasets) as [string, {file: string; sha256: string}][]) {
    const doc = JSON.parse(readFileSync("public/data/" + entry.file, "utf8"));
    doc.generated_at = manifest.generated_at;
    if (key === "forecasts") doc.data.rows[0].predictions_pct.ridge = 3.125;
    const body = JSON.stringify(doc);
    files.set(entry.file, body);
    entry.sha256 = createHash("sha256").update(body).digest("hex");
  }
  files.set("manifest.json", JSON.stringify(manifest));
  let phase: "original" | "partial" | "complete" = "original";
  await page.route("**/data/*.json", (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop()!;
    if (phase === "original" || (phase === "partial" && name === "forecasts.json")) return route.continue();
    return route.fulfill({contentType: "application/json", body: files.get(name)});
  });
  await page.clock.install();
  await page.goto("./", {waitUntil: "domcontentloaded"});
  const ridge = page.locator(".ridge dd");
  const original = latest.predictions_pct.ridge.toFixed(3) + "%";
  await expect(ridge).toHaveText(original);
  phase = "partial";
  await page.clock.fastForward(61_000);
  await expect(page.getByText(/release check failed/)).toBeVisible();
  await expect(ridge).toHaveText(original);
  phase = "complete";
  await page.clock.fastForward(61_000);
  await expect(ridge).toHaveText("3.125%");
  await expect(page.getByText(/release check failed/)).toHaveCount(0);
});
test("one page shows three estimates on desktop and mobile", async ({page}, info) => {
  await page.route("**/embed-widget/**", (route) => route.fulfill({body: "SPY quote", contentType: "text/plain"}));
  await page.goto("./#/forecasts");
  await expect(page.getByRole("heading", {name: "SPY volatility forecast"})).toBeVisible();
  await expect(page.locator(".estimates dd")).toHaveCount(3);
  await expect(page.locator(".ridge dd")).toHaveText(latest.predictions_pct.ridge.toFixed(3) + "%");
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await page.screenshot({path: info.outputPath("forecast-desktop.png")});
  await page.setViewportSize({width: 375, height: 812});
  await expect(page.getByText("5-session benchmark", {exact: true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({path: info.outputPath("forecast-mobile.png")});
});

test("refresh recovers a failed forecast request", async ({page}) => {
  await page.route("**/data/forecasts.json", r => r.fulfill({status: 503}));
  await page.goto("./", {waitUntil: "domcontentloaded"});
  await expect(page.getByText("The approved dataset could not be loaded or verified.")).toBeVisible();
  await page.unroute("**/data/forecasts.json");
  await page.getByRole("button", {name: "Refresh data"}).click();
  await expect(page.locator(".ridge dd")).toHaveText(latest.predictions_pct.ridge.toFixed(3) + "%");
});

test("restored research charts and model inputs use the verified release", async ({page}) => {
  await page.route("**/embed-widget/**", route => route.fulfill({body: "", contentType: "text/plain"}));
  await page.goto("./");
  const market = page.getByRole("region", {name: "Market history"});
  const performance = page.getByRole("region", {name: "Model performance"});
  await expect(market.locator(".recharts-area-curve")).toBeVisible();
  await expect(performance.locator(".recharts-bar-rectangle")).toHaveCount(5);
  await performance.getByText("Data table", {exact: true}).click();
  const history = JSON.parse(readFileSync("public/data/history.json", "utf8")).data;
  const ridge = history.performance.find((r: {method: string}) => r.method === "ridge");
  await expect(performance.getByRole("row").filter({hasText: "Ridge"})).toContainText(ridge.rmse.toFixed(4));
  await market.getByLabel("Market chart").selectOption("volatility");
  await expect(market.locator(".recharts-line-curve")).toHaveCount(3);
  await market.getByRole("button", {name: "5 sessions", exact: true}).click();
  await expect(market.locator(".recharts-line-curve")).toHaveCount(2);
  await market.getByLabel("Market chart").selectOption("returns");
  await expect(market.locator(".recharts-bar-rectangle").first()).toBeVisible();
  const analysis = performance.getByLabel("Model analysis chart");
  await analysis.selectOption("accuracy");
  await expect(performance.locator(".recharts-line-curve")).toHaveCount(2);
  await performance.getByRole("button", {name: "Signed error"}).click();
  await expect(performance.locator(".recharts-line-curve")).toHaveCount(1);
  await analysis.selectOption("uncertainty");
  await expect(performance.getByText(/paired repetitions/)).toBeVisible();
  await analysis.selectOption("sensitivity");
  await performance.getByRole("button", {name: "Both", exact: true}).click();
  await expect(performance.getByText("249 observations")).toBeVisible();
  await analysis.selectOption("offsets");
  await performance.getByRole("button", {name: "k = 2"}).click();
  await expect(performance.getByRole("button", {name: "k = 2"})).toHaveAttribute("aria-pressed", "true");
  await analysis.selectOption("spikes");
  await expect(performance.getByText("High-outcome origins")).toBeVisible();
  await page.getByText("Model inputs and forecast breakdown", {exact: true}).click();
  await expect(page.locator(".model-inputs dd")).toHaveCount(5);
  await expect(page.locator(".model-inputs dd").first()).toHaveText((100 * latest.predictors.log_return).toFixed(4) + "%");
  await expect(page.locator(".compareplot .recharts-bar-rectangle")).toHaveCount(latest.outcome ? 4 : 3);
  await page.setViewportSize({width: 375, height: 812});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("the local minute quote refreshes independently of the close forecast", async ({page}) => {
  await page.addInitScript(() => {
    const flag = document.createElement("meta");
    flag.name = "local-pilot-preview"; flag.content = "enabled";
    document.addEventListener("readystatechange", () => {
      if (document.head && !flag.isConnected) document.head.append(flag);
    });
  });
  let price = 500;
  const stamp = "2026-11-23T15:31:00Z";
  await page.route("**/local/quote.json", r => r.fulfill({json: {price, as_of: stamp, fetched_at: stamp, market_open: true, delayed: false}}));
  await page.route("**/local/pilots.json", r => r.fulfill({json: []}));
  await page.clock.install();
  await page.goto("./");
  await expect(page.locator(".quote-price")).toHaveText("$500.00");
  price = 501;
  await page.clock.fastForward(61_000);
  await expect(page.locator(".quote-price")).toHaveText("$501.00");
  await expect(page.locator(".ridge dd")).toHaveText(latest.predictions_pct.ridge.toFixed(3) + "%");
});
