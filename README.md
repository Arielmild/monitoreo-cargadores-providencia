# Monitoreo de cargadores de Providencia

Capturas automáticas de la API pública utilizada por [Dónde Cargo](https://dondecargo.cl/), mediante GitHub Actions. No requiere mantener un computador encendido ni instalar dependencias de Python.

## Consultar o descargar los datos

- [Última captura y estados](datos/estado_monitor.json).
- [Catálogo actual de estaciones](datos/estaciones.csv).
- [Historial diario](datos/): carpetas `AAAA/MM/` con `historial_estaciones_AAAA-MM-DD.csv` e `historial_conectores_AAAA-MM-DD.csv`.
- [Ejecuciones y errores](../../actions/workflows/monitoreo.yml).

Para descargar todo, usa **Code → Download ZIP** en la página del repositorio. Para descargar un CSV, abre el archivo y usa **Download raw file**. Los CSV se guardan en UTF-8 y usan coma como separador; en Excel se pueden importar desde **Datos → Desde texto/CSV**.

Con Python 3.11 o superior, descomprime el ZIP, abre una terminal en esa carpeta y ejecuta:

```console
python exportar_datos.py
```

Esto crea en `exportaciones/`:

- `monitoreo_providencia.db`, con las tablas `estaciones`, `historial_estaciones` e `historial_conectores`.
- `estaciones.csv`, `historial_estaciones.csv` e `historial_conectores.csv`, consolidados para Excel o Pandas. Estos CSV incluyen BOM para facilitar su apertura en Excel.

La exportación puede repetirse sin duplicar datos. SQLite se genera al descargar: el repositorio conserva CSV diarios como fuente del historial para evitar guardar versiones de un binario creciente cada cinco minutos. No se utilizan artefactos de Actions ni cachés de pago para conservar el historial.

## Frecuencia, costo y controles

El workflow `Monitoreo Cargadores Providencia` está programado cada cinco minutos, en los minutos UTC 02, 07, 12, …, 57 de cada hora. También se ejecuta al actualizar el monitor y con **Actions → Monitoreo Cargadores Providencia → Run workflow**. Los cambios automáticos en `datos/` no disparan otro ciclo.

Se usa un runner estándar `ubuntu-latest` en un repositorio público. GitHub establece que [estas ejecuciones son gratuitas](https://docs.github.com/en/billing/concepts/product-billing/github-actions). No se configuran servicios pagados. El monitor se omite si el repositorio se vuelve privado o se ejecuta en una copia de otra cuenta.

GitHub [puede retrasar u omitir ejecuciones programadas](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): cinco minutos es la frecuencia solicitada, no una garantía. En repositorios públicos puede desactivar el cron después de 60 días sin actividad; si ocurre, se reactiva desde Actions. No se añade un mecanismo artificial para eludir esa política.

Para detener la captura: **Actions → Monitoreo Cargadores Providencia → menú ⋯ → Disable workflow**. Los datos existentes se conservan. Para reanudar: **Enable workflow**.

Las ejecuciones no se solapan. El bot guarda primero un commit y luego realiza cualquier rebase necesario, evitando el error de intentar un rebase con cambios pendientes. Los fallos de consulta, la paginación inconsistente o una captura sin estaciones/conectores terminan con error antes de escribir datos. El guardado remoto de los CSV y el resumen ocurre en un mismo commit.

## Alcance de los datos

La consulta usa el rectángulo original: latitud entre -33.4560 y -33.4080; longitud entre -70.6380 y -70.5820. Incluye bordes y estaciones de comunas vecinas. **No representa un recorte por el límite administrativo oficial de Providencia.**

`es_providencia` es una heurística de texto sobre la dirección: `1` si menciona Providencia, `0` si menciona una comuna vecina y vacío si no puede inferirse. El nombre de una avenida puede inducir una clasificación incorrecta; este campo no confirma la comuna.

Los conectores se vinculan por igualdad de identificadores (`site_id`, UUID, identificador EVX, nombre o identificador Copec), siempre que haya una sola estación candidata. `metodo_vinculacion` documenta la coincidencia. Se rechazan vínculos ambiguos y coincidencias por fragmentos: `ocpp-7` no coincide con `ocpp-77`. `socket_record_id` es la clave del registro de la API y permite distinguir conectores cuyos `socket_id` se repiten entre proveedores. El resumen enumera estaciones sin conectores vinculados; la cobertura de conectores puede ser menor que la cobertura de estaciones.

`observed_at` es el instante UTC al completar la consulta; `updated_at` y `last_upserted_at` son las marcas de actualización entregadas por la fuente. Las consultas de distintas páginas no constituyen una instantánea transaccional de la API. Una captura reciente puede contener estados antiguos: conserva y revisa ambas marcas para detectar información desactualizada.

Los estados son los informados por la fuente, no una medición de energía, demanda eléctrica o sesiones completas. Los estados faltantes se guardan como `UNKNOWN`. Para estimar utilización, usa los intervalos reales entre observaciones y trata explícitamente huecos, estados desconocidos y datos antiguos.

La base del monitor local anterior se conserva en el computador y no se importa automáticamente: su algoritmo aceptaba coincidencias parciales que requieren revisión antes de incorporarlas al análisis.

## Configuración y pruebas

`config.json` contiene los límites geográficos y la clave **pública de rol `anon`** de la aplicación consultada. No contiene una clave administrativa `service_role`, credenciales personales ni un token de GitHub. La clave pública no concede más acceso que el que la API permite a visitantes anónimos. El código solo realiza solicitudes GET; no crea usuarios ni sesiones anónimas. Si el proveedor modifica la API o la clave, habrá que actualizar la configuración. También admite las variables de entorno `SUPABASE_URL` y `SUPABASE_ANON_KEY`.

Para una captura manual local:

```console
python monitor_cloud.py
```

Para comprobar vinculación, paginación, fallos de consulta y exportación sin red:

```console
python -m unittest discover -s tests -v
```

`Verificar monitor` ejecuta esas pruebas al modificar el código o abrir una solicitud de cambios. El workflow de recolección solo escribe en `datos/` con el `GITHUB_TOKEN` temporal de Actions; no requiere configurar secretos personales.
