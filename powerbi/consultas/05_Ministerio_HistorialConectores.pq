let
    Datos = fxDatos("ministerio_historial_conectores"),
    Tipos = Table.TransformColumnTypes(Datos, {
        {"station_id", type text}, {"connector_key", type text}, {"connector_id", type text},
        {"evse_uid", type text}, {"evse_id", type text},
        {"observed_at", type datetimezone}, {"observed_at_cl", type datetimezone}, {"fecha_chile", type date},
        {"power_kw", type number}, {"connected_to_electrical_grid", Int64.Type}, {"api_updates_enabled", Int64.Type}
    }, "en-US"),
    HoraChile = Table.TransformColumns(Tipos, {{"observed_at_cl", DateTimeZone.RemoveZone, type datetime}})
in
    HoraChile
