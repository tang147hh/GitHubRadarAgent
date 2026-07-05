import { readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

function parseArgs(argv) {
  const args = {
    width: 1200,
    height: 720,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--svg") args.svg = value;
    if (key === "--out") args.out = value;
    if (key === "--width") args.width = Number(value);
    if (key === "--height") args.height = Number(value);
    if (key.startsWith("--")) index += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
if (!args.svg || !args.out) {
  console.error("Usage: node render_svg.mjs --svg <path> --out <path> [--width 1200] [--height 720]");
  process.exit(2);
}

let browser;
try {
  const svg = await readFile(args.svg, "utf8");
  const width = Number.isFinite(args.width) ? args.width : 1200;
  const height = Number.isFinite(args.height) ? args.height : 720;
  const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {
        width: ${width}px;
        height: ${height}px;
        margin: 0;
        overflow: hidden;
        background: white;
      }
      svg {
        display: block;
        width: ${width}px;
        height: ${height}px;
      }
    </style>
  </head>
  <body>${svg}</body>
</html>`;

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 1,
  });
  await page.setContent(html, {
    waitUntil: "load",
    baseURL: `file://${dirname(fileURLToPath(import.meta.url))}/`,
  });
  await page.screenshot({ path: args.out, fullPage: false });
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
} finally {
  if (browser) await browser.close();
}
