import { createServer } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, extname } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const dashboard = fileURLToPath(new URL("../", import.meta.url));
const privateRows = join(dashboard, "../artifacts/dashboard_pilot");
const base = "/spy-volatility-forecasting/";
const port = Number(process.argv[2] ?? 4173);
const project = join(dashboard, "..");
const python = join(project, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const execute = promisify(execFile);
let quoteRequest, quoteExpires = 0;
function marketQuote() {
  if (!quoteRequest || Date.now() >= quoteExpires) {
    quoteExpires = Date.now() + 60_000;
    quoteRequest = execute(python, ["-m", "spy_volatility.workflows.dashboard_quote"], {
      cwd: project, timeout: 25_000, windowsHide: true,
    }).then(({ stdout }) => JSON.stringify(JSON.parse(stdout)));
  }
  return quoteRequest;
}
const mime = { ".css": "text/css", ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf" };
const datasets = /^data\/(manifest|market|market_preview|history|observations|forecasts|status)\.json$/;
const assets = /^assets\/[a-zA-Z0-9_.-]+\.(js|css|woff2?|ttf|svg)$/;

async function pilots() {
  let names;
  try {
    names = await readdir(privateRows, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return "[]";
    throw error;
  }
  const rows = names.filter((f) => f.isFile() && /^2026-\d\d-\d\d\.json$/.test(f.name));
  return JSON.stringify(await Promise.all(rows.map(async (f) => JSON.parse(await readFile(join(privateRows, f.name), "utf8")))));
}

createServer(async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  if (!["GET", "HEAD"].includes(req.method) || ![`127.0.0.1:${port}`, `localhost:${port}`].includes(req.headers.host) ||
      !req.url.startsWith(base)) {
    res.writeHead(404).end();
    return;
  }
  const name = req.url.slice(base.length).split("?")[0];
  let type = mime[extname(name)];
  try {
    let body;
    if (!name || name === "index.html") {
      type = mime[".html"];
      const html = await readFile(join(dashboard, "dist/index.html"), "utf8");
      body = html.replace("</head>", '<meta name="local-pilot-preview" content="enabled"></head>');
    } else if (name === "local/pilots.json") {
      body = await pilots();
    } else if (name === "local/quote.json") {
      body = await marketQuote();
    } else if (datasets.test(name)) {
      body = await readFile(join(dashboard, "public", name));
    } else if (name === "lab.svg" || assets.test(name)) {
      body = await readFile(join(dashboard, "dist", name));
    } else {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "Content-Type": type }).end(req.method === "HEAD" ? undefined : body);
  } catch (error) {
    res.writeHead(error.code === "ENOENT" ? 404 : 503).end();
  }
}).listen(port, "127.0.0.1", () => console.log(`Local pilot dashboard: http://127.0.0.1:${port}${base}`));
