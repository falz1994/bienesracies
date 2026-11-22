# Histórico de datos

Un **snapshot** por extracción y un **diff** contra la extracción anterior. Todo versionado,
así los cambios del mercado quedan auditables commit a commit.

## Snapshots (`snapshots/<fecha>.json`)

```json
{
  "v": 1,
  "fecha": "2026-11-21",
  "generado": "2026-11-21T22:48:00",
  "origen": "extraccion",
  "stats": { "global": {...}, "casas": {...}, "kw": {...} },
  "n": 1577,
  "l": {
    "kw:123456": {"p": 250000, "m": 180, "l": 300, "z": "Las Colinas",
                  "d": "Distrito III", "c": 1, "a": 12.1006, "o": -86.2843}
  }
}
```

| Clave | Significado |
|---|---|
| `p` | precio USD |
| `m` / `l` | m² construidos / lote |
| `z` / `d` | zona (barrio OSM) / distrito |
| `c` | 1 si el clasificador lo considera casa |
| `a` / `o` | latitud / longitud a 4 decimales (~11 m) |

La clave es `fuente:id` (`kw`, `qc`, `mb`, `sv`, `dn` + id del portal), así un anuncio se puede
seguir entre extracciones aunque cambie de precio o de zona asignada.

## Diffs (`diffs/<fecha>.json`)

- `nuevos` / `retirados`: ids que aparecieron o dejaron de aparecer en el consolidado.
- `precio`: sobre los avisos con precio en ambas fechas → `subieron`, `bajaron`, `iguales`,
  `pct_cambiaron`, `mediana_pct_cambios`, `p25/p75`, atípicos y mayor subida/bajada.
- `por_fuente`: altas, bajas y cambios de precio por portal.
- `por_zona`: las 25 zonas con más movimiento.

`analisis_cambios.py` produce un tercer informe (`diffs/analisis-<fecha>.json` +
`analisis-<fecha>.md`) que cruza los snapshots con los **CSV crudos** de cada portal y con el
backup de los anteriores, para distinguir:

- avisos que **salieron del portal** (dejaron de publicarse);
- avisos que siguen en el portal pero **salieron del dataset** (filtro territorial o dedupe);
- precio por barrio comparando la mediana de la zona en ambas fechas.

## Comandos

```bash
python3 pipeline/historial.py --snapshot            # snapshot del día
python3 pipeline/historial.py --diff                # diff contra el anterior
python3 pipeline/historial.py --serie               # docs/data/historico.json
python3 pipeline/historial.py --desde-git <sha>     # snapshot reconstruido de un commit
python3 pipeline/analisis_cambios.py --md history/analisis-<fecha>.md
```

## Baseline

- `snapshots/2026-09-03.json` — estado consolidado del 3 de septiembre de 2026, reconstruido desde
  el commit `e51f919` (tag `datos-2026-09-03`).
- Los commits intermedios de septiembre (Sep 3, 5 y 6) son cambios de **esquema** (flag `casa`,
  Discover, barrios OSM), no extracciones de mercado: no se backfillean para no falsear la serie.
  Si hace falta, `--desde-git <sha>` los reconstruye.
