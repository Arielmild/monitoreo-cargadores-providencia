"""Reconstruye una base SQLite propia desde los CSV del monitor del Ministerio."""

import argparse
import csv
import sqlite3
from contextlib import closing
from pathlib import Path

from monitor_providencia import ROOT, COLUMNAS_HIST, COLUMNAS_EST

INTEGER_FIELDS = {"es_providencia", "n_conectores", "connected_to_electrical_grid", "api_updates_enabled"}
REAL_FIELDS = {"latitude", "longitude", "max_power_kw", "power_kw"}


def exportar(data_dir=ROOT / "datos", db_path=ROOT / "monitoreo_ministerio.db"):
    data_dir, db_path = Path(data_dir), Path(db_path)
    catalog = data_dir / "estaciones.csv"
    histories = sorted(data_dir.glob("20??-??-??.csv"))
    if not catalog.is_file() or not histories:
        raise ValueError("Faltan el catálogo o los CSV diarios del Ministerio")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_db = db_path.with_name(db_path.name + ".tmp")
    counts = {}
    with closing(sqlite3.connect(temp_db)) as connection, connection:
        for table, columns, paths in (("estaciones", COLUMNAS_EST, [catalog]),
                                      ("historial_conectores", COLUMNAS_HIST, histories)):
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            definitions = [f'"{field}" '+("INTEGER" if field in INTEGER_FIELDS else "REAL" if field in REAL_FIELDS else "TEXT")
                           for field in columns]
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')
            counts[table] = 0
            for path in paths:
                with path.open(newline="", encoding="utf-8") as source:
                    reader = csv.DictReader(source)
                    if reader.fieldnames != columns:
                        raise ValueError(f"Esquema CSV incompatible en {path}")
                    for row in reader:
                        connection.execute(f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in columns)})',
                                           [None if row[field] == "" else row[field] for field in columns])
                        counts[table] += 1
        connection.execute("CREATE INDEX idx_hist_fecha ON historial_conectores(observed_at, station_id)")
        connection.execute("CREATE INDEX idx_hist_conector ON historial_conectores(connector_key, observed_at)")
    temp_db.replace(db_path)
    print(f"Base creada: {db_path.resolve()}; {counts}")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datos")
    parser.add_argument("--db-path", type=Path, default=ROOT / "monitoreo_ministerio.db")
    args = parser.parse_args()
    exportar(args.data_dir, args.db_path)
