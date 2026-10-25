let
    Datos = fxDatos("ministerio_estaciones"),
    Tipos = Table.TransformColumnTypes(Datos, {
        {"station_id", type text}, {"es_providencia", Int64.Type}, {"n_conectores", Int64.Type},
        {"latitude", type number}, {"longitude", type number}, {"max_power_kw", type number}
    }, "en-US")
in
    Tipos
