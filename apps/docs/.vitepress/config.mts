import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";

const baseName = process.env.BASE_PATH?.trim().replace(/^\/+|\/+$/g, "");
const sections = [
  {
    text: "Start",
    items: [
      { text: "Run your first Python query", link: "/guide/getting-started" },
      { text: "Concepts and boundaries", link: "/guide/concepts" },
    ],
  },
  {
    text: "Guides",
    items: [
      { text: "Author and validate a model", link: "/guide/authoring" },
      { text: "Edit an existing model", link: "/guide/editing" },
      { text: "Run queries from Python", link: "/guide/running" },
      { text: "Connect files and catalog tables", link: "/guide/data" },
      { text: "Parameterize queries with givens", link: "/guide/givens" },
      { text: "Capture Python data", link: "/guide/dataframes" },
      { text: "Bundle models and inputs", link: "/guide/bundles" },
      { text: "Export notebooks", link: "/guide/export" },
      { text: "Show and update a widget", link: "/guide/widget" },
      { text: "Inspect models in notebooks", link: "/guide/notebook-editing" },
      { text: "Troubleshooting", link: "/guide/troubleshooting" },
    ],
  },
  {
    text: "Reference",
    items: [
      { text: "Python API", link: "/reference/python" },
      { text: "Python runtime API", link: "/reference/runtime" },
      { text: "Widget API", link: "/reference/widget" },
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
      { text: "Start", link: "/guide/getting-started" },
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
