import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from publicar_powerbi import HISTORIES, TZ_CHILE, publish


class PowerBITests(unittest.TestCase):
    def write_csv(self, path, fields, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def fixture(self, repo, timestamps):
        for source, path in (("dondecargo", "datos/estaciones.csv"), ("ministerio", "ministerio/datos/estaciones.csv")):
            self.write_csv(repo / path, ["station_id", "name"], [{"station_id": "001", "name": 'Ñuñoa, "Prueba"'}])
        fields = ["observed_at", "station_id", "status", "note"]
        for _, _, directory, _, basename, local_names in HISTORIES:
            groups = {}
            for index, timestamp in enumerate(timestamps):
                observed = datetime.fromisoformat(timestamp)
                day = observed.astimezone(TZ_CHILE).date() if local_names else observed.date()
                groups.setdefault(day, []).append(dict(observed_at=timestamp, station_id="001", status="AVAILABLE", note=f'Fila {index}, "ñ"\nsegunda línea'))
            for day, rows in groups.items():
                path = repo / directory / (f"{day}.csv" if local_names else f"{day:%Y/%m}/{basename}_{day}.csv")
                self.write_csv(path, fields, rows)

    def entries(self, repo):
        with (repo / "powerbi/archivos.csv").open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def table_rows(self, repo, table):
        rows = []
        for entry in self.entries(repo):
            if entry["tabla"] == table:
                path = repo / entry["ruta_relativa"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    rows.extend(csv.DictReader(handle))
        return rows

    def test_chile_day_boundary_excludes_current_day_and_keeps_utf8_and_ids(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            self.fixture(repo, ["2026-10-23T23:00:00+00:00", "2026-10-24T23:00:00+00:00",
                                "2026-10-25T02:59:59+00:00", "2026-10-25T03:00:00+00:00"])
            state = publish(repo, now=datetime(2026, 10, 25, 4, tzinfo=timezone.utc))
            self.assertEqual(state["cerrado_hasta"], "2026-10-24")
            for table, *_ in HISTORIES:
                rows = self.table_rows(repo, table)
                self.assertEqual(len(rows), 3)
                self.assertEqual(rows[-1]["fecha_chile"], "2026-10-24")
                self.assertEqual(rows[-1]["station_id"], "001")
                self.assertIn('"ñ"\nsegunda línea', rows[-1]["note"])

    def test_waits_until_0010_and_does_not_repeat_the_same_export(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            self.fixture(repo, ["2026-10-24T23:00:00+00:00"])
            self.assertFalse(publish(repo, now=datetime(2026, 10, 25, 3, 9, tzinfo=timezone.utc), if_pending=True)["publicado"])
            self.assertFalse((repo / "powerbi").exists())
            state = publish(repo, now=datetime(2026, 10, 25, 3, 10, tzinfo=timezone.utc), if_pending=True)
            self.assertTrue(state["publicado"])
            before = {path: path.read_bytes() for path in (repo / "powerbi").rglob("*") if path.is_file()}
            self.assertFalse(publish(repo, now=datetime(2026, 10, 25, 20, tzinfo=timezone.utc), if_pending=True)["publicado"])
            self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_incremental_close_adds_new_days_without_duplicates_and_can_rebuild(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            timestamps = ["2026-10-24T23:00:00+00:00", "2026-10-25T02:59:59+00:00", "2026-10-25T03:00:00+00:00"]
            self.fixture(repo, timestamps)
            publish(repo, now=datetime(2026, 10, 25, 4, tzinfo=timezone.utc))
            state = publish(repo, now=datetime(2026, 10, 26, 4, tzinfo=timezone.utc))
            before = {entry["ruta_relativa"]: entry["sha256"] for entry in self.entries(repo)}
            self.assertEqual(state["filas_nuevas"]["ministerio_historial_conectores"], 1)
            for table, *_ in HISTORIES:
                self.assertEqual(len(self.table_rows(repo, table)), 3)
            publish(repo, now=datetime(2026, 10, 26, 4, tzinfo=timezone.utc), rebuild=True)
            self.assertEqual(before, {entry["ruta_relativa"]: entry["sha256"] for entry in self.entries(repo)})

    def test_failed_export_preserves_the_previous_published_index_and_state(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            self.fixture(repo, ["2026-10-24T23:00:00+00:00", "2026-10-25T03:00:00+00:00"])
            publish(repo, now=datetime(2026, 10, 25, 4, tzinfo=timezone.utc))
            index_before = (repo / "powerbi/archivos.csv").read_bytes()
            state_before = (repo / "powerbi/estado_exportacion.json").read_bytes()
            self.write_csv(repo / "ministerio/datos/2026-10-25.csv", ["campo_incorrecto"], [{"campo_incorrecto": "x"}])
            with self.assertRaises(ValueError):
                publish(repo, now=datetime(2026, 10, 26, 4, tzinfo=timezone.utc))
            self.assertEqual(index_before, (repo / "powerbi/archivos.csv").read_bytes())
            self.assertEqual(state_before, (repo / "powerbi/estado_exportacion.json").read_bytes())
            self.assertFalse(list(repo.glob(".exportacion-powerbi-*")))

    def test_splits_detail_files_before_the_size_limit_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            self.fixture(repo, [f"2026-10-24T20:{minute:02d}:00+00:00" for minute in range(20)])
            publish(repo, now=datetime(2026, 10, 25, 4, tzinfo=timezone.utc), max_part_bytes=1024)
            for table, *_ in HISTORIES:
                matching = [entry for entry in self.entries(repo) if entry["tabla"] == table]
                self.assertGreater(len(matching), 1)
                self.assertTrue(all(int(entry["tamano_bytes"]) <= 1024 for entry in matching))
                self.assertEqual(len(self.table_rows(repo, table)), 20)

    def test_winter_boundary_uses_chile_timezone_instead_of_a_fixed_utc_offset(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            repo = Path(folder)
            self.fixture(repo, ["2026-07-25T03:59:59+00:00", "2026-07-25T04:00:00+00:00"])
            publish(repo, now=datetime(2026, 7, 25, 5, tzinfo=timezone.utc))
            for table, *_ in HISTORIES:
                rows = self.table_rows(repo, table)
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0]["observed_at_cl"].endswith("-04:00"))


if __name__ == "__main__":
    unittest.main()
