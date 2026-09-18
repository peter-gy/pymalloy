from pathlib import Path

import pymalloy as pm


def main() -> None:
    root = Path(__file__).parent
    result = pm.run(
        """run: duckdb.table('orders.csv') -> {
  group_by: region
  aggregate: revenue is amount.sum()
  order_by: region
}""",
        data_root=root,
    ).polars()
    assert result.to_dicts() == [
        {"region": "North", "revenue": 105},
        {"region": "South", "revenue": 95},
    ]
    print(result)
    orders = pm.model(root / "orders.malloy", data_root=root)
    print(orders.query(malloy="run: orders -> region_detail").run().polars())


if __name__ == "__main__":
    main()
