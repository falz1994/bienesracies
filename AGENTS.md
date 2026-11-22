# AGENTS.md — Bienes Raíces Managua (pipeline + sitio + histórico)

Proyecto único: **extracción → geocodificación → consolidación → publicación → histórico**.
Todo vive en este repo. El sitio (`docs/`) es lo único que Vercel publica.

## Reglas

- **Vercel Root Directory = `docs`** (no cambiar la estructura: `docs/index.html` + `docs/data/` +
  `docs/slides/`). Deploy automático al pushear a `main` por HTTPS
  (`https://github.com/falz1994/bienesracies.git`, credenciales vía `gh`).
  Deployment Protection (Vercel Authentication) puede bloquear visitas: se desactiva en el dashboard.
- **Contrato de rutas** (`pipeline/rutas.py`): los extractores y geocodificadores escriben y leen en
  `pipeline/datos/` (NO versionado); solo `pipeline/generar_datos.py` publica en `docs/`.
  Los scripts se ejecutan desde cualquier directorio (`python3 pipeline/extraer_kw.py`) porque
  cambiando a `pipeline/datos/` al arrancar; `run.sh` lo hace por todos.
- **Nunca** commitear `pipeline/datos/` (CSVs crudos, caches, `kw_listados.json`, slides en crudo).
- **No commitear `geocache*.json`** (viven en `pipeline/datos/` por el `.gitignore`).
- **Checkpoint de CSV**: los extractores de QuieroCasa/Momotombo/Sovinic reanudan desde su CSV si
  existe (dedup por id). En un refresco completo `run.sh` los aparta para que las propiedades
  retiradas desaparezcan del consolidado. KW y Discover sobrescriben siempre.
- **Nominatim**: máx 1 req/seg, `User-Agent` obligatorio, `countrycodes=ni`. No conoce las
  urbanizaciones nuevas del gobierno → usar **Overpass API** para esos nombres.
  Si hay entradas `null` viejas en el cache, borrarlas para re-consultar (`run.sh` lo hace).
