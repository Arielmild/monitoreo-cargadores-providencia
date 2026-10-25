# CSV diarios para Power BI Desktop

Los dos monitores conservan sus capturas habituales. Además, el workflow original ejecuta `python exportar_datos.py --power-bi --si-pendiente` después del intento de captura. La primera exportación correcta desde las **00:10 de America/Santiago** publica los días terminados hasta ayer. Aprovecha el cron-job existente; no depende del cron de GitHub ni necesita otro job externo.

El primer cierre incluye también los días anteriores que encuentre. En días posteriores agrega únicamente los días pendientes. Si el workflow estuvo detenido, recupera el cierre cuando vuelve a ejecutarse. La hora de exportación depende de que cron-job active el workflow original y el entorno se prepare correctamente. Un fallo al consultar la API de Dónde Cargo no impide exportar el historial ya existente. El margen de diez minutos permite que las últimas capturas del día anterior se guarden.

## Direcciones estables

- [Índice CSV de archivos publicados](https://raw.githubusercontent.com/Arielmild/monitoreo-cargadores-providencia/main/powerbi/archivos.csv).
- [Estado de la exportación](https://raw.githubusercontent.com/Arielmild/monitoreo-cargadores-providencia/main/powerbi/estado_exportacion.json).
- [Catálogo de estaciones de Dónde Cargo](https://raw.githubusercontent.com/Arielmild/monitoreo-cargadores-providencia/main/powerbi/dondecargo/estaciones.csv).
- [Catálogo de estaciones del Ministerio](https://raw.githubusercontent.com/Arielmild/monitoreo-cargadores-providencia/main/powerbi/ministerio/estaciones.csv).

El índice contiene las URLs de los CSV de detalle. Power Query lo lee y combina los archivos; no hay que cambiar la consulta ni añadir a mano una dirección por cada día nuevo. El índice no es la tabla de mediciones que se usa para graficar.

| Tabla de Power Query | Contenido |
| --- | --- |
| `DondeCargo_Estaciones` | Catálogo de estaciones de la primera fuente |
| `DondeCargo_HistorialEstaciones` | Cada observación del estado de una estación |
| `DondeCargo_HistorialConectores` | Cada observación del estado de un conector |
| `Ministerio_Estaciones` | Catálogo de estaciones del Ministerio |
| `Ministerio_HistorialConectores` | Cada observación del estado de un conector del Ministerio |

Los historiales mantienen todas las filas originales de los días cerrados, incluidos los estados desconocidos y fuera de línea. Se añaden `observed_at_cl` y `fecha_chile`, calculados desde el timestamp con zona horaria. Las fechas de partición se calculan en Chile, incluso para el historial original cuyos archivos de entrada se nombran por fecha UTC. Los cambios de horario de verano/invierno no necesitan ajustar el cron-job.

Los catálogos de estaciones son la versión disponible al hacer la exportación, no una reconstrucción de sus atributos a medianoche. `estado_exportacion.json` registra `cerrado_hasta`, las cantidades por tabla y el momento de publicación. El día actual se incorpora en el siguiente cierre; no es un tablero en tiempo real.

## Conectar una vez en Power BI Desktop

1. En Power BI Desktop, abre **Inicio → Transformar datos** para entrar en Power Query.
2. Selecciona **Nueva fuente → Consulta en blanco**.
3. Abre **Editor avanzado**, reemplaza todo por el contenido de [consultas/00_fxDatos.pq](consultas/00_fxDatos.pq) y pulsa **Listo**.
4. Nombra esa consulta exactamente **`fxDatos`**. Es una función auxiliar; no necesitas invocarla desde el formulario.
5. Crea una consulta en blanco por cada tabla que quieras usar. Pega en su Editor avanzado el archivo correspondiente de la carpeta [consultas/](consultas/), desde `01_...` hasta `05_...`. Usa como nombre de consulta el nombre de tabla de la tabla anterior.
6. Cuando Power BI solicite credenciales para `https://raw.githubusercontent.com`, selecciona **Anónimo**. Los archivos están en un repositorio público; no necesitan contraseña ni token de GitHub. Si solicita nivel de privacidad, estos datos públicos corresponden al nivel **Público**.
7. Comprueba las tablas y pulsa **Cerrar y aplicar**.
8. Construye los gráficos usando esas consultas. En días posteriores, **Inicio → Actualizar** incorporará todos los días nuevos que figuren en el índice.

Las consultas conservan los identificadores como texto para mantener ceros iniciales. Convierten los números con cultura `en-US`, que corresponde al punto decimal de los CSV. `observed_at_cl` se convierte a fecha/hora local de Chile sin que la zona horaria del computador cambie sus horas; `fecha_chile` es una fecha explícita para ejes y filtros diarios.

Para cargar solo un período, se puede usar el segundo parámetro de la función, por ejemplo:

```powerquery
fxDatos("ministerio_historial_conectores", #date(2026, 10, 24))
```

Ese filtro elige particiones a partir de la fecha indicada y reduce los archivos descargados. Dejarlo sin segundo parámetro carga todo el historial publicado.

## Relaciones sugeridas

- `DondeCargo_Estaciones[station_id]` → `DondeCargo_HistorialEstaciones[station_id]`, uno a muchos.
- `DondeCargo_Estaciones[station_id]` → `DondeCargo_HistorialConectores[station_id_vinculado]`, uno a muchos.
- `Ministerio_Estaciones[station_id]` → `Ministerio_HistorialConectores[station_id]`, uno a muchos.

Mantén las fuentes separadas hasta revisar una tabla de equivalencias entre sus ubicaciones. Sus identificadores no son intercambiables. Para analizar solo Providencia, usa el campo del catálogo correspondiente; en Dónde Cargo es una heurística de dirección y en el Ministerio procede de la comuna declarada.

Cada fila es una observación, no una sesión de carga. Para estimar utilización, pondera por el tiempo real entre observaciones y trata huecos, estados desconocidos y datos antiguos. Los estados `CHARGING`, `OCCUPIED`, etc. de Dónde Cargo y los estados normalizados del Ministerio requieren una definición común antes de compararlos. El primer día puede contener solo una fracción de la jornada si el monitoreo comenzó después de medianoche.

## Qué se actualiza automáticamente

La publicación de los CSV en GitHub ocurre automáticamente con el cierre diario. En **Power BI Desktop**, estas consultas de importación se actualizan al pulsar **Actualizar**; no hay un refresco programado nativo de este modelo. Cambiar un CSV en GitHub no refresca por sí solo un PBIX abierto o cerrado.

Si más adelante publicas el informe en Power BI Service, allí puedes configurar una actualización programada del modelo después del cierre diario. Las consultas usan una URL base fija y `RelativePath`, sin archivos locales. Esa conexión debe validarse en tu entorno y con tu licencia; no se configura ni se necesita Power BI Service para usar Desktop.

Referencias: [actualización en Desktop y Service](https://learn.microsoft.com/en-us/power-bi/connect-data/refresh-data), [conector Web para CSV](https://learn.microsoft.com/en-us/power-query/connectors/web/web), [actualización programada](https://learn.microsoft.com/en-us/power-bi/connect-data/refresh-scheduled-refresh).

## Operación y recuperación

```console
python exportar_datos.py --power-bi --si-pendiente
```

Fuera del horario de cierre, o si el cierre ya está hecho, termina sin volver a generar los CSV. Para reconstruir la publicación después de importar o corregir datos antiguos:

```console
python exportar_datos.py --power-bi --reconstruir-power-bi
```

La exportación local de SQLite y CSV consolidados sigue disponible con `python exportar_datos.py`, sin argumentos. Esos archivos de `exportaciones/` se mantienen fuera de Git. La publicación web está en `powerbi/` y no sube las bases SQLite.

Los CSV publicados se separan por día y, cuando hace falta, en partes de como máximo 45 MiB. Esto evita el [límite de 100 MiB por archivo de GitHub](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github). El repositorio total sigue creciendo con la campaña; la partición no elimina ese crecimiento ni hace infinito el almacenamiento.

Si la exportación falla, el workflow conserva la captura nueva del monitor, deja la ejecución marcada como fallida y reintenta el cierre en la siguiente activación. Los archivos de publicación de una exportación fallida no se agregan al commit. Una reconstrucción puede dejar partes antiguas sin referencias; Power BI solo lee las que aparecen en el índice actual.
