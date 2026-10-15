# Bundle notice sources

These npm packages omit license text from their published tarballs. The notice
builder uses the upstream license at the npm release's `gitHead`, selected by
exact package name and version. Updating either package requires verifying its
new release provenance and license text.

| npm release                          | npm `gitHead`                              | License source                                                                                                  |
| ------------------------------------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `@duckdb/duckdb-wasm@1.33.1-dev65.0` | `448ec38a52238ad2aacde514f0ee3acfd9515b6c` | [upstream LICENSE](https://github.com/duckdb/duckdb-wasm/blob/448ec38a52238ad2aacde514f0ee3acfd9515b6c/LICENSE) |
| `@malloydata/motly-ts-parser@0.9.0`  | `f5db040f97fe211a0d4a182ea6793792505d70ef` | [upstream LICENSE](https://github.com/malloydata/motly/blob/f5db040f97fe211a0d4a182ea6793792505d70ef/LICENSE)   |

`@malloydata/motly-ts-parser@0.9.1` uses the same notice as 0.9.0, verified at
release `gitHead` [a7289dab7201ec93de2e0c9e3736072605e62b7b](https://github.com/malloydata/motly/blob/a7289dab7201ec93de2e0c9e3736072605e62b7b/LICENSE).

Provenance is available through `pnpm view '<package>@<version>' gitHead`.
