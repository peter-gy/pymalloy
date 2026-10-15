"""Run regional and nested queries through one native connection."""

from pathlib import Path

import pymalloy as pm


def main() -> None:
    root = Path(__file__).parent
    with pm.connect(data_root=root) as con:
        model = con.model(root / "orders.malloy")
        result = model.query("orders.by_region").run().to_polars()
        assert result.to_dicts() == [
            {"region": "North", "revenue": 105, "order_count": 3},
            {"region": "South", "revenue": 95, "order_count": 3},
        ]
        print(result)
        print(model.query("orders.region_detail").run().to_polars())


if __name__ == "__main__":
    main()
