let
    Datos = fxDatos("dondecargo_historial_estaciones"),
    Tipos = Table.TransformColumnTypes(Datos, {
        {"station_id", type text}, {"es_providencia", Int64.Type},
        {"observed_at", type datetimezone}, {"observed_at_cl", type datetimezone}, {"fecha_chile", type date}
    }, "en-US"),
    HoraChile = Table.TransformColumns(Tipos, {{"observed_at_cl", DateTimeZone.RemoveZone, type datetime}})
in
    HoraChile
