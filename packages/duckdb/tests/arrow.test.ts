import { expect, test } from "vite-plus/test";
import { Field, Int32, Map_, Struct, Table, Utf8, vectorFromArray } from "apache-arrow";
import { materialize } from "../src/arrow";

test("preserves map keys and values, including empty and null maps", () => {
  const type = new Map_(
    new Field(
      "entries",
      new Struct([new Field("key", new Utf8(), false), new Field("value", new Int32(), true)]),
      false,
    ),
  );
  const attributes = vectorFromArray(
    [
      new Map<string, number | null>([
        ["alpha", 42],
        ["beta", 13],
        ["missing", null],
      ]),
      new Map(),
      null,
    ],
    type,
  );
  expect(materialize(new Table({ attributes })).rows).toEqual([
    {
      attributes: [
        { key: "alpha", value: 42 },
        { key: "beta", value: 13 },
        { key: "missing", value: null },
      ],
    },
    { attributes: [] },
    { attributes: null },
  ]);
});
