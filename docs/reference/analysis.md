# Analysis records

`pymalloy.analysis` exports frozen records from the
[Malloy](https://docs.malloydata.dev/documentation/) compiler contract. Malloy
supplies symbols, diagnostics, and resolved model metadata.

```python
import pymalloy as pm
from pymalloy.analysis import SourcePosition, to_dict

with pm.connect() as con:
    report = con.check("run: missing", position=SourcePosition(line=0, character=5))
assert not report.ok
assert report.diagnostics
print(to_dict(report.diagnostics)[0]["severity"])
```

The print is `error`. `to_dict(value)` converts records, mappings, and sequences
to detached dictionaries and lists. It preserves Python scalar values, including
exact integers and decimals, and preserves authored dictionary keys. Choose a
scalar encoder when writing JSON.

## Record construction and shapes

Records use keyword-only fields. Sequence fields are tuples, including nested
record sequences. Optional values use `None`. Supply nonnegative integers for
source positions and spans. Code-point positions count Unicode characters
rather than JavaScript UTF-16 units. Ranges and spans have exclusive ends.

| Qualified record                     | Fields and contract                                                                                                                |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `pymalloy.analysis.SourcePosition`   | `line: int`, `character: int`, both zero-based                                                                                     |
| `pymalloy.analysis.SourceRange`      | `start: SourcePosition`, `end: SourcePosition`                                                                                     |
| `pymalloy.analysis.SourceLocation`   | `url: str`, `range: SourceRange`                                                                                                   |
| `pymalloy.analysis.SourceSpan`       | `start: int`, `end: int`, absolute code-point offsets                                                                              |
| `pymalloy.analysis.Diagnostic`       | `code`, `severity` (`error`, `warning`, `debug`), `message`, nullable `location`, `replacement`, `error_tag`, and arbitrary `data` |
| `pymalloy.analysis.SymbolInfo`       | `name`, `type`, `range`, `lens_range`, `children: tuple[SymbolInfo, ...]`                                                          |
| `pymalloy.analysis.Table`            | `connection`, `path`, `range`, describing an authored table reference                                                              |
| `pymalloy.analysis.ImportInfo`       | Resolved `url` and authored statement `location`                                                                                   |
| `pymalloy.analysis.ParsedImport`     | `url`, `location`, and `reference: SourceSpan` locating the quoted import URL including delimiters                                 |
| `pymalloy.analysis.Completion`       | `type: str`, `text: str`                                                                                                           |
| `pymalloy.analysis.Help`             | `type: str`, `token: str \| None`                                                                                                  |
| `pymalloy.analysis.AnnotationInfo`   | `route`, original `text`, parsed `content`, and `location`                                                                         |
| `pymalloy.analysis.RoutedAnnotation` | Nullable `route`, parsed `content`, and original `text`                                                                            |
| `pymalloy.analysis.AnnotatedObject`  | `path: tuple[str, ...]`, `kind`, `annotations: tuple[RoutedAnnotation, ...]`                                                       |
| `pymalloy.analysis.GivenInfo`        | `name`, `type`, `required: bool`, nullable `default_text` and `location`, and `annotations`                                        |
| `pymalloy.analysis.QueryDescriptor`  | `name`, `kind` (`run`, `named`, `view`, `sql`), nullable `location`, and `schema=None`                                             |
| `pymalloy.analysis.MarkdownCell`     | `text: str`, one ordered prose cell                                                                                                |
| `pymalloy.analysis.QueryCell`        | `name: str`, `sql: str`, one compiler-prepared query cell                                                                          |
| `pymalloy.analysis.DocumentCell`     | Union of `MarkdownCell` and `QueryCell`. Use `isinstance` to distinguish them                                                      |

`pymalloy.analysis.QueryCell` comes from `Model.document()`. Notebook export uses
[`pymalloy.export.NotebookQuery`](export.md#document-and-cells), which adds SQL
statement classification.

## Reports and metadata

`pymalloy.analysis.ParseReport` contains `url`, `compiler_version`, `diagnostics`,
`symbols`, `tables`, `imports: tuple[ParsedImport, ...]`, `completions`, and
nullable `help`. Its derived `.ok` is true when diagnostics contain no errors.
`pm.parse` checks syntax and records unresolved imports and tables.

`pymalloy.analysis.CheckReport` contains the same syntax fields plus `ok: bool`,
`queries: tuple[QueryDescriptor, ...]`, and `model: NativeMetadata`.
`Connection.check` resolves names, imports, types, and schemas.
Documentation policy findings can also affect `ok`.

`pymalloy.analysis.NativeMetadata` contains nullable upstream `model`,
`sources: tuple[SourceInfo, ...]`, and `annotations: tuple[AnnotatedObject, ...]`.
These upstream schema records follow Malloy's
[interface definitions](https://github.com/malloydata/malloy/tree/main/packages/malloy-interfaces).

`pymalloy.analysis.Inspection` contains `model`, `queries`, `givens`, `annotations`,
`model_annotations`, `dependencies: tuple[str, ...]`, `imports: tuple[ImportInfo, ...]`,
and `diagnostics`. `reference=None` and `import_=None` carry optional positional
lookup results. An imported-document lookup requires a position and its URL.

Read query output from `QueryDescriptor.schema`. Compiled runs and named queries
carry their own output fields. Required unbound givens yield `None`.
For `run:0`, `run:1`, and `run:2`, each descriptor retains its authored ordinal
even when `run:1` requires givens. Source views and SQL cells resolve output during
preparation or execution. Source schemas remain available through
`NativeMetadata.sources`. The upstream model's `anonymous_queries` is empty.
