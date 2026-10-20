import { expect, test } from "@playwright/test";

test("home page renders and recorded session loads without calling the API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /outdoor activity assistant/i })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /your question/i })).toBeVisible();
  await page.getByRole("button", { name: /running near powai/i }).click();
  await expect(page.getByText(/recorded session/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: /hiranandani garden/i })).toBeVisible();
  await expect(page.getByText(/openstreetmap/i).first()).toBeVisible();
});
