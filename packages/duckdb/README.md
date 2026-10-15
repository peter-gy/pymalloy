# Malloy DuckDB adapters

Shared [DuckDB](https://duckdb.org/docs/stable/) SQL type conversion, native search-path statements, Arrow materialization,
and Malloy stable result serialization for the Node, browser and Python hosts.

`describeSQL(need)` builds a DuckDB DESCRIBE statement for a compiler schema
request. `fields(columns)` converts DuckDB column types to Malloy field
definitions using Malloy's DuckDB type parser. Runtime hosts own connections,
read source files, and execute queries.

Arrow consumers import `materialize` from `@malloy-runtime/duckdb/arrow` and
provide the optional `apache-arrow` peer dependency. Native schema conversion
uses the root entry.
