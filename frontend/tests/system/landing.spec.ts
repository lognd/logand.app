import { test, expect } from "@playwright/test";

test("landing page renders real content", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toHaveText("Logan Dapp");
});
