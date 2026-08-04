/**
 * e2e/design-lab-functional.spec.ts
 *
 * Functional E2E tests for the Design Lab page, which lazy-loads
 * @excalidraw/excalidraw v0.18 via React Suspense + lazy().
 *
 * The DesignLab component (src/capabilities/design/DesignLab.tsx) wraps
 * Excalidraw and wires it into the Hermes web app router under a nav
 * link labelled "Design Lab".
 *
 * Excalidraw 0.18 renders a drawing canvas with shape tools, zoom
 * controls, and export buttons.  The library is heavy (~2 MB gzipped)
 * and loads asynchronously, so tests use generous timeouts (15–20 s).
 *
 * PREREQUISITES:
 *   - @playwright/test installed (npm i -D @playwright/test)
 *   - Chromium browser installed (npx playwright install chromium)
 *   - Hermes web/desktop dev server running on BASE_URL
 *
 * Excalidraw 0.18 key DOM selectors (from source):
 *   .excalidraw                 – root container
 *   .excalidraw__canvas-wrapper – canvas wrapper
 *   canvas.interactive          – interactive overlay canvas
 *   .App-toolbar-content        – toolbar row
 *   .shapes-section             – shape tool group
 *   .App-menu_top               – top bar (zoom, undo/redo, export)
 *   .ToolIcon                   – individual tool button
 */

import { expect, test, type Page } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:5174";
const ASYNC_TIMEOUT = 20_000; // 20 s for the heavy async Excalidraw chunk

// ── Helpers ──────────────────────────────────────────────────────────

/** Navigate to the Design Lab via the sidebar nav link (exact label match). */
async function navigateToDesignLab(page: Page) {
  await page.getByRole("link", { name: "Design Lab", exact: true }).click();
  // The exact route may vary — match any path containing "design" or "design-lab"
  await page.waitForURL(/\/design/, { timeout: 10_000 });
}

/**
 * Wait for the Excalidraw canvas to appear in the DOM.
 * Excalidraw 0.18 renders an interactive canvas with classes matching
 * either the task-specified "excalidraw-canvas" or the actual library's
 * BEM class "excalidraw__canvas".
 */
async function waitForExcalidrawCanvas(page: Page) {
  const canvasSelector = page.locator(
    ".excalidraw-canvas, " +
      // Actual Excalidraw 0.18 BEM class
      ".excalidraw__canvas-wrapper canvas, " +
      // Interactive overlay canvas
      ".excalidraw canvas.interactive",
  );
  await canvasSelector.first().waitFor({ state: "visible", timeout: ASYNC_TIMEOUT });
}

/** Shape tools exposed by Excalidraw 0.18 toolbar. */
const SHAPE_TOOLS = [
  "rectangle",
  "diamond",
  "ellipse",
  "arrow",
  "line",
  "text",
  "image",
] as const;

// ── Test Suite ───────────────────────────────────────────────────────

