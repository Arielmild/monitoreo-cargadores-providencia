"""Una captura de la API pública de Dónde Cargo, sin crear usuarios ni sesiones."""

import argparse
import csv
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATION_FIELDS = [
    "station_id", "id_uuid", "name", "provider_id", "address", "es_providencia",
    "latitude", "longitude", "power_kw", "is_fast", "min_price", "copec_id", "operator_id",
]
STATION_HISTORY_FIELDS = [
    "observed_at", "station_id", "name", "provider_id", "es_providencia", "status", "updated_at",
]
SOCKET_HISTORY_FIELDS = [
    "observed_at", "station_id_vinculado", "station_name", "provider_id", "es_providencia",
    "socket_record_id", "socket_id", "site_id", "status", "power", "speed", "price",
    "price_minute", "connector_type", "city", "address", "maintenance",
    "last_upserted_at", "metodo_vinculacion",
]


class PublicClient:
    def __init__(self, config):
        self.url = os.environ.get("SUPABASE_URL", config["supabase_url"]).rstrip("/")
        self.key = os.environ.get("SUPABASE_ANON_KEY", config["supabase_anon_key"])

    def page(self, endpoint, params):
        request = Request(
            f"{self.url}/rest/v1/{endpoint}?{urlencode(params)}",
            headers={"apikey": self.key, "Authorization": f"Bearer {self.key}",
                     "Accept": "application/json", "Accept-Profile": "public",
                     "User-Agent": "monitoreo-cargadores-providencia/1.0"},
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=25) as response:
                    result = json.load(response)
                if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                    raise ValueError(f"Respuesta inesperada de {endpoint}")
                return result
            except HTTPError as error:
                if attempt == 2 or error.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"La API respondió HTTP {error.code} en {endpoint}") from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError(f"No se pudo consultar {endpoint} tras 3 intentos") from None
            time.sleep(2 ** attempt)

    def fetch_all(self, endpoint, filters=()):
        records = []
        offset = 0
        seen = set()
        # Se avanza por la cantidad recibida, incluso si el servidor reduce el tamaño de página.
        for _ in range(100):
            rows = self.page(endpoint, [*filters, ("select", "*"), ("order", "id.asc"),
                                        ("limit", 1000), ("offset", offset)])
            if not rows:
                return records
            for row in rows:
                record_id = str(row.get("id", ""))
                if not record_id or record_id in seen:
                    raise ValueError(f"Paginación inconsistente en {endpoint}; no se guardó la captura")
                seen.add(record_id)
            records.extend(rows)
            offset += len(rows)
        raise RuntimeError(f"Se excedió el límite de páginas en {endpoint}")


def text_id(value):
    return "" if value is None else str(value).strip()


def municipality_flag(address):
    """Heurística de dirección, nunca un límite administrativo oficial. Vacío = desconocido."""
    address = (address or "").casefold()
    if "providencia" in address:
        return 1
    if any(name in address for name in ("las condes", "vitacura", "ñuñoa", "nunoa", "santiago centro", "recoleta")):
        return 0
    return ""


def build_indexes(stations):
    indexes = {name: defaultdict(set) for name in ("station_id", "id", "name", "copec_id")}
    for station_id, station in stations.items():
        for field, index in indexes.items():
            values = station.get(field)
            for value in values if isinstance(values, list) else [values]:
                if text_id(value):
                    index[text_id(value)].add(station_id)
    return indexes


def match_socket(socket, indexes):
    checks = [
        ("site_id", "station_id"), ("site_id", "id"),
        ("evx_charge_point_id", "station_id"), ("evx_charge_point_id", "id"),
        ("evx_charge_point_id", "name"), ("copec_id", "copec_id"),
    ]
    candidates = set()
    methods = []
    for source_field, station_field in checks:
        matches = indexes[station_field].get(text_id(socket.get(source_field)), set())
        candidates.update(matches)
        if matches:
            methods.append(f"{source_field}={station_field}")
    # No aceptar coincidencias por fragmentos ni identificadores que señalen a varias estaciones.
    if len(candidates) != 1:
        return None, "ambiguo" if candidates else "sin_coincidencia"
    return next(iter(candidates)), ";".join(methods)


