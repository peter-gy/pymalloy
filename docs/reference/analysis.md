# Analysis records

Language tools return typed Python records generated from the compiler schema:

```python
import pymalloy as pm
from pymalloy.analysis import SourcePosition, to_dict

report = pm.check("run: missing", position=SourcePosition(line=0, character=5))
print(report.ok, to_dict(report.diagnostics))
```

`ParseReport` contains syntax metadata: `url`, `diagnostics`, `symbols`, `tables`,
`imports`, `completions`, and `help`. `pm.parse(source, url=...)` returns this record.

`MarkdownCell(text=...)` and `QueryCell(name=..., sql=...)` form the `DocumentCell`
union returned by `model.document()`. Use `isinstance` to distinguish the cell
types, or `to_dict` to obtain their tagged JSON shape.

`CheckReport` contains `url`, `compiler_version`, `ok`, `diagnostics`, `symbols`,
`tables`, `imports`, `completions`, `help`, `queries`, and `model`.

`Diagnostic` contains `code`, `severity`, `message`, `location`, `replacement`,
`error_tag`, and `data`. Source locations contain a URL and a start/end range.
Coordinates are zero-based code-point offsets. `SourcePosition` uses named
`line` and `character` fields.

`Inspection` contains typed givens, annotations, dependencies, imports, queries,
diagnostics and upstream model schemas. Positional inspection also includes
`reference` and `import_` when requested. Optional fields may be absent.

`QueryDescriptor` contains `name`, `kind`, and `location`. `NativeMetadata.model`
and `.sources` retain upstream Malloy schema records. Required givens may defer
the whole-model schema while source schemas remain available.

Records are immutable. `to_dict(record)` returns detached Python field names,
including tagged schema variants. Authored dictionary keys retain their spelling.
