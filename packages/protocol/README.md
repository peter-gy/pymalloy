# Python wire contracts

`@pymalloy/protocol` defines Python-facing compiler requests, widget state, and
exact given values. The widget and embedded compiler host import it. Compiler and
database packages expose native TypeScript values and remain independent of
Python serialization.

`records.ts` selects the records emitted by `pnpm records` as JSON Schema and
Python [msgspec](https://jcristharif.com/msgspec/) typed records. `schema/` contains the generation configuration and output.
Change the TypeScript contracts, regenerate records, and rebuild the consuming
bundles together. `pnpm records:check` verifies freshness without changing outputs
and runs in the normal workspace check.