def write_csv(path, fields, rows, append=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.exists() and path.stat().st_size > 0
    if append and existing:
        with path.open(newline="", encoding="utf-8") as handle:
            if next(csv.reader(handle), None) != fields:
                raise ValueError(f"Encabezado incompatible: {path}")
    with path.open("a" if append else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not append or not existing:
            writer.writeheader()
        writer.writerows(rows)


def prepare_capture(raw_stations, raw_sockets, observed_at):
    stations = {}
    for raw_station in raw_stations:
        station = dict(raw_station)
        station_id = text_id(station.get("station_id"))
        if not station_id or station_id in stations:
            raise ValueError("Estación sin identificador único; no se guardó la captura")
        station.update(station_id=station_id, id_uuid=station.get("id"),
                       es_providencia=municipality_flag(station.get("address")),
                       is_fast=int(bool(station.get("is_fast"))),
                       copec_id=json.dumps(station.get("copec_id"), ensure_ascii=False))
        stations[station_id] = station
    if not stations:
        raise ValueError("La API devolvió cero estaciones; no se guardó la captura")
    # Índices sobre los valores originales: copec_id sigue siendo una lista/número.
    indexes = build_indexes({text_id(row["station_id"]): row for row in raw_stations})
    station_history = [dict(station, observed_at=observed_at, status=station.get("status") or "UNKNOWN")
                       for station in stations.values()]
    socket_history = []
    unmatched = Counter()
    for socket in raw_sockets:
        station_id, method = match_socket(socket, indexes)
        if station_id is None:
            unmatched[method] += 1
            continue
        station = stations[station_id]
        socket_history.append(dict(
            socket, observed_at=observed_at, station_id_vinculado=station_id,
            station_name=station.get("name"), provider_id=station.get("provider_id"),
            es_providencia=station["es_providencia"], socket_record_id=socket["id"],
            status=socket.get("status") or "UNKNOWN", maintenance=int(bool(socket.get("maintenance"))),
            metodo_vinculacion=method,
        ))
    if not socket_history:
        raise ValueError("No se vinculó ningún conector; revisar la API antes de guardar")
    return list(stations.values()), station_history, socket_history, unmatched


def capture(data_dir, config):
    started_at = datetime.now(timezone.utc)
    client = PublicClient(config)
    box = config["bounding_box"]
    filters = [("latitude", f"gte.{box['lat_min']}"), ("latitude", f"lte.{box['lat_max']}"),
               ("longitude", f"gte.{box['lon_min']}"), ("longitude", f"lte.{box['lon_max']}")]
    raw_stations = client.fetch_all("stations", filters)
    raw_sockets = client.fetch_all("sockets")
    observed = datetime.now(timezone.utc)
    timestamp = observed.isoformat()
    stations, station_history, socket_history, unmatched = prepare_capture(raw_stations, raw_sockets, timestamp)
    day_dir = data_dir / observed.strftime("%Y/%m")
    for label, fields, rows in (("estaciones", STATION_HISTORY_FIELDS, station_history),
                                 ("conectores", SOCKET_HISTORY_FIELDS, socket_history)):
        write_csv(day_dir / f"historial_{label}_{observed:%Y-%m-%d}.csv", fields, rows, append=True)
    write_csv(data_dir / "estaciones.csv", STATION_FIELDS, stations)
    summary = {
        "observed_at": timestamp, "consulta_iniciada_utc": started_at.isoformat(),
        "duracion_consulta_segundos": round((observed-started_at).total_seconds(), 3),
        "estaciones": len(stations), "conectores": len(socket_history),
        "conectores_consultados_total": len(raw_sockets),
        "conectores_fuera_de_zona_o_sin_vinculo": dict(unmatched),
        "estados_estaciones": dict(Counter(row["status"] for row in station_history)),
        "estados_conectores": dict(Counter(row["status"] for row in socket_history)),
        "estaciones_sin_conectores_vinculados": sorted(
            {row["station_id"] for row in stations} - {row["station_id_vinculado"] for row in socket_history}),
        "fuente": "https://dondecargo.cl/", "limites_consulta": box,
    }
    (data_dir / "estado_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"Captura UTC: {timestamp}\n\n{len(stations)} estaciones y {len(socket_history)} conectores guardados.\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "datos")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    capture(args.data_dir, config)


if __name__ == "__main__":
    main()
