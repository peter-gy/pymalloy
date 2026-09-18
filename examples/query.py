from pathlib import Path

from pymalloy.server import Session


def main() -> None:
    with Session(data_root=Path(__file__).parent) as session:
        result = session.run("""
run: duckdb.table('orders.csv') -> {
  group_by: region
  aggregate: revenue is amount.sum()
  order_by: region
}
""")
        assert result.to_dicts() == [
            {"region": "North", "revenue": 105},
            {"region": "South", "revenue": 95},
        ]
        print(result)
        orders = session.load(Path(__file__).with_name("orders.malloy"))
        print(orders.run("run: orders -> region_detail"))


if __name__ == "__main__":
    main()
