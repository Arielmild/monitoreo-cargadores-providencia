import copy
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from a_sqlite import exportar
from monitor_providencia import procesar, guardar


class MinisterioTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
        self.location = {
            "location_id": 10, "name": "Estación de prueba", "commune": "Providencia",
            "coordinates": {"latitude": "-33.43", "longitude": "-70.61"},
            "last_updated": "2026-10-23T12:00:00+00:00",
            "OPC": {"normalized_name": "Operador", "email": "no-publicar@example.org"},
            "connected_to_electrical_grid": None, "api_updates_enabled": True,
            "evses": [{
                "evse_uid": 20, "evse_id": "EVSE-20", "status": "DISPONIBLE",
                "last_updated": "2026-10-24T18:59:00+00:00",
                "connectors": [
                    {"connector_id": 30, "status": "OCUPADO", "standard": "CCS 2", "max_electric_power": 60, "tariffs": []},
                    {"connector_id": 31, "status": "NO DISPONIBLE", "max_electric_power": 50, "tariffs": []},
                ],
            }],
        }

    def test_nested_connectors_use_their_own_status_and_stable_ids(self):
        rows, stations = procesar([self.location], self.now)
        self.assertEqual([row["status"] for row in rows], ["OCUPADO", "NO_DISPONIBLE"])
        self.assertEqual(rows[0]["source_updated_at_level"], "evse")
        self.assertEqual(rows[0]["evse_status_raw"], "DISPONIBLE")
        self.assertEqual(rows[0]["connected_to_electrical_grid"], "")
        self.assertEqual(stations[0]["n_conectores"], 2)
        self.assertEqual(stations[0]["max_power_kw"], 60)
        self.assertEqual(stations[0]["operator"], "Operador")
        reversed_location = copy.deepcopy(self.location)
        reversed_location["evses"][0]["connectors"].reverse()
        self.assertEqual(procesar([reversed_location], self.now)[0], rows)

    def test_bbox_and_official_commune_are_distinct_filters(self):
        neighbor = dict(self.location, location_id=11, commune="Las Condes")
        outside = dict(self.location, location_id=12, coordinates={"latitude": "-34", "longitude": "-71"})
        unknown = dict(self.location, location_id=13, commune=None)
        rows, stations = procesar([self.location, neighbor, outside, unknown], self.now)
        self.assertEqual(len(rows), 6)
        self.assertEqual([station["es_providencia"] for station in stations], [1, 0, ""])
        strict_rows, strict_stations = procesar([self.location, neighbor, outside, unknown], self.now, solo_providencia=True)
        self.assertEqual(len(strict_rows), 2)
        self.assertEqual(len(strict_stations), 1)

    def test_malformed_or_empty_data_is_rejected(self):
        for payload in ([], {"error": "no disponible"}, [{"status": "DISPONIBLE"}]):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                procesar(payload, self.now)
        broken = copy.deepcopy(self.location)
        del broken["evses"][0]["connectors"][0]["connector_id"]
        with self.assertRaises(ValueError):
            procesar([broken], self.now)

    def test_duplicate_connectors_are_rejected(self):
        duplicate = copy.deepcopy(self.location)
        duplicate["evses"][0]["connectors"].append(duplicate["evses"][0]["connectors"][0])
        with self.assertRaises(ValueError):
            procesar([duplicate], self.now)

    def test_storage_and_sqlite_stay_in_the_ministry_directory(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            root = Path(folder)
            old_data = root / "datos"
            old_data.mkdir()
            existing = old_data / "estaciones.csv"
            existing.write_text("datos del otro monitor\n", encoding="utf-8")
            data = root / "ministerio/datos"
            rows, stations = procesar([self.location], self.now)
            guardar(rows, stations, self.now, data_dir=data, total_locations=1)
            self.assertEqual(existing.read_text(encoding="utf-8"), "datos del otro monitor\n")
            self.assertNotIn("no-publicar@example.org", "".join(path.read_text(encoding="utf-8") for path in data.iterdir()))
            summary = json.loads((data / "estado_monitor.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["conectores_comuna_providencia"], 2)
            db = root / "ministerio/monitoreo_ministerio.db"
            exportar(data, db)
            counts = exportar(data, db)
            self.assertEqual(counts["historial_conectores"], 2)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM historial_conectores").fetchone()[0], 2)
            with next(data.glob("20??-??-??.csv")).open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)


if __name__ == "__main__":
    unittest.main()
