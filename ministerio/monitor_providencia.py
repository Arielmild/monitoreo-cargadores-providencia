"""Captura de cargadorespublicos.cl: ubicaciones -> EVSE -> conectores."""

import argparse
import csv
import json
import os
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "datos")))
API_URL = "https://cargadorespublicos.cl/api/data"
TZ_CL = ZoneInfo("America/Santiago")
LAT_MIN, LAT_MAX = -33.4560, -33.4080
LON_MIN, LON_MAX = -70.6380, -70.5820
COLUMNAS_HIST = [
    "observed_at", "observed_at_cl", "connector_key", "connector_id", "station_id",
    "evse_uid", "evse_id", "status", "status_raw", "evse_status_raw", "power_kw",
    "connector_type", "operator", "connected_to_electrical_grid", "api_updates_enabled",
    "source_updated_at", "source_updated_at_level", "location_updated_at", "tariffs_json",
]
COLUMNAS_EST = [
    "station_id", "name", "address", "comuna", "es_providencia", "latitude", "longitude",
    "operator", "n_conectores", "max_power_kw",
]


def norm(value):
    return "_".join(unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore")
                    .decode().strip().upper().replace("_", " ").split())


def a_float(value):
    try:
        return float(str(value).replace(",", ".")) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def bool_csv(value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return int(value)
    if norm(value) in ("TRUE", "1", "SI"):
        return 1
    if norm(value) in ("FALSE", "0", "NO"):
        return 0
    return ""


def normalizar_estado(value):
    state = norm(value)
    if state in ("DISPONIBLE", "AVAILABLE"):
        return "DISPONIBLE"
    if state in ("OCUPADO", "OCCUPIED", "CHARGING", "CARGANDO"):
        return "OCUPADO"
    if state in ("FUERA_DE_LINEA", "OFFLINE", "SIN_COMUNICACION"):
        return "FUERA_DE_LINEA"
    if state in ("NO_DISPONIBLE", "UNAVAILABLE", "INOPERATIVO", "FUERA_DE_SERVICIO",
                 "OUTOFSERVICE", "OUT_OF_SERVICE", "OUT_OF_ORDER", "FAULTED"):
        return "NO_DISPONIBLE"
    return "DESCONOCIDO"


def crear_sesion():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=1, allowed_methods=("GET",),
                    status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update({"Accept": "application/json", "User-Agent": "monitor-cargadores-providencia/1.0"})
    return session


def procesar(payload, observed_at, solo_providencia=False):
    if not isinstance(payload, list) or not payload or not all(isinstance(item, dict) for item in payload):
        raise ValueError("La API debe entregar una lista no vacía de ubicaciones")
    stations, observations, seen = {}, [], set()
    timestamp = observed_at.isoformat(timespec="seconds")
    local_timestamp = observed_at.astimezone(TZ_CL).isoformat(timespec="seconds")
    for location in payload:
        coordinates = location.get("coordinates") or {}
        lat, lon = a_float(coordinates.get("latitude")), a_float(coordinates.get("longitude"))
        commune = location.get("commune")
        providencia = "" if not commune else int(norm(commune) == "PROVIDENCIA")
        if lat is not None and lon is not None:
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                continue
        else:
            # Sin coordenadas no se puede asegurar el mismo rectángulo de comparación.
            continue
        if solo_providencia and providencia != 1:
            continue
        location_id = location.get("location_id")
        if location_id in (None, ""):
            raise ValueError("Ubicación de la zona sin location_id")
        station_id = str(location_id)
        if station_id in stations:
            raise ValueError(f"location_id duplicado: {station_id}")
        operator = location.get("OPC") or {}
        if not isinstance(operator, dict):
            raise ValueError("OPC dejó de ser un objeto")
        operator_name = operator.get("normalized_name") or operator.get("name")
        station = dict(station_id=station_id, name=location.get("name"), address=location.get("address"),
                       comuna=commune, es_providencia=providencia, latitude=lat, longitude=lon,
                       operator=operator_name, n_conectores=0, max_power_kw=None)
        stations[station_id] = station
        evses = location.get("evses")
        if not isinstance(evses, list):
            raise ValueError(f"La ubicación {station_id} no contiene una lista evses")
        for evse in evses:
            if not isinstance(evse, dict) or not isinstance(evse.get("connectors"), list):
                raise ValueError(f"Esquema EVSE inesperado en {station_id}")
            evse_uid = evse.get("evse_uid")
            if evse_uid in (None, ""):
                raise ValueError(f"EVSE sin evse_uid en {station_id}")
            for connector in evse["connectors"]:
                if not isinstance(connector, dict) or connector.get("connector_id") in (None, ""):
                    raise ValueError(f"Conector sin connector_id en {station_id}")
                connector_id = str(connector["connector_id"])
                # Los tres identificadores proceden de la fuente y no dependen del orden de la lista.
                key = f"{station_id}:{evse_uid}:{connector_id}"
                if key in seen:
                    raise ValueError(f"Conector duplicado: {key}")
                seen.add(key)
                power = a_float(connector.get("max_electric_power"))
                updated_at, updated_level = None, ""
                for item, level in ((connector, "connector"), (evse, "evse"), (location, "location")):
                    if item.get("last_updated"):
                        updated_at, updated_level = item["last_updated"], level
                        break
                tariffs = connector.get("tariffs") or []
                if not isinstance(tariffs, list):
                    raise ValueError(f"Tarifas inesperadas en {key}")
                # Publicar solo campos de tarifas, no la respuesta completa con datos de contacto.
                tariff_fields = ("tariff_id", "last_updated", "min_price", "max_price", "pse_id", "elements")
                safe_tariffs = [{field: tariff[field] for field in tariff_fields if field in tariff}
                                for tariff in tariffs if isinstance(tariff, dict)]
                observations.append(dict(
                    observed_at=timestamp, observed_at_cl=local_timestamp, connector_key=key,
                    connector_id=connector_id, station_id=station_id, evse_uid=str(evse_uid),
                    evse_id=evse.get("evse_id"), status=normalizar_estado(connector.get("status")),
                    status_raw=connector.get("status"), evse_status_raw=evse.get("status"),
                    power_kw=power, connector_type=connector.get("standard"), operator=operator_name,
                    connected_to_electrical_grid=bool_csv(location.get("connected_to_electrical_grid")),
                    api_updates_enabled=bool_csv(location.get("api_updates_enabled")),
                    source_updated_at=updated_at, source_updated_at_level=updated_level,
                    location_updated_at=location.get("last_updated"),
                    tariffs_json=json.dumps(safe_tariffs, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ))
                station["n_conectores"] += 1
                if power is not None:
                    station["max_power_kw"] = max(power, station["max_power_kw"] or 0)
    if not observations:
        raise ValueError("La API no entregó conectores utilizables en la zona; no se guardó la captura")
    observations.sort(key=lambda row: row["connector_key"])
    return observations, [stations[key] for key in sorted(stations)]


def write_csv(path, columns, rows, append=False):
    existing = path.exists() and path.stat().st_size > 0
    if append and existing:
        with path.open(newline="", encoding="utf-8") as handle:
            if next(csv.reader(handle), None) != columns:
                raise ValueError(f"Encabezado incompatible en {path}")
    with path.open("a" if append else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not append or not existing:
            writer.writeheader()
        writer.writerows(rows)


def guardar(rows, stations, observed_at, data_dir=DATA_DIR, total_locations=None, solo_providencia=False):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{observed_at.astimezone(TZ_CL):%Y-%m-%d}.csv"
    write_csv(path, COLUMNAS_HIST, rows, append=True)
    catalog = data_dir / "estaciones.csv.tmp"
    write_csv(catalog, COLUMNAS_EST, stations)
    catalog.replace(data_dir / "estaciones.csv")
    summary = dict(
        fuente=API_URL, observed_at=observed_at.isoformat(timespec="seconds"),
        observed_at_cl=observed_at.astimezone(TZ_CL).isoformat(timespec="seconds"),
        ubicaciones_consultadas=total_locations, estaciones=len(stations), conectores=len(rows),
        estaciones_comuna_providencia=sum(station["es_providencia"] == 1 for station in stations),
        conectores_comuna_providencia=sum(station["n_conectores"] for station in stations if station["es_providencia"] == 1),
        comunas=dict(Counter(station["comuna"] or "DESCONOCIDA" for station in stations)),
        estados=dict(Counter(row["status"] for row in rows)), solo_providencia=solo_providencia,
        limites_consulta=dict(lat_min=LAT_MIN, lat_max=LAT_MAX, lon_min=LON_MIN, lon_max=LON_MAX),
    )
    (data_dir / "estado_monitor.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"Fuente: {API_URL}\n\nCaptura UTC: {summary['observed_at']}\n\n"
                         f"{len(stations)} estaciones y {len(rows)} conectores guardados.\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspeccionar", action="store_true", help="consultar y validar sin guardar")
    parser.add_argument("--solo-providencia", action="store_true", help="exigir comuna Providencia además del rectángulo")
    args = parser.parse_args()
    strict = args.solo_providencia or os.environ.get("SOLO_PROVIDENCIA", "0") == "1"
    with crear_sesion() as session:
        response = session.get(API_URL, timeout=(10, 40))
        response.raise_for_status()
        payload = response.json()
    observed_at = datetime.now(timezone.utc)
    rows, stations = procesar(payload, observed_at, solo_providencia=strict)
    if args.inspeccionar:
        print(f"API válida: {len(payload)} ubicaciones consultadas; {len(stations)} estaciones y {len(rows)} conectores en zona")
    else:
        guardar(rows, stations, observed_at, total_locations=len(payload), solo_providencia=strict)


if __name__ == "__main__":
    main()
