# Python wire contracts

`@pymalloy/protocol` defines Python-facing compiler requests, widget state, and
exact given values. Both the widget and Deno server import it. Compiler and
database packages expose native TypeScript values and remain independent of
Python serialization.

`records.ts` selects the records emitted by `pnpm records` as JSON Schema and
Python msgspec types. Change the TypeScript contracts, regenerate records, and
rebuild the consuming bundles together.
