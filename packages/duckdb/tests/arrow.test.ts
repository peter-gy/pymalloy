import { expect, test } from "vite-plus/test";
import { Field, Int32, List, Map_, Struct, Table, Utf8, vectorFromArray } from "apache-arrow";
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

test("materializes dictionary values across batches and sliced nested rows", () => {
  const first = new Table({ label: vectorFromArray(["first", "second"]) });
  const second = new Table({ label: vectorFromArray(["third", null]) });
  expect(materialize(first.concat(second).slice(1, 4)).rows).toEqual([
    { label: "second" },
    { label: "third" },
    { label: null },
  ]);
  const nested = vectorFromArray(
    [{ value: 1, names: ["one"] }, { value: 2, names: ["two", "second"] }, null],
    new Struct([
      new Field("value", new Int32(), true),
      new Field("names", new List(new Field("item", new Utf8(), true)), true),
    ]),
  );
  expect(materialize(new Table({ nested }).slice(1, 3)).rows).toEqual([
    { nested: { value: 2, names: ["two", "second"] } },
    { nested: null },
  ]);
});
