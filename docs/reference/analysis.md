# Analysis records

Language tools return typed Python records generated from the compiler schema:

```python
import pymalloy as pm
from pymalloy.analysis import SourcePosition, to_dict

with pm.connect() as connection:
    report = connection.check(
        "run: missing", position=SourcePosition(line=0, character=5)
    )
print(report.ok, to_dict(report.diagnostics))
```

`ParseReport` contains syntax metadata: `url`, `compiler_version`, `diagnostics`,
`symbols`, `tables`, `imports`, `completions`, and `help`. `pm.parse(source, url=..., document_kind=None)` returns this record. The optional
kind selects `"model"` or `"notebook"`, with URL-based inference when omitted.

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
`reference` and `import_` when requested. Optional record fields default to `None`.

`QueryDescriptor` contains `name`, `kind`, `location`, and `schema`. Each compiled
run or named query carries its own output schema. A query with required unbound
givens has `schema=None`. For `run:0`, `run:1`, and `run:2`, each descriptor keeps
its authored ordinal even when `run:1` requires givens. Source views and SQL
document cells resolve their output during preparation or execution.

`NativeMetadata.model` and `.sources` retain upstream Malloy schema records.
Source schemas remain available when queries require givens. Read query output
from `QueryDescriptor.schema`. The upstream model's `anonymous_queries` is empty.

Records are immutable. `to_dict(value)` converts records, mappings, and sequences
into detached dictionaries and lists. Record fields use Python names, including
tagged schema variants. Authored dictionary keys retain their spelling. Use the
same function to convert a widget's read-only state into editable containers.
Scalar values, including exact integers and decimals, retain their Python types.
JSON encoding may require a serializer for those scalar types.
