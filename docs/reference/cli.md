# CLI

```sh
pymalloy check examples/orders.malloy --data-root examples --json
pymalloy format examples/orders.malloy --check
pymalloy export examples/orders.malloy --format marimo --all -o report.py
```

`check PATH` supports `--syntax-only`, `--json`, `--data-root`, and `--database`.
It exits 1 for invalid source or runtime setup failure. JSON output uses Python
field names. Diagnostic text includes source locations.

`format PATH` writes formatted source to stdout. `--check` exits 1 if formatting
would change the file. It preserves the input file.

`export MODEL --format {marimo,jupyter} -o OUTPUT` supports repeatable `--query`,
`--all`, `--profile {precompiled,server,widget}`, `--data-root`, `--database`,
`--title`, `--givens JSON`, and `--files JSON`. Output extensions must match the
format. Compilation and rendering finish before an existing output is replaced.

Server commands require `pymalloy[server]`. Marimo rendering also requires the
`marimo` extra. `--help` works with base dependencies.
