import { expect, test as base } from "@playwright/test";

export const test = base.extend<{ diagnostics: void }>({
  diagnostics: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.stack ?? error.message));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      await use();
      expect(errors, "Browser errors").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };
