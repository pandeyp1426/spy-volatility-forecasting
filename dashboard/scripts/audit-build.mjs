import { readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import assert from "node:assert/strict";
import { manifestSchema, envelope, schemas } from "../src/types/public.ts";
const dir = "dist/data",
  manifest = manifestSchema.parse(
    JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8")),
  );
assert.deepEqual(readdirSync("dist").sort(), [
  "assets",
  "data",
  "index.html",
  "lab.svg",
]);
assert.deepEqual(
  readdirSync(dir).sort(),
  [...Object.keys(schemas), "manifest"].map((k) => k + ".json").sort(),
);
for (const [key, entry] of Object.entries(manifest.datasets)) {
  assert.equal(entry.file, key + ".json");
  const bytes = readFileSync(join(dir, entry.file));
  assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
  const doc = envelope.parse(JSON.parse(bytes));
  assert.equal(doc.dataset, key);
  assert.equal(doc.generated_at, manifest.generated_at);
  assert.equal(doc.status, entry.status);
  const data = schemas[key].parse(doc.data);
  if (["market", "market_preview", "observations"].includes(key))
    assert(data.rows.every((r) => r.date <= "2025-12-31"));
}
const forbidden =
  /(?:[a-z]:[\\/]+Users[\\/]|\/Users\/[^/\s]+\/|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|github_pat_[a-zA-Z0-9_]{30,}|gh[pousr]_[a-zA-Z0-9]{30,}|journal\.sqlite3)/i;
function scan(path) {
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const name = join(path, entry.name);
    assert(!entry.isSymbolicLink());
    if (entry.isDirectory()) scan(name);
    else if (/\.(?:js|css|html|json|svg)$/.test(name))
      assert(
        !forbidden.test(readFileSync(name, "utf8")),
        "Private content detected in " + name,
      );
    else
      assert(
        /\.(?:woff2?|ttf)$/.test(name),
        "Unexpected published asset " + name,
      );
  }
}
scan("dist");
console.log(
  "Verified public schemas, release hashes, historical date boundaries and static asset inventory.",
);
