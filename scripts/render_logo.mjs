/* Render frontend/assets/logo.svg to a PNG.
 *
 * Submission forms and app stores want a raster square; the SVG is the source of truth
 * and this keeps the PNG reproducible from it rather than hand-exported once and then
 * silently out of date. Chromium is already a dev dependency for the browser tests, so
 * this adds nothing to install.
 *
 *   node scripts/render_logo.mjs [size]        # default 1024
 */
import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const size = Number(process.argv[2] || 1024);
const svg = readFileSync(join(root, "frontend/assets/logo.svg"), "utf8");

// Same pinned binary the browser tests use: the bundled headless shell is not
// installed in this environment, and letting Playwright pick would fail here.
const EXE = "/root/.cache/ms-playwright/chromium-1148/chrome-linux/chrome";
const browser = await chromium.launch({
  headless: true, executablePath: EXE,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage({ viewport: { width: size, height: size },
                                     deviceScaleFactor: 1 });
// omitBackground keeps the rounded corners transparent instead of white.
await page.setContent(
  `<body style="margin:0">${svg.replace(/width="512" height="512"/,
     `width="${size}" height="${size}"`)}</body>`);
const png = await page.screenshot({ omitBackground: true });
await browser.close();

const out = join(root, "frontend/assets/logo.png");
writeFileSync(out, png);
console.log(`wrote ${out} (${size}x${size}, ${(png.length / 1024).toFixed(1)}K)`);
