"""Publica días cerrados de ambas fuentes como CSV de detalle para Power BI."""

import csv
import hashlib
import io
import json
import re
from collections import Counter, OrderedDict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

TZ_CHILE = ZoneInfo("America/Santiago")
VERSION = 1
RAW_PREFIX = "Arielmild/monitoreo-cargadores-providencia/main/"
RAW_BASE = "https://raw.githubusercontent.com/"
MAX_PART_BYTES = 45 * 1024 * 1024
INDEX_FIELDS = ["tabla", "fuente", "fecha_chile", "parte", "ruta_relativa", "url", "filas",
                "tamano_bytes", "sha256", "columnas_json"]
HISTORIES = (
    ("dondecargo_historial_estaciones", "dondecargo", "datos", "*/*/historial_estaciones_*.csv", "historial_estaciones", False),
    ("dondecargo_historial_conectores", "dondecargo", "datos", "*/*/historial_conectores_*.csv", "historial_conectores", False),
    ("ministerio_historial_conectores", "ministerio", "ministerio/datos", "20??-??-??.csv", "historial_conectores", True),
)


def csv_line(values):
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerow(values)
    return buffer.getvalue().encode("utf-8")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields) or any(not field for field in fields):
            raise ValueError(f"Encabezado inválido: {path}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Fila CSV incompleta o con columnas adicionales: {path}")
            rows.append(row)
    return fields, rows


def entry_for_file(path, relative_path, table, source, fields, count, day="", part=""):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(tabla=table, fuente=source, fecha_chile=day, parte=part,
                ruta_relativa=relative_path, url=RAW_BASE + RAW_PREFIX + relative_path,
                filas=count, tamano_bytes=path.stat().st_size, sha256=digest,
                columnas_json=json.dumps(fields, ensure_ascii=False, separators=(",", ":")))


class Partitions:
    """Archivos diarios acotados en tamaño; como máximo ocho descriptores abiertos."""

    def __init__(self, stage, table, source, basename, fields, max_bytes):
        self.stage, self.table, self.source, self.basename = stage, table, source, basename
        self.fields, self.max_bytes = fields, max_bytes
        self.header = b"\xef\xbb\xbf" + csv_line(fields)
        self.current, self.parts, self.handles = {}, [], OrderedDict()

    def _write(self, state, content):
        path = state["path"]
        handle = self.handles.pop(path, None)
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("ab")
        self.handles[path] = handle
        if len(self.handles) > 8:
            _, old_handle = self.handles.popitem(last=False)
            old_handle.close()
        handle.write(content)
        state["hash"].update(content)
        state["bytes"] += len(content)

    def append(self, day, row):
        content = csv_line([row.get(field, "") for field in self.fields])
        if len(self.header) + len(content) > self.max_bytes:
            raise ValueError(f"Una fila de {self.table} excede el tamaño permitido")
        state = self.current.get(day)
        if state is None or state["bytes"] + len(content) > self.max_bytes:
            number = 1 if state is None else state["number"] + 1
            relative = f"powerbi/{self.source}/{day:%Y/%m/%d}/{self.basename}_{number:03d}.csv"
            state = dict(path=self.stage / relative, relative=relative, number=number,
                         day=day, rows=0, bytes=0, hash=hashlib.sha256())
            self.current[day] = state
            self.parts.append(state)
            self._write(state, self.header)
        self._write(state, content)
        state["rows"] += 1

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()

    def entries(self):
        self.close()
        return [dict(tabla=self.table, fuente=self.source, fecha_chile=part["day"].isoformat(),
                     parte=part["number"], ruta_relativa=part["relative"],
                     url=RAW_BASE + RAW_PREFIX + part["relative"], filas=part["rows"],
                     tamano_bytes=part["bytes"], sha256=part["hash"].hexdigest(),
                     columnas_json=json.dumps(self.fields, ensure_ascii=False, separators=(",", ":")))
                for part in self.parts]


def _history_files(repo, directory, pattern, first_day, last_day, local_filenames):
    for path in sorted((repo / directory).glob(pattern)):
        match = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", path.name)
        if not match:
            raise ValueError(f"Fecha de archivo no reconocida: {path}")
        file_day = date.fromisoformat(match[1])
        final_file_day = last_day if local_filenames else last_day + timedelta(days=1)
        if (first_day is None or file_day >= first_day) and file_day <= final_file_day:
            yield path


