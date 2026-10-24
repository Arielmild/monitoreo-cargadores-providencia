# Monitor de cargadores públicos del Ministerio

Consulta de solo lectura a [cargadorespublicos.cl/api/data](https://cargadorespublicos.cl/api/data), independiente del monitor de Dónde Cargo que existe en la raíz del repositorio.

## Integración y ejecución

El workflow está en `/.github/workflows/ministerio.yml` y aparece en Actions como **Monitoreo Ministerio - Providencia**. Ejecuta una sola captura en los minutos UTC 04, 09, 14, …, 59 de cada hora. El otro monitor solicita sus capturas en los minutos 02, 07, 12, …, 57. Las ejecuciones de ambas fuentes son independientes; una falla no detiene a la otra.

Cada monitor tiene su propio grupo de concurrencia. Ambos pueden ejecutar consultas en paralelo. Sus commits solo incluyen sus respectivas carpetas de datos; si la rama avanzó mientras se hacía una captura, el guardado intenta un rebase antes de reintentar el push. Las marcas de captura permiten comparar los instantes efectivos, que no son simultáneos.

GitHub puede retrasar u omitir disparos programados. El workflow solo recolecta en este repositorio de Arielmild mientras sea público, con un runner estándar. No requiere tokens personales ni modificar los permisos generales de Actions: declara `contents: write` en su propio YAML. Una copia en otra cuenta requiere ajustar la condición del workflow.

Se ejecuta al subir cambios en su código o workflow, y manualmente desde **Actions → Monitoreo Ministerio - Providencia → Run workflow → main**. Los commits en `ministerio/datos/` no provocan una nueva ejecución.

## Qué se guarda

| Archivo | Contenido |
| --- | --- |
| `ministerio/datos/AAAA-MM-DD.csv` | Historial de conectores; el nombre del archivo usa la fecha de Chile |
| `ministerio/datos/estaciones.csv` | Catálogo actual de estaciones con comuna declarada por la fuente |
| `ministerio/datos/estado_monitor.json` | Hora de captura, cantidades y distribución de estados/comunas |

Los datos del primer monitor siguen en `/datos/`. No se comparten CSV ni bases SQLite entre las fuentes. El script calcula su ruta de salida desde su propio archivo, por lo que también funciona al invocarlo desde la raíz.

Solo se exportan los campos de seguimiento necesarios; no se guarda la respuesta completa de la API, que incluye otros datos administrativos y contactos. No hace falta configurar `MAPEO_JSON`.

## Interpretación de la fuente

La API entrega una lista de ubicaciones (`location_id`). Cada una contiene equipos `evses` y cada equipo contiene `connectors`. El monitor recorre ambos niveles. Usa el estado del **conector**, que puede diferir del estado del EVSE; conserva ambos en `status_raw` y `evse_status_raw`.

`connector_key` combina los identificadores originales de ubicación, EVSE y conector. No depende del orden en la respuesta. `power_kw` contiene la potencia máxima declarada del conector; no es una estimación de potencia consumida. Las tarifas se conservan como `tariffs_json`: no se reducen a un precio único porque pueden tener varios componentes.

El alcance predeterminado es el mismo rectángulo del primer monitor: latitud [-33.4560, -33.4080], longitud [-70.6380, -70.5820]. Incluye zonas de comunas vecinas. Aquí `es_providencia` se obtiene de la igualdad de `commune` con Providencia, sin inferirla a partir del nombre de una avenida. Si la comuna falta, se deja vacío. Los registros sin coordenadas no se incluyen porque no se puede confirmar que estén dentro del rectángulo.

Para exigir además comuna Providencia, agrega `--solo-providencia` al comando de captura del workflow, o define `SOLO_PROVIDENCIA=1` en su entorno. Eso cambia el alcance respecto de la configuración actual del primer monitor.

`observed_at` es el momento UTC al terminar la descarga; `observed_at_cl` representa ese mismo instante en America/Santiago. `source_updated_at` procede primero del conector, luego del EVSE o, si ambos carecen de fecha, de la ubicación. `source_updated_at_level` identifica ese nivel. Esta fecha no demuestra que el estado del conector se haya actualizado en ese instante. También se conserva `location_updated_at`.

`connected_to_electrical_grid` describe conexión a la red eléctrica según la fuente; no indica conectividad de comunicaciones. `api_updates_enabled` tampoco garantiza que los estados estén actualizados. `FUERA_DE_LINEA` no equivale por sí solo a avería ni a ocupación. Los estados no reconocidos se conservan en bruto y se normalizan como `DESCONOCIDO`.

Las fuentes tienen catálogos e identificadores diferentes: comparar cantidades no basta para identificar la misma estación. Para análisis conjunto hace falta construir y revisar una tabla de correspondencia de ubicaciones y conectores.

## Uso local y SQLite

Desde la raíz del repositorio:

```console
python -m pip install -r ministerio/requirements.txt
python ministerio/monitor_providencia.py --inspeccionar
python ministerio/monitor_providencia.py
python ministerio/a_sqlite.py
```

La última instrucción genera `ministerio/monitoreo_ministerio.db` con `estaciones` e `historial_conectores`. No modifica la base del primer monitor. Repetir la exportación reconstruye la base sin duplicar filas. La base SQLite se ignora en Git; los CSV diarios son el historial que se publica.

Desde la carpeta `ministerio/` se ejecutan las pruebas sin conexión:

```console
python -m unittest discover -s tests -v
```

El workflow comprueba el parser y el almacenamiento antes de consultar la API. Una descarga fallida, un esquema incompatible o una selección vacía produce una ejecución fallida sin publicar un commit de datos nuevos.
