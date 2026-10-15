from pathlib import Path

import pymalloy as pm


def main() -> None:
    root = Path(__file__).parent
    result = (
        pm.connect(data_root=root)
        .model(
            "run: duckdb.table('orders.csv') -> {\n  group_by: region\n  aggregate: revenue is amount.sum()\n  order_by: region\n}"
        )
        .query()
        .run()
        .to_polars()
    )
    assert result.to_dicts() == [
        {"region": "North", "revenue": 105},
        {"region": "South", "revenue": 95},
    ]
    print(result)
    orders = pm.connect(data_root=root).model(root / "orders.malloy")
    print(orders.query(malloy="run: orders -> region_detail").run().to_polars())


if __name__ == "__main__":
    main()
