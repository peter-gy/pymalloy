# Bundle notice sources

These npm packages omit license text from their published tarballs. The notice
builder uses the upstream license at the npm release's `gitHead`, selected by
exact package name and version. Updating either package requires verifying its
new release provenance and license text.

| npm release                          | npm `gitHead`                              | License source                                                                                                  |
| ------------------------------------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `@duckdb/duckdb-wasm@1.33.1-dev57.0` | `ef8a4f8912b6e7f62bc0cc490145ebd391b79e1f` | [upstream LICENSE](https://github.com/duckdb/duckdb-wasm/blob/ef8a4f8912b6e7f62bc0cc490145ebd391b79e1f/LICENSE) |
| `@malloydata/motly-ts-parser@0.9.0`  | `f5db040f97fe211a0d4a182ea6793792505d70ef` | [upstream LICENSE](https://github.com/malloydata/motly/blob/f5db040f97fe211a0d4a182ea6793792505d70ef/LICENSE)   |

Provenance is available through `pnpm view '<package>@<version>' gitHead`.
