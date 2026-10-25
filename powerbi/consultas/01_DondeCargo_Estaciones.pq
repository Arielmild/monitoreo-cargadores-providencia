let
    Datos = fxDatos("dondecargo_estaciones"),
    Tipos = Table.TransformColumnTypes(Datos, {
        {"station_id", type text}, {"es_providencia", Int64.Type},
        {"latitude", type number}, {"longitude", type number}, {"power_kw", type number},
        {"is_fast", Int64.Type}, {"min_price", type number}
    }, "en-US")
in
    Tipos