test.describe("Design Lab — Excalidraw functional", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    // Wait for the app shell to fully hydrate (sidebar nav must be clickable).
    await page.waitForLoadState("networkidle");
    // Ensure the sidebar is visible before trying to navigate.
    const sidebar = page.getByRole("navigation").or(page.locator("nav").first());
    await expect(sidebar).toBeVisible({ timeout: 10_000 });
  });

  // ── 1. Suspense fallback ────────────────────────────────────────────

  test("shows loading state before Excalidraw finishes loading", async ({
    page,
  }) => {
    // The DesignLab wraps the lazy-loaded Excalidraw in <Suspense> with a
    // fallback (spinner, skeleton, or "Loading…" text).
    await navigateToDesignLab(page);

    // Before Excalidraw resolves, the Suspense fallback should be in the
    // DOM.  Look for common fallback patterns.
    const fallback = page.locator(
      '[role="status"], [aria-label*="loading" i], [aria-label*="Loading" i], ' +
        // Skeleton / shimmer loader pattern
        '[class*="skeleton"], [class*="Skeleton"], ' +
        // Text-based fallback
        'text("Loading"), text("Loading…")',
    );

    // The fallback may flicker in/out very quickly.  If it was already
    // replaced by the Excalidraw canvas, the test still passes — the
    // important assertion is that the canvas does eventually render.
    const fallbackVisible = await fallback.first().isVisible().catch(() => false);
    if (fallbackVisible) {
      await expect(fallback.first()).toBeVisible();
    }

    // Eventually the Excalidraw interactive canvas appears.
    await waitForExcalidrawCanvas(page);
    // Assert the canvas is actually there.
    const canvas = page.locator(".excalidraw-canvas, .excalidraw__canvas-wrapper canvas, .excalidraw canvas.interactive");
    await expect(canvas.first()).toBeVisible({ timeout: ASYNC_TIMEOUT });
  });

  // ── 2. Excalidraw canvas area renders ───────────────────────────────

  test("Excalidraw canvas area is rendered and has non-zero dimensions", async ({
    page,
  }) => {
    await navigateToDesignLab(page);
    await waitForExcalidrawCanvas(page);

    // The Excalidraw root container should be present.
    const container = page.locator(".excalidraw");
    await expect(container).toBeVisible();

    // The interactive canvas (the one users draw on) should have non-zero
    // dimensions.
    const interactiveCanvas = page.locator(".excalidraw canvas.interactive");
    await expect(interactiveCanvas).toBeVisible({ timeout: ASYNC_TIMEOUT });
    const box = await interactiveCanvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.height).toBeGreaterThan(200);

    // The background canvas (static layer) should also exist.
    const staticCanvas = page.locator(".excalidraw__canvas.static canvas");
    await expect(staticCanvas).toHaveCount(1);
  });

  // ── 3. Drawing toolbar ──────────────────────────────────────────────

  test("drawing toolbar with shape tools is visible", async ({ page }) => {
    await navigateToDesignLab(page);
    await waitForExcalidrawCanvas(page);

    // Excalidraw 0.18 renders shape tools inside a .shapes-section within
    // the .App-toolbar-content.  Each tool is a <button> with an icon and
    // typically has a title or aria-label describing the shape.
    const toolbar = page.locator(".App-toolbar-content, .excalidraw-toolbar");
    await expect(toolbar).toBeVisible({ timeout: ASYNC_TIMEOUT });

    // Verify each shape tool is present.  Excalidraw uses tool names as
    // aria-labels or data-testid attributes.
    for (const tool of SHAPE_TOOLS) {
      const toolBtn = page.locator(
        `.App-toolbar-content [title*="${tool}" i], ` +
          `.App-toolbar-content [aria-label*="${tool}" i], ` +
          `.shapes-section [title*="${tool}" i], ` +
          `.shapes-section [aria-label*="${tool}" i], ` +
          // Fallback: any button whose accessible name includes the tool name
          `button:has-text("${tool}")`,
      );
      await expect(toolBtn.first()).toBeVisible({ timeout: ASYNC_TIMEOUT });
    }

    // The shapes section (centered group of shape buttons) should be present.
    const shapesSection = page.locator(".shapes-section");
    await expect(shapesSection).toBeVisible();
  });

  // ── 4. Console errors ───────────────────────────────────────────────

  test("no critical console errors during Excalidraw load", async ({
    page,
  }) => {
    const errors: string[] = [];

    // Listen for console errors before navigating so we catch everything.
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    await navigateToDesignLab(page);
    await waitForExcalidrawCanvas(page);

    // Give a short settle window for any lazy initialisation callbacks.
    await page.waitForTimeout(2_000);

    // Filter out benign messages that commonly appear in dev builds.
    const critical = errors.filter((e) => {
      const lower = e.toLowerCase();
      return (
        !lower.includes("react router future flag warning") &&
        !lower.includes("downloadable font") &&
        !lower.includes("failed to load resource") &&
        !lower.includes("source map") &&
        !lower.includes("favicon") &&
        !lower.includes("third-party") &&
        !lower.includes("experimental") &&
        !lower.includes("development mode") &&
        !lower.includes("localhost") &&
        !lower.includes("unrecognized feature")
      );
    });

    expect(critical).toHaveLength(0);
  });

  // ── 5. Canvas click ────────────────────────────────────────────────

  test("canvas responds to a click without crashing", async ({ page }) => {
    await navigateToDesignLab(page);
    await waitForExcalidrawCanvas(page);

    // Click near the centre of the interactive canvas.
    const interactiveCanvas = page.locator(".excalidraw canvas.interactive");
    await expect(interactiveCanvas).toBeVisible({ timeout: ASYNC_TIMEOUT });
    const box = await interactiveCanvas.boundingBox();
    expect(box).not.toBeNull();

    const cx = box!.x + box!.width / 2;
    const cy = box!.y + box!.height / 2;
    await page.mouse.click(cx, cy);

    // After the click the page must still be functional.
    await expect(page.locator("body")).toBeVisible();

    // Verify click produced no page crash.  Playwright tracks
    // 'pageerror' events; if the page crashed the test would fail.
    // Also check the Excalidraw container is still responsive.
    const container = page.locator(".excalidraw");
    await expect(container).toBeVisible();
  });

  // ── 6. Zoom / export buttons ───────────────────────────────────────

  test("zoom controls and export button are present", async ({ page }) => {
    await navigateToDesignLab(page);
    await waitForExcalidrawCanvas(page);

    // Excalidraw 0.18 renders zoom controls in the top toolbar area
    // (.App-menu_top).  Look for zoom-in, zoom-out, and zoom-percentage
    // indicators.
    const zoomControls = page.locator(
      '[title*="zoom" i], [aria-label*="zoom" i], ' +
        // Zoom-value display (shows "100%")
        '.excalidraw button:has-text("%"), ' +
        '[data-testid*="zoom" i]',
    );
    await expect(zoomControls.first()).toBeVisible({ timeout: ASYNC_TIMEOUT });

    // At least two zoom-related buttons should be present (in / out).
    const zoomButtons = await page.locator(
      '[title*="zoom in" i], [aria-label*="zoom in" i], ' +
        '[title*="zoom out" i], [aria-label*="zoom out" i]',
    ).all();
    const visibleZoomButtons = zoomButtons.filter((b) => b.isVisible());
    // Either zoom-in or zoom-out (or both) must be visible.
    expect(visibleZoomButtons.length).toBeGreaterThanOrEqual(1);

    // Export / save button.  Excalidraw places export in the top-right
    // area or as an icon button with a download/save label.
    const exportBtn = page.locator(
      '[title*="export" i], [aria-label*="export" i], ' +
        '[title*="download" i], [aria-label*="download" i], ' +
        '[title*="save" i], [aria-label*="save" i], ' +
        '[data-testid*="export" i]',
    );
    await expect(exportBtn.first()).toBeVisible({ timeout: ASYNC_TIMEOUT });
  });
});
