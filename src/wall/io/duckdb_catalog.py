from __future__ import annotations

import argparse
from pathlib import Path

try:
    import duckdb
except ModuleNotFoundError as exc:
    raise SystemExit(
        "duckdb is not installed in the current environment. "
        "Install it in the 'wall' environment first, then rerun this script."
    ) from exc

from wall.io.table_io import detect_existing_tables


def sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a DuckDB catalog over parsed demo tables.")
    parser.add_argument("data_dir", type=Path, help="Parsed demo output directory")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Output DuckDB file; defaults to <data_dir>/tables.duckdb",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    db_path = args.db_path or (data_dir / "tables.duckdb")
    tables = detect_existing_tables(data_dir)
    if not tables:
        raise FileNotFoundError(f"No .parquet or .csv tables found in {data_dir}")

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("create schema if not exists wall")

        registry_rows: list[tuple[str, str, str]] = []
        for stem, path, table_format in tables:
            resolved_path = str(path.resolve())
            registry_rows.append((stem, table_format, resolved_path))
            if table_format == "parquet":
                conn.execute(
                    f'create or replace view wall."{stem}" as select * from read_parquet({sql_string_literal(resolved_path)})'
                )
            else:
                conn.execute(
                    f'create or replace view wall."{stem}" as select * from read_csv_auto({sql_string_literal(resolved_path)}, header=true)'
                )

        conn.execute("drop table if exists wall.table_registry")
        conn.execute(
            """
            create table wall.table_registry (
                table_name varchar,
                source_format varchar,
                source_path varchar
            )
            """
        )
        conn.executemany(
            "insert into wall.table_registry (table_name, source_format, source_path) values (?, ?, ?)",
            registry_rows,
        )
    finally:
        conn.close()

    print(f"Built DuckDB catalog: {db_path}")
    print("Registered tables:")
    for stem, path, table_format in tables:
        print(f"  - {stem} ({table_format}) -> {path.name}")


if __name__ == "__main__":
    main()
