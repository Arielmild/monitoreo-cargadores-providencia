// Crear una consulta en blanco, pegar en Editor avanzado y nombrarla fxDatos.
(NombreTabla as text, optional Desde as nullable date) as table =>
let
    Prefijo = "Arielmild/monitoreo-cargadores-providencia/main/",
    LeerCSV = (Ruta as text) as table =>
        Table.PromoteHeaders(
            Csv.Document(
                Web.Contents("https://raw.githubusercontent.com", [RelativePath = Prefijo & Ruta]),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
            ),
            [PromoteAllScalars = true]
        ),
    Indice = LeerCSV("powerbi/archivos.csv"),
    Archivos = Table.SelectRows(
        Indice,
        each [tabla] = NombreTabla and
            (Desde = null or [fecha_chile] = "" or [fecha_chile] >= Date.ToText(Desde, "yyyy-MM-dd", "en-US"))
    ),
    Rutas = if Table.IsEmpty(Archivos)
        then error "No hay archivos publicados para esta tabla y período. Revisa powerbi/estado_exportacion.json."
        else Archivos[ruta_relativa],
    Combinada = Table.Combine(List.Transform(Rutas, each LeerCSV(_))),
    SinVacios = Table.ReplaceValue(Combinada, "", null, Replacer.ReplaceValue, Table.ColumnNames(Combinada))
in
    SinVacios
