# Malloy DuckDB adapters

Shared DuckDB type conversion, native search-path statements, Arrow materialization,
and Malloy stable result serialization for the Node, browser and Python hosts.

`drive(job, host)` fulfils compiler needs with `host.readURL(url)` and
`host.describe(sql)`. `fields(columns)` converts DuckDB column types to Malloy
field definitions. Runtime hosts own connections and execute queries.

Arrow consumers import `materialize` from `@malloy-runtime/duckdb/arrow` and
provide the optional `apache-arrow` peer dependency. Native schema conversion
uses the root entry.
