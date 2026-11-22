# Bienes Raíces Managua — análisis de precios de vivienda

Un solo proyecto: **pipeline de extracción + sitio estático + histórico de datos**.
Consolida cuatro portales inmobiliarios y una corredora más, geocodifica, deduplica y publica
un análisis de precios de casas en venta en el Área Metropolitana de Managua.

| Fuente | Acceso | Coordenadas |
|---|---|---|
| [KW Nicaragua](https://kwnicaragua.kw.com) | API GraphQL pública | ✅ nativas |
| [QuieroCasa](https://www.quierocasa.com) | HTML server-rendered | ❌ geocodificadas (Nominatim) |
| [Momotombo](https://momotomborealestate.com) | WordPress/Houzez, HTML | ❌ geocodificadas (Nominatim) |
| [Sovinic](https://www.sovinic.com.ni) | WordPress/Elementor, HTML | ❌ geocodificadas (Nominatim) |
| [Discover Real Estate](https://discovernica.com) | API JSON pública | ❌ geocodificadas (Nominatim) |

Sitio publicado: **https://bienesracies.vercel.app** (Vercel, Root Directory = `docs`).

## Qué hay en el repositorio

```
docs/                  sitio estático (lo único que Vercel publica)
docs/data/             JSON del sitio + CSVs de descarga + geojson de OSM
docs/slides/           9 PNG verticales (1080×1920) del análisis
docs/vercel.json       headers de cache para data/ y slides/
pipeline/              extractores, geocodificadores y scripts de análisis
pipeline/datos/        datos de trabajo (CSVs crudos, caches, slides sin publicar) — NO se versiona
history/               snapshots y diffs versionados para análisis de cambios históricos
run.sh                 orquestador del refresco
```

## Datos publicados (`docs/data/`)

- `listados.json` — propiedades consolidadas: precio, lat/lng, zona, distrito, tipo,
  habitaciones, baños, m², URL del anuncio, imagen, fuente y flag `casa`.
- `stats.json` — estadísticas globales y por fuente (n, media, p25, p75, p5, p95) + fecha de extracción.
- `zonas.json` — ranking de zonas caras/baratas (promedio, mediana, nº de listados).
- `historico.json` — serie de extracciones con altas, bajas y variación de precios.
- `programas_gobierno.json` — urbanizaciones del Gobierno con coordenadas OSM/Overpass.
- CSVs por fuente (descarga) y `distritos_managua.geojson` / `barrios_managua.geojson`.

## Refrescar los datos

```bash
./run.sh                # refresco completo: extraer → geocodificar → publicar → histórico → validar
./run.sh --extract      # solo extracción (con guarda de regresión por fuente)
./run.sh --datos        # solo consolidación + histórico + validación
./run.sh --slides       # solo slides
./run.sh --validar      # solo validación
```

Qué hace el refresco completo:

1. **Backup** de los CSV de trabajo en `pipeline/datos/_backup_<fecha>/` y limpieza de los
   checkpoints de reanudación (así desaparecen las propiedades retiradas de los portales).
2. **Purga** de entradas `null` en `geocache_*.json` para reintentar geocodificaciones fallidas.
3. **Extracción** de las 5 fuentes con guarda: si una fuente devuelve menos del 70 % de las filas
   anteriores, se restaura su backup y se avisa (cambio de HTML/API o bloqueo).
4. **Geocodificación** con Nominatim (1 req/s, `countrycodes=ni`) y caches por fuente.
5. **Consolidación** (`pipeline/generar_datos.py`): dedupe entre portales ±110 m + precio en el
   mismo millar, filtro Managua + Ciudad Sandino + Ticuantepe, asignación de distrito y barrio OSM.
6. **Histórico**: snapshot del día, diff contra la extracción anterior y serie `historico.json`.
7. **Slides** (opcional si hay Playwright/Chromium) y **validación** de invariantes.

Requisitos: Python 3 (extracción y geocodificación usan solo la biblioteca estándar) y, para los
slides, Playwright (`pip install -r requirements.txt`) o Chrome del sistema
(`CHROME_PATH=/usr/bin/google-chrome ./run.sh --slides`).

## Histórico de cambios

Cada extracción deja `history/snapshots/<fecha>.json` (~200 KB, un registro por anuncio con
precio, m², lote, zona, distrito y flag de casa) y `history/diffs/<fecha>.json` con:

- anuncios **nuevos** y **retirados** (por id de portal, así se distingue "no está" de "lo movieron");
- variación de precio de los anuncios que siguen publicados (subieron/bajaron/iguales, mediana, p25/p75);
- desglose por portal y por zona.

```bash
python3 pipeline/historial.py --snapshot          # snapshot de la extracción actual
python3 pipeline/historial.py --diff              # compara los dos últimos snapshots
python3 pipeline/historial.py --serie             # regenera docs/data/historico.json
python3 pipeline/historial.py --desde-git <sha>   # reconstruye un snapshot de un commit
python3 pipeline/analisis_cambios.py --md history/analisis-<fecha>.md
```

`analisis_cambios.py` cruza los snapshots con los CSV crudos de cada portal para separar los avisos
que **salieron del portal** de los que solo **salieron del dataset** (filtro o dedupe), y compara la
mediana de precio de cada barrio entre ambas fechas.

El sitio muestra la serie y el último cambio en la sección **Histórico**.

## Deploy

- **Vercel Root Directory = `docs`** (configurado en el dashboard; el repo no lo puede fijar).
  El push a `main` dispara el deploy automático.
- `docs/vercel.json` fija cache: `data/` siempre revalida (los refrescos se ven al instante),
  `slides/` 1 h, HTML sin cache.
- `.vercelignore` excluye `pipeline/`, `history/` y `run.sh` por si se deploya con la CLI.
- Probar local antes de pushear: `python3 -m http.server 8931` y abrir
  `http://localhost:8931/docs/` (los `fetch` fallan en `file://`).
  `python3 pipeline/verificar_sitio.py` comprueba automáticamente datos, mapa y sección Histórico.

## Notas metodológicas

- Análisis del municipio de Managua + Ciudad Sandino + Ticuantepe (Nindirí excluido).
- Deduplicación entre portales: misma ubicación (±110 m) y precio similar → una sola fila,
  se queda la primera según el orden kw, qc, mb, sv, dn.
- El dataset refleja el **segmento formal** (propiedades con agencia inmobiliaria); no incluye
  ventas entre particulares ni mercado informal. Los promedios no representan todo el mercado.
- Análisis independiente con fines informativos. No constituye avalúo ni oferta.
