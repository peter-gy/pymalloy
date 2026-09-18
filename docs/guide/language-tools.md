# Check and inspect Malloy source

```python
import pymalloy as pm
from pymalloy.analysis import SourcePosition, to_dict

report = pm.check("run: missing", path="draft.malloy")
print(to_dict(report))
model = pm.model("run: duckdb.sql('SELECT 42 AS answer') -> { select: answer }")
inspection = model.inspect(position=SourcePosition(line=0, character=5))
```

Reports expose generated, typed records for diagnostics, symbols, imports,
tables, query descriptors, completions, and model schemas. Python fields use
snake case. TypeScript fields use camel case. `to_dict` produces detached Python
records for JSON output while preserving user-authored dictionary keys.

Positions are zero-based code-point offsets. `path` establishes source identity
and the base for imports. `syntax_only=True` checks syntax before imports or
schemas are requested. Pass `data_root`, `database`, or `connection` to configure semantic checking.

`model.inspect()` includes givens, annotations, dependencies, and upstream model
schemas. A position also requests its reference and import target. Pass `url=`
to inspect a captured imported document.

```sh
pymalloy check examples/orders.malloy --data-root examples --json
pymalloy format examples/orders.malloy --check
```

TypeScript compiler-only tools are available from
`@malloy-runtime/compiler/tooling`. `formatSource(text)` uses Malloy's
experimental formatter and returns source plus diagnostics.
