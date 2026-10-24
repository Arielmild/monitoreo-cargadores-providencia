"""Consolida los CSV diarios en dos CSV completos y una base SQLite para análisis."""

import argparse
import csv
import sqlite3
from contextlib import closing
from pathlib import Path

from monitor_cloud import ROOT, STATION_FIELDS, STATION_HISTORY_FIELDS, SOCKET_HISTORY_FIELDS

INTEGER_FIELDS = {"es_providencia", "is_fast", "maintenance", "socket_record_id"}
REAL_FIELDS = {"latitude", "longitude", "power_kw", "min_price", "power", "price", "price_minute"}


def export(data_dir, output_dir):
    if not (data_dir / "estaciones.csv").exists():
        raise ValueError("No se encontró datos/estaciones.csv; descarga primero los datos del repositorio")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Construir una base nueva permite repetir la exportación sin duplicar filas.
    temp_db = output_dir / "monitoreo_providencia.tmp.db"
    counts = {}
    with closing(sqlite3.connect(temp_db)) as connection, connection:
        for table, fields, paths in (
            ("estaciones", STATION_FIELDS, [data_dir / "estaciones.csv"]),
            ("historial_estaciones", STATION_HISTORY_FIELDS, sorted(data_dir.glob("*/*/historial_estaciones_*.csv"))),
            ("historial_conectores", SOCKET_HISTORY_FIELDS, sorted(data_dir.glob("*/*/historial_conectores_*.csv"))),
        ):
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            columns = [f'"{field}" '+("INTEGER" if field in INTEGER_FIELDS else "REAL" if field in REAL_FIELDS else "TEXT") for field in fields]
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(columns)})')
            counts[table] = 0
            with (output_dir / f"{table}.csv").open("w", newline="", encoding="utf-8-sig") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                for path in paths:
                    with path.open(newline="", encoding="utf-8") as source:
                        reader = csv.DictReader(source)
                        if reader.fieldnames != fields:
                            raise ValueError(f"Encabezado incompatible en {path}")
                        for row in reader:
                            writer.writerow(row)
                            values = [None if row[field] == "" else row[field] for field in fields]
                            connection.execute(f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in fields)})', values)
                            counts[table] += 1
            if table != "estaciones":
                connection.execute(f'CREATE INDEX "idx_{table}_fecha" ON "{table}" (observed_at)')
    temp_db.replace(output_dir / "monitoreo_providencia.db")
    print(f"Exportado en {output_dir.resolve()}: {counts}")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datos")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "exportaciones")
    args = parser.parse_args()
    export(args.data_dir, args.output_dir)
