import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";

const baseName = process.env.BASE_PATH?.trim().replace(/^\/+|\/+$/g, "");
const sections = [
  {
    text: "Start",
    items: [
      { text: "What is PyMalloy?", link: "/guide/overview" },
      { text: "Your first widget", link: "/guide/getting-started" },
      { text: "Run queries from Python", link: "/guide/headless-python" },
      { text: "Concepts and boundaries", link: "/guide/concepts" },
    ],
  },
  {
    text: "Guides",
    items: [
      { text: "Author and validate models", link: "/guide/authoring" },
      { text: "Reuse models and select queries", link: "/guide/models" },
      { text: "Connect files, tables, and Python data", link: "/guide/data" },
      { text: "Parameterize queries with givens", link: "/guide/givens" },
      { text: "Check and inspect Malloy source", link: "/guide/language-tools" },
      { text: "Capture Python data", link: "/guide/dataframes" },
      { text: "Bundle models and inputs", link: "/guide/bundles" },
      { text: "Export notebooks", link: "/guide/export" },
      { text: "Update widget inputs and read results", link: "/guide/widget" },
      { text: "Troubleshooting", link: "/guide/troubleshooting" },
    ],
  },
  {
    text: "Reference",
    items: [
      { text: "Python widget API", link: "/reference/python" },
      { text: "Headless Python API", link: "/reference/headless" },
      { text: "Analysis records", link: "/reference/analysis" },
      { text: "Python authoring API", link: "/reference/authoring" },
      { text: "Browser JavaScript API", link: "/reference/browser" },
      { text: "Node API", link: "/reference/node" },
      { text: "Compiler API", link: "/reference/core" },
      { text: "Export API", link: "/reference/export" },
      { text: "CLI", link: "/reference/cli" },
    ],
  },
];

export default defineConfig({
  title: "PyMalloy",
  description:
    "Author, check, run, and share Malloy models from Python. Use browser widgets, captured dataframe inputs, source bundles, and notebook exports.",
  lang: "en-US",
  srcDir: "../../docs",
  base: baseName ? `/${baseName}/` : "/",
  cleanUrls: true,
  sitemap: { hostname: "https://peter-gy.github.io/pymalloy/" },
  themeConfig: {
    socialLinks: [{ icon: "github", link: "https://github.com/peter-gy/pymalloy" }],
    editLink: { pattern: "https://github.com/peter-gy/pymalloy/edit/main/docs/:path" },
    nav: [
      { text: "Start", link: "/guide/overview" },
      { text: "Guides", items: sections[1].items },
      { text: "Reference", items: sections[2].items },
    ],
    sidebar: sections,
    search: { provider: "local" },
    outline: [2, 3],
  },
  vite: {
    publicDir: fileURLToPath(new URL("../public", import.meta.url)),
    server: {
      host: "127.0.0.1",
      port: Number(process.env.PORT ?? 4173),
      strictPort: true,
    },
  },
});
