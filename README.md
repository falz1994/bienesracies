# Bienes Raíces Managua — Análisis de precios de vivienda

Sitio web con el análisis de precios de casas en venta en el Área Metropolitana de Managua,
consolidando **tres fuentes inmobiliarias**:

| Fuente | Tipo de acceso | Coordenadas |
|---|---|---|
| [KW Nicaragua](https://kwnicaragua.kw.com) | API GraphQL pública | ✅ nativas |
| [QuieroCasa](https://www.quierocasa.com) | HTML server-rendered | ❌ geocodificadas (Nominatim) |
| [Momotombo](https://momotomborealestate.com) | WordPress/Houzez, HTML | ❌ geocodificadas (Nominatim) |

**Qué contiene el sitio (`docs/index.html`, raíz de Vercel = `docs`):**
- Mapa de calor interactivo (precio / densidad) con clusters y cuadrícula de zonas
- Filtros por fuente (KW / QuieroCasa / Momotombo)
- Top 10 zonas más caras y más baratas (por promedio de venta)
- Galería con los 9 slides del análisis
- Metodología, consideraciones (sesgo de selección) y oportunidades futuras

**Datos disponibles para uso dinámico (`data/`):**
- `data/listados.json` — 1,481 propiedades consolidadas: precio, lat/lng, zona, tipo,
  habitaciones, baños, m², URL del anuncio, imagen, fuente
- `stats.json` — estadísticas globales y por fuente (n, media, p25, p75, p5, p95)
- `zonas.json` — ranking de zonas caras/baratas (promedio, mediana, nº de listados)
- CSVs originales por fuente (`kw_listados_venta.csv`, `quierocasa_venta.csv`,
  `momotombo_venta.csv`)

**Regenerar datos:** `python3 generar_datos.py` (lee el pipeline en
`/home/devni/analisis bienes raices/`: `extraer_kw.py`, `extraer_quierocasa.py` +
`geocodificar_quierocasa.py`, `extraer_momotomborealestate.py` +
`geocodificar_momotomborealestate.py`).

**Notas:**
- Análisis del municipio de Managua + Ciudad Sandino + Ticuantepe (Nindirí excluido).
- Deduplicación entre portales: misma ubicación (±110 m) y precio similar.
- El dataset refleja el segmento formal del mercado (propiedades con agencia
  inmobiliaria); no incluye ventas entre particulares ni mercado informal.
- Análisis independiente con fines informativos. No constituye avalúo ni oferta.