def _export_history(repo, stage, spec, first_day, last_day, max_bytes):
    table, source, directory, pattern, basename, local_filenames = spec
    partition = None
    original_fields = None
    count = 0
    try:
        for path in _history_files(repo, directory, pattern, first_day, last_day, local_filenames):
            # Leer en streaming: el historial total no se carga en memoria.
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                fields = reader.fieldnames
                if not fields or "observed_at" not in fields or len(set(fields)) != len(fields):
                    raise ValueError(f"Encabezado de historial incompatible: {path}")
                if original_fields is None:
                    original_fields = fields
                    output_fields = fields + [field for field in ("observed_at_cl", "fecha_chile") if field not in fields]
                    partition = Partitions(stage, table, source, basename, output_fields, max_bytes)
                elif fields != original_fields:
                    raise ValueError(f"Cambió el esquema CSV de {table}: {path}")
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError(f"Fila incompleta o con columnas adicionales en {path}")
                    observed = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                    if observed.tzinfo is None:
                        raise ValueError(f"Timestamp sin zona horaria en {path}")
                    local = observed.astimezone(TZ_CHILE)
                    day = local.date()
                    if day > last_day or (first_day is not None and day < first_day):
                        continue
                    row["observed_at_cl"] = local.isoformat()
                    row["fecha_chile"] = day.isoformat()
                    partition.append(day, row)
                    count += 1
        return partition.entries() if partition else [], count
    finally:
        if partition:
            partition.close()


def publish(repo, *, now=None, if_pending=False, rebuild=False, through=None, max_part_bytes=MAX_PART_BYTES):
    repo = Path(repo).resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("La hora de exportación necesita zona horaria")
    local_now = now.astimezone(TZ_CHILE)
    last_day = through or local_now.date() - timedelta(days=1)
    if last_day >= local_now.date():
        raise ValueError("Solo se pueden publicar días de Chile que ya terminaron")
    if if_pending and local_now.time().replace(tzinfo=None) < time(0, 10):
        print("Exportación diaria: se espera hasta las 00:10 de Chile")
        return {"publicado": False}
    output = repo / "powerbi"
    state_path = output / "estado_exportacion.json"
    index_path = output / "archivos.csv"
    previous_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    previous_entries = []
    previous_day = None
    if previous_state and not rebuild:
        if previous_state.get("version") != VERSION:
            raise ValueError("Cambió el formato de publicación; ejecutar --reconstruir-power-bi")
        previous_day = date.fromisoformat(previous_state["cerrado_hasta"])
        if not index_path.exists():
            raise ValueError("Falta powerbi/archivos.csv; ejecutar --reconstruir-power-bi")
        fields, previous_entries = read_csv(index_path)
        if fields != INDEX_FIELDS or any(not (repo / entry["ruta_relativa"]).is_file() for entry in previous_entries):
            raise ValueError("El índice o sus archivos están incompletos; ejecutar --reconstruir-power-bi")
        if previous_day >= last_day:
            print(f"Exportación diaria: ya publicada hasta {previous_day}")
            return {"publicado": False, "cerrado_hasta": previous_day.isoformat()}
    first_day = previous_day + timedelta(days=1) if previous_day else None
    entries = [entry for entry in previous_entries if entry["fecha_chile"]]
    added_counts = {}
    # El directorio temporal pertenece a este repositorio y se elimina al terminar.
    # Solo se instalan las salidas cuando todos los CSV pasaron la validación.
    with TemporaryDirectory(prefix=".exportacion-powerbi-", dir=repo) as folder:
        stage = Path(folder)
        for spec in HISTORIES:
            new_entries, count = _export_history(repo, stage, spec, first_day, last_day, max_part_bytes)
            entries.extend(new_entries)
            added_counts[spec[0]] = count
        if not entries:
            raise ValueError("Todavía no hay observaciones de días cerrados para publicar")
        for source, source_path in (("dondecargo", "datos/estaciones.csv"), ("ministerio", "ministerio/datos/estaciones.csv")):
            fields, rows = read_csv(repo / source_path)
            relative = f"powerbi/{source}/estaciones.csv"
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            entries.append(entry_for_file(path, relative, f"{source}_estaciones", source, fields, len(rows)))
        entries.sort(key=lambda entry: (entry["tabla"], entry["fecha_chile"], int(entry["parte"] or 0)))
        stage_index = stage / "powerbi/archivos.csv"
        with stage_index.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(entries)
        totals = Counter()
        for entry in entries:
            totals[entry["tabla"]] += int(entry["filas"])
        state = dict(version=VERSION, generado_utc=now.astimezone(timezone.utc).isoformat(),
                     generado_chile=local_now.isoformat(), cerrado_hasta=last_day.isoformat(),
                     zona_horaria="America/Santiago", filas_por_tabla=dict(totals),
                     filas_nuevas=added_counts, archivos=len(entries),
                     nota_catalogos="Catálogos actuales al exportar; los historiales contienen solo días cerrados")
        stage_state = stage / "powerbi/estado_exportacion.json"
        stage_state.write_text(json.dumps(state, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        staged_paths = [stage / entry["ruta_relativa"] for entry in entries if (stage / entry["ruta_relativa"]).is_file()]
        # Índice y estado se instalan al final. El workflow solo publica si este paso terminó correctamente.
        for path in [*staged_paths, stage_index, stage_state]:
            destination = repo / path.relative_to(stage)
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return dict(state, publicado=True)
