let
    Datos = fxDatos("dondecargo_historial_conectores"),
    Tipos = Table.TransformColumnTypes(Datos, {
        {"station_id_vinculado", type text}, {"socket_id", type text}, {"site_id", type text},
        {"socket_record_id", type text}, {"es_providencia", Int64.Type}, {"maintenance", Int64.Type},
        {"observed_at", type datetimezone}, {"observed_at_cl", type datetimezone}, {"fecha_chile", type date},
        {"power", type number}, {"price", type number}, {"price_minute", type number}
    }, "en-US"),
    HoraChile = Table.TransformColumns(Tipos, {{"observed_at_cl", DateTimeZone.RemoveZone, type datetime}})
in
    HoraChile
