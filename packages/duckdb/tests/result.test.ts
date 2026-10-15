import { runInNewContext } from "node:vm";
import { expect, test } from "vite-plus/test";
import { stableResult } from "../src/result";

test("formats signed TIME microseconds", () => {
  const result = stableResult(
    "",
    [{ name: "clock", type: "TIME" }],
    [{ clock: -1n }, { clock: -1_500_000n }],
  );
  expect(result.data).toEqual({
    kind: "array_cell",
    array_value: [
      {
        kind: "record_cell",
        record_value: [{ kind: "string_cell", string_value: "-00:00:00.000001" }],
      },
      { kind: "record_cell", record_value: [{ kind: "string_cell", string_value: "-00:00:01.5" }] },
    ],
  });
});

test("normalizes upstream date inputs into UTC ISO cells", () => {
  const foreignDate: Date = runInNewContext("new Date('2026-09-10T00:00:00Z')");
  expect(foreignDate instanceof Date).toBe(false);
  const result = stableResult(
    "",
    [{ name: "day", type: "DATE" }],
    [
      { day: "2026-09-10" },
      { day: "2026-09-10 00:00:00" },
      { day: Date.UTC(2026, 8, 10) },
      { day: { value: "2026-09-10T00:00:00Z" } },
      { day: foreignDate },
    ],
  );
  expect(result.data).toEqual({
    kind: "array_cell",
    array_value: Array.from({ length: 5 }, () => ({
      kind: "record_cell",
      record_value: [{ kind: "date_cell", date_value: "2026-09-10T00:00:00.000Z" }],
    })),
  });
});

test("non-finite nested values share string schemas with their finite siblings", () => {
  const result = stableResult(
    "",
    [],
    [
      { nested: { reading: Infinity, samples: [NaN, 1.5, null] } },
      { nested: { reading: 42, samples: [-Infinity] } },
      { nested: null },
    ],
    {
      schema: {
        fields: [
          {
            kind: "dimension",
            name: "nested",
            type: {
              kind: "record_type",
              fields: [
                { name: "reading", type: { kind: "number_type" } },
                {
                  name: "samples",
                  type: { kind: "array_type", element_type: { kind: "number_type" } },
                },
              ],
            },
          },
        ],
      },
    },
  );
  expect(result.schema).toEqual({
    fields: [
      {
        kind: "dimension",
        name: "nested",
        type: {
          kind: "record_type",
          fields: [
            { name: "reading", type: { kind: "string_type" } },
            {
              name: "samples",
              type: { kind: "array_type", element_type: { kind: "string_type" } },
            },
          ],
        },
      },
    ],
  });
  expect(result.data).toEqual({
    kind: "array_cell",
    array_value: [
      {
        kind: "record_cell",
        record_value: [
          {
            kind: "record_cell",
            record_value: [
              { kind: "string_cell", string_value: "Infinity" },
              {
                kind: "array_cell",
                array_value: [
                  { kind: "string_cell", string_value: "NaN" },
                  { kind: "string_cell", string_value: "1.5" },
                  { kind: "null_cell" },
                ],
              },
            ],
          },
        ],
      },
      {
        kind: "record_cell",
        record_value: [
          {
            kind: "record_cell",
            record_value: [
              { kind: "string_cell", string_value: "42" },
              {
                kind: "array_cell",
                array_value: [{ kind: "string_cell", string_value: "-Infinity" }],
              },
            ],
          },
        ],
      },
      { kind: "record_cell", record_value: [{ kind: "null_cell" }] },
    ],
  });
});
