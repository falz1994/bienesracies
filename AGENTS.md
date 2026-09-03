# AGENTS.md — Sitio Bienes Raíces Managua

Sitio estático (Vercel) con el análisis de precios de vivienda de Managua. El pipeline de datos
vive en `/home/devni/analisis bienes raices/` (ver su AGENTS.md).

## Reglas

- **Vercel Root Directory = `docs`** (no cambiar la estructura: `docs/index.html` + `docs/data/` + `docs/slides/`).
  Deploy automático al pushear a `main` (push por SSH: `git@github.com:falz1994/bienesracies.git`).
- Deployment Protection (Vercel Authentication) puede bloquear visitas; se desactiva en el dashboard.
- Los datos los regenera `generar_datos.py` (lee CSVs del pipeline, dedupe ±110m + precio,
  filtro Managua + Ciudad Sandino + Ticuantepe, escribe `docs/data/{listados,stats,zonas}.json`
  y copia CSVs + slides). La fecha de extracción = mtime de los CSVs.
- `generar_programas_gobierno.py` → `docs/data/programas_gobierno.json` (coordenadas hardcodeadas
  de OSM/Overpass; NO re-geocodificar sin revisar porque Nominatim no conoce esos nombres).
- No commitear `geocache*.json` (en `.gitignore`).
- Probar local antes de pushear: `python3 -m http.server 8931` y Playwright contra
  `http://localhost:8931/docs/` (fetch falla en `file://`).

## Estructura

```
docs/index.html        sitio completo (mapa Leaflet, tablas, programas de gobierno)
docs/data/             listados.json, stats.json, zonas.json, programas_gobierno.json + CSVs
docs/slides/           9 PNGs TikTok
generar_datos.py       regenera docs/data desde el pipeline
generar_programas_gobierno.py
```

## Mapa (capas y parámetros)

- Capas: Heatmap, Clusters, Zonas, Cobertura agencias, Poco cubiertas, Urbanizaciones del Gobierno
- Heat suave: maxZoom 16, blur 15, minOpacity .1, peso log con ^1.15 (NO bajar maxZoom: satura rojo)
- Colores fuentes: KW #F2C14E · QuieroCasa #5B9BD5 · Momotombo #C9A0DC · Sovinic #FF8C42 · Gobierno #2DD4BF
- Controles en 3 grupos: Fuentes / Capas / Ajustes
