import { expect, test } from "./fixture";

test("marimo controls update the widget and reactive Python readback", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const analysis = page.getByRole("region", { name: "Malloy query", exact: true }).first();
  await expect(page.getByRole("heading", { name: "Sales analysis", exact: true })).toBeVisible();
  await expect(analysis.getByRole("cell", { name: "42", exact: true })).toBeVisible();
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 42}]");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await expect(analysis.getByRole("table")).toContainText("30");
  await expect(page.getByText("Rows:", { exact: false })).toHaveText("Rows: [{'revenue': 30}]");

  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).check();
  await expect(analysis.getByRole("alert")).toContainText("missing_source");
  await expect(page.getByText("Python received: error", { exact: false })).toBeVisible();
  await page.getByRole("checkbox", { name: "Use an invalid model", exact: true }).uncheck();
  await expect(analysis.getByRole("table")).toContainText("30");
  await expect(page.getByText("Python received: ready", { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(analysis.getByRole("table")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("marimo-mobile.png"), fullPage: true });
});

test("marimo cell outputs inspect grammar and preview a bound native query", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const views = page.getByRole("region", { name: "Malloy query", exact: true });
  await expect(views).toHaveCount(4);
  const expression = views.nth(1);
  await expect(expression.getByLabel("Malloy source", { exact: true })).toHaveText("amount.sum()");
  await expression.getByRole("tab", { name: "Context", exact: true }).click();
  await expect(expression.getByLabel("Referenced fields and sources")).toHaveText("amount");
  const draft = views.nth(2);
  await expect(draft.getByRole("status")).toHaveText("Ready to inspect");
  await draft.getByRole("button", { name: "Check", exact: true }).click();
  await expect(draft.getByRole("status")).toHaveText("Checked");
  await draft.getByRole("button", { name: "Run", exact: true }).click();
  await expect(draft.getByRole("table")).toContainText("42");
  const native = views.nth(3);
  await native.getByRole("button", { name: "Check", exact: true }).click();
  await expect(native.getByRole("status")).toHaveText("Checked");
  await native.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(native.getByRole("table")).toContainText("9,007,199,254,740,993");
  await expect(native.getByRole("status")).toHaveText("1 row");
  await native.getByRole("tab", { name: "Schema", exact: true }).click();
  await expect(native.getByLabel("Model schemas")).toBeVisible();
  const previous = await expression.elementHandle();
  if (!previous) throw new Error("Expression view must be mounted before changing its input");
  await page.getByRole("combobox", { name: "Region", exact: true }).selectOption("South");
  await previous.waitForElementState("hidden");
  await expect(views).toHaveCount(4);
  await expression.getByRole("tab", { name: "Context", exact: true }).click();
  await expect(expression).toContainText("Booked amount in USD for South.");
  await page.setViewportSize({ width: 390, height: 844 });
  await native.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("notebook-inspector-mobile.png"),
    fullPage: true,
  });
});

test.describe("notebook presentation", () => {
  test.use({ hasTouch: true });
  test("inspector controls support keyboard, host styles, dark mode and reflow", async ({
    page,
  }, testInfo) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const draft = page.getByRole("region", { name: "Malloy query", exact: true }).nth(2);
    const check = draft.getByRole("button", { name: "Check", exact: true });
    await expect(check).toBeVisible();
    const before = await check.evaluate((element) => getComputedStyle(element).padding);
    const hostile = await page.addStyleTag({ content: "button { padding: 80px !important; }" });
    expect(await check.evaluate((element) => getComputedStyle(element).padding)).toBe(before);
    await hostile.evaluate((element) => element.parentNode?.removeChild(element));
    await check.focus();
    await expect(check).toBeFocused();
    expect(await check.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
    await check.press("Enter");
    await expect(draft.getByRole("status")).toHaveText("Checked");
    await expect(draft.getByRole("table")).toHaveCount(0);
    await expect(draft.getByRole("tab", { name: "Schema", exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(draft.getByRole("img", { name: "measure", exact: true })).toBeVisible();
    const sourceTab = draft.getByRole("tab", { name: "Source", exact: true });
    await sourceTab.focus();
    await sourceTab.press("End");
    await expect(draft.getByRole("tab", { name: "Context", exact: true })).toBeFocused();
    await draft.getByRole("tab", { name: "Context", exact: true }).press("Home");
    await expect(sourceTab).toBeFocused();
    await expect(sourceTab).toHaveAttribute("aria-selected", "true");
    await expect(draft.getByLabel("Malloy source", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("inspector-light.png"), fullPage: true });
    const lightBackground = await draft.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    );
    await page.evaluate(() => {
      document.documentElement.classList.add("dark");
      document.documentElement.style.colorScheme = "dark";
      document.documentElement.dir = "rtl";
    });
    await page.setViewportSize({ width: 320, height: 844 });
    await draft.scrollIntoViewIfNeeded();
    expect(await draft.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(
      lightBackground,
    );
    const rect = await draft.boundingBox();
    expect(rect?.width).toBeLessThanOrEqual(320);
    expect(
      await check.evaluate((element) => element.getBoundingClientRect().height),
    ).toBeGreaterThanOrEqual(44);
    await expect(draft.getByLabel("Malloy source", { exact: true })).toHaveAttribute("dir", "ltr");
    await page.screenshot({
      path: testInfo.outputPath("inspector-dark-rtl-mobile.png"),
      fullPage: true,
    });
  });
});
