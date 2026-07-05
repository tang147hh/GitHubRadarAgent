import { chromium } from "playwright";

function parseArgs(argv) {
  const args = {
    width: 1440,
    height: 1000,
    target: "page",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--url") args.url = value;
    if (key === "--out") args.out = value;
    if (key === "--width") args.width = Number(value);
    if (key === "--height") args.height = Number(value);
    if (key === "--target") args.target = value;
    if (key.startsWith("--")) index += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
if (!args.url || !args.out) {
  console.error("Usage: node capture_page.mjs --url <url> --out <path> [--width 1440] [--height 1000]");
  process.exit(2);
}

let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: {
      width: Number.isFinite(args.width) ? args.width : 1440,
      height: Number.isFinite(args.height) ? args.height : 1000,
    },
    deviceScaleFactor: 1,
  });
  await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: 30000 });
  try {
    await page.waitForLoadState("networkidle", { timeout: 10000 });
  } catch {
    // Some pages keep long-lived connections open; a DOM-ready screenshot is still useful.
  }
  await page.addStyleTag({
    content: `
      cookie-consent, [data-testid*="cookie"], .js-cookie-consent,
      .cookie, .flash, .Popover-message, .Overlay,
      [role="dialog"], [aria-modal="true"] {
        display: none !important;
        visibility: hidden !important;
      }
    `,
  }).catch(() => undefined);
  let captured = false;
  if (args.target === "readme") {
    const selectors = ["#readme", "[data-testid='readme']", "article.markdown-body", ".Box .markdown-body"];
    for (const selector of selectors) {
      const locator = page.locator(selector).first();
      if (await locator.count()) {
        await locator.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => undefined);
        await locator.screenshot({ path: args.out, timeout: 15000 });
        captured = true;
        break;
      }
    }
  }
  if (!captured) await page.screenshot({ path: args.out, fullPage: false });
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
} finally {
  if (browser) await browser.close();
}
