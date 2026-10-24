import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from exportar_datos import export
from monitor_cloud import (PublicClient, STATION_FIELDS, STATION_HISTORY_FIELDS, SOCKET_HISTORY_FIELDS,
                           build_indexes, match_socket, prepare_capture, write_csv, capture)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.station = dict(id="uuid-a", station_id="a123456", name="Cargador A", copec_id=[42],
                            address="Providencia", latitude=-33.42, longitude=-70.61, status="AVAILABLE")
        self.socket = dict(id=1, site_id="a123456", socket_id="s1", status="CHARGING")

    def test_does_not_invent_substring_links_or_choose_ambiguous_identifiers(self):
        other = dict(self.station, id="uuid-b", station_id="b123456")
        indexes = build_indexes({"a123456": self.station, "b123456": other})
        self.assertEqual(match_socket({"site_id": "123456"}, indexes)[0], None)
        self.assertEqual(match_socket({"copec_id": 42}, indexes), (None, "ambiguo"))
        self.assertEqual(match_socket(dict(self.socket, copec_id=42), indexes), (None, "ambiguo"))
        self.assertEqual(match_socket(self.socket, indexes)[0], "a123456")

    def test_pagination_continues_when_server_returns_small_pages(self):
        client = PublicClient(dict(supabase_url="https://example.org", supabase_anon_key="public"))
        with patch.object(client, "page", side_effect=[[{"id": 1}], [{"id": 2}], []]) as page:
            self.assertEqual(len(client.fetch_all("stations")), 2)
            self.assertEqual(dict(page.call_args_list[1].args[1])["offset"], 1)
        with patch.object(client, "page", side_effect=[[{"id": 1}], [{"id": 1}]]):
            with self.assertRaises(ValueError):
                client.fetch_all("stations")

    def test_empty_or_failed_capture_leaves_no_history(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "datos"
            config = dict(supabase_url="https://example.org", supabase_anon_key="public",
                          bounding_box=dict(lat_min=-34, lat_max=-33, lon_min=-71, lon_max=-70))
            with patch.object(PublicClient, "fetch_all", side_effect=[[self.station], RuntimeError("fallo")]):
                with self.assertRaises(RuntimeError):
                    capture(data, config)
            self.assertFalse(data.exists())
            with self.assertRaises(ValueError):
                prepare_capture([], [self.socket], "2026-10-24T20:00:00+00:00")

    def test_export_preserves_observations_and_repeated_export_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "datos"
            stations, history, sockets, _ = prepare_capture([self.station], [self.socket], "2026-10-24T20:00:00+00:00")
            write_csv(data / "estaciones.csv", STATION_FIELDS, stations)
            for label, fields, rows in (("estaciones", STATION_HISTORY_FIELDS, history),
                                       ("conectores", SOCKET_HISTORY_FIELDS, sockets)):
                path = data / "2026/10" / f"historial_{label}_2026-10-24.csv"
                write_csv(path, fields, rows, append=True)
                write_csv(path, fields, [dict(row, observed_at="2026-10-24T20:05:00+00:00") for row in rows], append=True)
            output = Path(folder) / "exportaciones"
            export(data, output)
            counts = export(data, output)
            self.assertEqual(counts["historial_conectores"], 2)
            with closing(sqlite3.connect(output / "monitoreo_providencia.db")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM historial_conectores").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT status FROM historial_conectores LIMIT 1").fetchone()[0], "CHARGING")
            with (output / "historial_estaciones.csv").open(newline="", encoding="utf-8-sig") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)


if __name__ == "__main__":
    unittest.main()