- **Dedupe entre portales**: ≤110 m + precio a ≤3 % **y evidencia de que es el mismo inmueble**
  (m² a ≤5 % o lote a ≤5 % o programa completo igual). Sin evidencia se conservan ambos: las
  fuentes geocodificadas comparten el centroide del barrio y el dedupe antiguo (precio en el mismo
  millar) borraba casas distintas. Nunca se fusiona dentro del mismo portal (son unidades
  distintas del mismo proyecto: lotes #2, #3, #4…). Auditoría en `pipeline/datos/_dedupe_audit.json`.
  Orden de preferencia al fusionar: kw, qc, mb, sv, dn (se queda el primero).
- **Filtro territorial**: municipio de Managua + Ciudad Sandino + Ticuantepe. BBOX aproximado
  lat 11.98–12.26, lng −86.48 a −86.10 (Nindirí, Tipitapa, Mateare y Masaya quedan fuera).
- **Métrica principal = PROMEDIO** (así lo pidió el usuario). La mediana existe internamente y en el
  histórico, pero las tablas y slides usan promedio.
- **Sesgo de selección**: los portales son el mercado formal (agencias). Los promedios NO
  representan el precio real de todas las viviendas de Managua. Va explicado en el sitio y slides.
- **Slides**: `pipeline/generar_slides.py` borra `pipeline/datos/slides/` completa en cada corrida
  (por diseño) y `generar_datos.py` la copia a `docs/slides/`. Requiere Playwright/Chromium o
  `CHROME_PATH` con Chrome del sistema.
- **`generar_programas_gobierno.py`**: coordenadas hardcodeadas de OSM/Overpass.
  **NO re-geocodificar** sin revisar, porque Nominatim no conoce esos nombres.
- **Probar local antes de pushear**: `python3 -m http.server 8931` + navegador contra
  `http://localhost:8931/docs/` (los `fetch` fallan en `file://`),
  `python3 pipeline/verificar_sitio.py` y `./run.sh --validar`.

## Estructura

```
docs/                     sitio (Vercel Root Directory): index.html, data/, slides/, vercel.json
pipeline/rutas.py         rutas únicas (REPO, DATOS, PUB, SLIDES_OUT, HISTORY)
pipeline/extraer_*.py     5 extractores (KW, QuieroCasa, Momotombo, Sovinic, Discover)
pipeline/geocodificar_*.py 4 geocodificadores con cache por fuente
pipeline/extraer_distritos.py / extraer_barrios.py  polígonos OSM (Overpass)
pipeline/clasificador_casas.py + clasificar_casas.py  clasificación de "casa" compartida
pipeline/generar_datos.py consolidación → docs/data + copia CSVs, geojson y slides
pipeline/generar_programas_gobierno.py
pipeline/generar_slides.py 9 PNG 1080×1920
pipeline/historial.py     snapshots, diffs y serie docs/data/historico.json
pipeline/analisis_cambios.py  informe de cambios (portal vs dataset, precios por barrio)
pipeline/cruzar_fuentes.py  misma propiedad en varios portales + diferencia de precio
pipeline/verificar_sitio.py   verificación del sitio servido por HTTP
pipeline/validar_datos.py invariantes; corta el run si algo no cuadra
pipeline/datos/           datos de trabajo (gitignored)
history/                  snapshots/ + diffs/ versionados (análisis de cambios)
run.sh                    orquestador
```

## Fuentes de datos

| Fuente | Acceso | Coordenadas | Extractor | Geocodificador |
|---|---|---|---|---|
| kwnicaragua.kw.com | API GraphQL `graph.prod.consumer.kw.com` (`ListingSearch`, `first` hasta 300, `after` pagina) | ✅ nativas (`geometry.coordinates` = `[lng, lat]`) | `extraer_kw.py` | — |
| quierocasa.com | HTML server-rendered (`/resultados/venta-propiedades.htm`, paginación real = total/10) | ❌ por zona del título | `extraer_quierocasa.py` | `geocodificar_quierocasa.py` |
| momotomborealestate.com | WordPress/Houzez (`/search-result-page/?type[]=family-home`, `/page/N/`) | ❌ por título | `extraer_momotomborealestate.py` | `geocodificar_momotomborealestate.py` |
| sovinic.com.ni | WordPress/Elementor (`/resultados-de-busqueda/`, `data-listid=`; ubicación del slug) | ❌ por slug + municipio | `extraer_sovinic.py` | `geocodificar_sovinic.py` |
| discovernica.com | API JSON `POST /properties/filter` (devuelve todo en una llamada; sin coords ni dirección) | ❌ por zona del título | `extraer_discovernica.py` | `geocodificar_discovernica.py` |

Caches por fuente en `pipeline/datos/geocache_*.json`; el geocodificador de Discover acepta solo
resultados dentro del BBOX (sin hint, Nominatim manda "Santo Domingo" a Chontales).

## Pipeline (orden de ejecución)

```bash
./run.sh                 # todo (recomendado)
```

Equivalente manual:

```bash
python3 pipeline/extraer_kw.py && python3 pipeline/clasificar_casas.py
python3 pipeline/extraer_quierocasa.py && python3 pipeline/geocodificar_quierocasa.py
python3 pipeline/extraer_momotomborealestate.py && python3 pipeline/geocodificar_momotomborealestate.py
python3 pipeline/extraer_sovinic.py && python3 pipeline/geocodificar_sovinic.py
python3 pipeline/extraer_discovernica.py && python3 pipeline/geocodificar_discovernica.py
python3 pipeline/generar_datos.py
python3 pipeline/historial.py --snapshot --diff --serie
python3 pipeline/validar_datos.py
```

## Histórico (cambios entre extracciones)

- `history/snapshots/<fecha>.json` — un registro por `fuente:id` con precio, m², lote, zona,
  distrito, flag de casa y coordenadas a 4 decimales. ~200 KB por extracción.
- `history/diffs/<fecha>.json` — nuevos, retirados, variación de precio de los comunes
  (subieron/bajaron/iguales, mediana, p25/p75, mayor subida y bajada), por portal y por zona.
- `docs/data/historico.json` — serie para el sitio (`ultimo_cambio` con el detalle del último diff).
- Baseline: tag git `datos-2026-09-03` (estado consolidado del 3 de septiembre de 2026).
- `--desde-git <sha>` reconstruye un snapshot de cualquier commit para backfill.
- `pipeline/analisis_cambios.py` genera `history/analisis-<fecha>.md` con el desglose por portal
  (salieron del portal vs salieron del dataset) y precio por barrio.

## Mapa del sitio (`docs/index.html`)

- Capas toggleables: Heatmap (peso precio/densidad), Clusters, Zonas, Cobertura agencias,
  Zonas poco cubiertas, Urbanizaciones del Gobierno.
- Heat suave: `maxZoom:16`, blur 15, `minOpacity:.1`, peso log p5–p95 con `^1.15`
  (no bajar `maxZoom`: satura rojo por acumulación).
- Colores por fuente: KW `#F2C14E` · QuieroCasa `#5B9BD5` · Momotombo `#C9A0DC` ·
  Sovinic `#FF8C42` · Discover `#D65DB1` · Gobierno `#2DD4BF`.
- Controles en 3 grupos: Fuentes / Capas / Ajustes. Toggle "Solo casas" (usa el flag `casa`).
- Agrupación por barrio (OSM) o distrito (I–VII) en mapa y tablas.
- Sección **Histórico**: serie de extracciones, altas/bajas por portal y variación mediana de precio.
