"""Genera slides TikTok (1080x1920) estilo 'Canasta Basica Frijol'.

Modos:
  python3 generar_slides.py            → CONSOLIDADO: KW + QuieroCasa + Momotombo + Sovinic, solo casas
  python3 generar_slides.py casas      → casas (universo expandido KW, clasificador)

Salida en carpeta slides/ (se borra y regenera completa en cada corrida).
Orden: cada gráfico va seguido de su slide de interpretación:
  01 mapa de calor → 02 interpretación
  03 zonas caras   → 04 interpretación
  05 zonas baratas → 06 interpretación
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import asyncio
import collections
import csv
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import urllib.request

import rutas  # noqa: E402
from clasificador_casas import kw_es_casa, qc_es_casa, mb_es_casa, sv_es_casa, dn_es_casa

OUT = "slides"
BBOX = {"s": 12.0, "n": 12.26, "o": -86.48, "e": -86.10}
BG = "#0D1526"
AMARILLO = "#F2C14E"
AZUL = "#5B9BD5"
ROJO = "#E15759"
TXT = "#F0F3FA"
GRIS = "#8B95AB"

NOMBRES = {"Nindiri": "Nindirí"}
CIUDADES = {"managua", "nindiri", "nindirí", "ticuantepe", "tipitapa", "ciudad sandino",
            "el crucero", "masaya", "mateare", "jinotega", "diriamba", "san rafael del sur"}
MUNI_ZONAS = {"nindiri", "nindirí", "tipitapa", "mateare", "el crucero",
              "masaya", "san rafael del sur"}
RE_RECHAZO = re.compile(r"^(kms?|kil[oó]metro|carretera|avenida|ave\.?|calle|pista|contiguo|"
                        r"costado|entrada|frente|rotonda|sem[aá]foro|de |del |donde|\d)", re.I)
RE_BARRIO_KW = re.compile(r"^(bo\.?\s*|barrio|reparto|residencial|urb\.?\s*|urbanizaci[oó]n|"
                          r"colonia|villas?\b|villa\b|etapa|lomas|altos|praderas|jardines|"
                          r"jard[ií]n)", re.I)

CASAS = "casas" in sys.argv
SUFIJ = "_casas" if CASAS else ""


def fmt_k(n):
    if n >= 1_000_000:
        s = f"{n/1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"${s}M"
    if n >= 1_000:
        return f"${n/1_000:,.0f}k"
    return f"${n:,.0f}"


MENORES = {"de", "del", "la", "las", "los", "y", "en", "a", "al"}


def title_es(s):
    palabras = s.lower().split()
    out = []
    for i, w in enumerate(palabras):
        base = w.rstrip("….,.-")
        suf = w[len(base):]
        out.append((base if (i > 0 and base in MENORES) else base.capitalize()) + suf)
    return " ".join(out)


def limpia(s):
    s = NOMBRES.get(s, s).strip()
    if "|" in s:
        s = max(s.split("|"), key=lambda x: len(x.strip()))
    if "#" in s:
        left, right = (x.strip(" ,.-") for x in s.split("#", 1))
        kw = lambda x: bool(x) and x.lower().startswith(("reparto", "residencial", "urbanizaci",
                                                         "colonia", "barrio", "km ", "bo."))
        if kw(left):
            s = left
        elif kw(right):
            s = right
        elif left and len(left) >= 8 and not any(c.isdigit() for c in left):
            s = left
        else:
            s = max([left, right], key=len)
    s = re.sub(r"\s*\d+(\.\d+)?\s*kms?\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s+\d+\s*(mts?|metros|varas|cuadras)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s+\d+\s*(and\.?|ave\.?|av\.?|c\.|calle|cuadra)\b.*$", "", s, flags=re.I)
    s = s.strip(" ,.-#")
    if len(s) > 30:
        s = s[:30]
        s = s[:s.rfind(" ")].rstrip(" .,") + "…"
    return s


def _geobarrio(lat, lng):
    cache_f = str(rutas.dato("geocache.json"))
    cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
    k = f"{lat:.4f},{lng:.4f}"
    if k in cache:
        return cache[k]
    try:
        url = (f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}"
               f"&format=jsonv2&addressdetails=1&zoom=17&accept-language=es")
        req = urllib.request.Request(url, headers={"User-Agent": "analisis-managua/1.0"})
        a = json.load(urllib.request.urlopen(req, timeout=20)).get("address", {})
    except Exception:
        return None
    nombre = None
    for campo in ("neighbourhood", "quarter", "suburb", "borough", "city_district",
                  "hamlet", "village", "town"):
        if a.get(campo) and a[campo].lower() != "managua":
            nombre = a[campo]
            break
    cache[k] = nombre
    with open(cache_f, "w") as f:
        json.dump(cache, f, ensure_ascii=False)
    time.sleep(1.1)
    return nombre


def _candidato_barrio(seg):
    s = NOMBRES.get(seg.strip(), seg.strip())
    low = s.lower()
    if not low or low in CIUDADES:
        return None
    for pref in ("managua ", "nindiri ", "nindirí ", "ticuantepe "):
        if low.startswith(pref):
            s, low = s[len(pref):], low[len(pref):]
    if not low or low in CIUDADES or RE_RECHAZO.match(low):
        return None
    if "#" in s:
        s = s.split("#")[0].strip(" ,.-")
    return s or None


def nombre_zona_de_items(items, fallback):
    fuertes, debiles = collections.Counter(), collections.Counter()
    for it in items:
        cand = _candidato_barrio((it["dir"] or "").split(",")[0])
        if not cand:
            continue
        cand = limpia(cand)
        if RE_BARRIO_KW.match(cand.lower()):
            fuertes[cand] += 1
        elif not any(ch.isdigit() for ch in cand) and len(cand.split()) <= 4:
            debiles[cand] += 1
    if fuertes:
        return title_es(fuertes.most_common(1)[0][0])
    if debiles:
        return title_es(debiles.most_common(1)[0][0])
    geo = _geobarrio(sum(it["lat"] for it in items) / len(items),
                     sum(it["lng"] for it in items) / len(items))
    return title_es(geo) if geo else title_es(fallback)


MANAGUA_OK = {"managua", "ciudad sandino", "ticuantepe"}


def es_managua_kw(r):
    return (r.get("ciudad") or "").strip().lower() in MANAGUA_OK


def es_managua_qc(r):
    m = (r.get("municipio") or "").strip().lower()
    d = (r.get("departamento") or "").strip().lower()
    return m in MANAGUA_OK or (m == "" and d in MANAGUA_OK)


def _stats(items):
    ps = sorted(it["p"] for it in items)
    return {"n": len(ps), "media": statistics.mean(ps), "mediana": statistics.median(ps),
            "p25": ps[len(ps) // 4], "p75": ps[3 * len(ps) // 4],
            "p5": ps[int(len(ps) * .05)], "p95": ps[int(len(ps) * .95)]}


ES_CASA = {"kw": kw_es_casa, "qc": qc_es_casa, "mb": mb_es_casa, "sv": sv_es_casa,
           "dn": dn_es_casa}


def cargar_items(archivo, fuente, managua_kw=None):
    out = []
    for r in csv.DictReader(open(archivo, encoding="utf-8-sig")):
        if not r["lat"] or not r["lng"] or not r["precio"]:
            continue
        if managua_kw is True and not es_managua_kw(r):
            continue
        if managua_kw is False and not es_managua_qc(r):
            continue
        if not ES_CASA[fuente](r):  # solo casas: fuera terrenos, locales, oficinas...
            continue
        lat, lng, p = float(r["lat"]), float(r["lng"]), float(r["precio"])
        if not (BBOX["s"] <= lat <= BBOX["n"] and BBOX["o"] <= lng <= BBOX["e"]):
            continue
        z = (r.get("zona") or r.get("loc") or (r.get("direccion") or "").split(",")[0]).strip().title()
        out.append({"lat": lat, "lng": lng, "p": p,
                    "dir": r.get("direccion") or r.get("zona") or r.get("loc") or "",
                    "zona": NOMBRES.get(z, z), "fuente": fuente})
    return out


def cargar():
    """Modo casas: KW con universo expandido, municipio Managua."""
    archivo = "kw_casas_venta.csv" if CASAS else "kw_listados_venta.csv"
    items = []
    for r in csv.DictReader(open(archivo, encoding="utf-8-sig")):
        if not r["lat"] or not r["lng"] or not r["precio"] or not es_managua_kw(r):
            continue
        lat, lng, p = float(r["lat"]), float(r["lng"]), float(r["precio"])
        if not (BBOX["s"] <= lat <= BBOX["n"] and BBOX["o"] <= lng <= BBOX["e"]):
            continue
        z = (r["direccion"] or "").split(",")[0].strip().title()
        items.append({"lat": lat, "lng": lng, "p": p, "fuente": "kw",
                      "dir": r["direccion"] or "", "zona": NOMBRES.get(z, z)})
    return items, _stats(items)


def cargar_consolidado():
    kw = cargar_items("kw_listados_venta.csv", "kw", managua_kw=True)
    qc = cargar_items("quierocasa_venta.csv", "qc", managua_kw=False)
    mb = cargar_items("momotombo_venta.csv", "mb", managua_kw=False)
    sv = cargar_items("sovinic_venta.csv", "sv", managua_kw=False)
    dn = cargar_items("discovernica_venta.csv", "dn", managua_kw=False)
    items, dups = [], []
    vistos = set()
    for it in kw + qc + mb + sv + dn:  # dedup: ±110 m + precio en el mismo millar
        k = (round(it["lat"], 3), round(it["lng"], 3), int(it["p"] / 1000))
        if k in vistos:
            dups.append(it)
            continue
        vistos.add(k)
        items.append(it)
    print(f"  consolidado: kw={len(kw)} qc={len(qc)} mb={len(mb)} sv={len(sv)} dn={len(dn)} "
          f"repetidos={len(dups)} → {len(items)}")
    return items, _stats(items), len(kw), len(qc), len(mb), len(sv), len(dn), len(dups)


def _dedupe(filas):
    mejor = {}
    for f in filas:
        if f[0] and (f[0] not in mejor or f[1] > mejor[f[0]][1]):
            mejor[f[0]] = f
    return list(mejor.values())


def agg_por_zona(items):
    grupos = collections.defaultdict(list)
    for it in items:
        if it["zona"] and it["zona"].lower() not in MUNI_ZONAS:
            grupos[it["zona"]].append(it)
    filas = []
    for z, its in grupos.items():
        if len(its) < 3:
            continue
        nombre = title_es(z)
        if z.lower() in CIUDADES or RE_RECHAZO.match(z.lower()):
            nombre = nombre_zona_de_items(its, z)
        ps = [it["p"] for it in its]
        filas.append((nombre, len(ps), statistics.mean(ps), statistics.median(ps)))
    filas = _dedupe(filas)
    # ranking por PROMEDIO; la mediana va como referencia en cada barra
    caras = sorted([f for f in filas if f[1] >= 4], key=lambda t: -t[2])[:10]
    excl = {c[0] for c in caras}
    baratas = sorted((f for f in filas if f[0] not in excl), key=lambda t: t[2])[:10]
    return caras, baratas


def agg_por_celdas(items):
    dLat, dLng = 0.014, 0.014 / 0.97768
    celdas = collections.defaultdict(list)
    for it in items:
        k = (int(it["lat"] / dLat), int(it["lng"] / dLng))
        celdas[k].append(it)
    agg, agg2 = [], []
    for its in celdas.values():
        if len(its) < 2:
            continue
        nombre = nombre_zona_de_items(its, "Zona sin nombre")
        ps = [it["p"] for it in its]
        fila = (nombre, len(ps), statistics.mean(ps), statistics.median(ps))
        (agg if len(ps) >= 3 else agg2).append(fila)
    agg, agg2 = _dedupe(agg), _dedupe(agg2)
    caras = sorted(agg, key=lambda t: -t[2])[:10]
    excl = {c[0] for c in caras}
    baratas = sorted((a for a in agg2 if a[0] not in excl), key=lambda t: t[2])[:10]
    return caras, baratas


def pesos_heat(items, p5, p95, exponente=1.0):
    lo, hi = math.log(p5), math.log(p95)
    out = []
    for it in items:
        w = max(0.0, min(1.0, (math.log(max(it["p"], 1)) - lo) / (hi - lo))) ** exponente
        out.append([it["lat"], it["lng"], round(w, 3)])
    return out


FILA = """
<g transform="translate(0,{y})">
  <text x="0" y="22" class="znombre">{zona}</text>
  <text x="960" y="22" class="zlist" text-anchor="end">{n} listados</text>
  <rect x="0" y="36" width="700" height="18" rx="9" fill="#1A2438"/>
  <rect x="0" y="36" width="{w}" height="18" rx="9" fill="{color}"/>
  <text x="960" y="51" class="zval" text-anchor="end">{prom}</text>
</g>"""


def escala_color(t):
    stops = [(0, (35, 139, 69)), (.25, (116, 196, 118)), (.5, (254, 224, 139)),
             (.75, (252, 141, 89)), (1, (215, 48, 39))]
    t = max(0, min(1, t))
    for i in range(1, len(stops)):
        t0, c0 = stops[i - 1]
        t1, c1 = stops[i]
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return "rgb(%s)" % ",".join(str(round(a + (b - a) * f)) for a, b in zip(c0, c1))
    return "rgb(215,48,39)"


def html_slide1(pts_w, st):
    radio, blur, mz, mo = (27, 15, 14, .1) if CASAS else (30, 16, 16, .12)
    extra_head = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
  #mapa{width:100%;height:1040px;border-radius:18px;background:#11151c;flex-shrink:0}
  .leyenda{margin:0 10px 28px;flex-shrink:0}
  .ley-bar{height:22px;border-radius:11px;
    background:linear-gradient(90deg,#1a9850,#a6d96a 30%,#fee08b 50%,#fc8d59 70%,#e31a1c 85%,#ff0000)}
  .ley-lbls{display:flex;justify-content:space-between;font-size:26px;color:__G__;margin-top:10px;font-weight:600}
  .ley-tit{text-align:center;font-size:21px;letter-spacing:3px;color:__G__;margin-top:8px}
</style>
""".replace("__G__", GRIS)
    extra_js = """
<script>
const ESRI='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
const mapa=L.map('mapa',{zoomControl:false,attributionControl:false});
L.tileLayer(ESRI+'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,maxNativeZoom:16}).addTo(mapa);
L.tileLayer(ESRI+'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,maxNativeZoom:16,opacity:.85}).addTo(mapa);
mapa.setView([12.13,-86.27],12);
L.heatLayer(__PTS__,{radius:__R__,blur:__B__,maxZoom:__MZ__,minOpacity:__MO__,
  gradient:{0.0:'#37b24d',0.3:'#a6d96a',0.5:'#fee08b',0.7:'#fc8d59',0.85:'#e31a1c',1.0:'#ff0000'}}).addTo(mapa);
</script>
""".replace("__PTS__", json.dumps(pts_w, separators=(",", ":"))) \
        .replace("__R__", str(radio)).replace("__B__", str(blur)) \
        .replace("__MZ__", str(mz)).replace("__MO__", str(mo))
    sub = (f"Mapa de calor · {st['n']} casas en venta (5 portales) · municipio de Managua"
           if not CASAS else
           f"Mapa de calor de precios · {st['n']} casas en venta (KW Nicaragua)")
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo="Breve análisis de casas en venta en el Área Metropolitana de Managua",
        sub=sub,
        cuerpo="""
<div class="leyenda">
  <div class="ley-bar"></div>
  <div class="ley-lbls"><span>__P5__</span><span>media __MED__</span><span>__P95__</span></div>
  <div class="ley-tit">PRECIO DE VENTA →</div>
</div>
<div id="mapa"></div>
""".replace("__P5__", fmt_k(st["p5"])).replace("__MED__", fmt_k(st["media"])).replace("__P95__", fmt_k(st["p95"])),
        extra_head=extra_head,
        extra_js=extra_js,
        pie="Interpretación en el siguiente slide",
        fondo_mapa=BG)


def html_slide_rank(titulo, datos, modo):
    max_prom = max(d[2] for d in datos)
    filas, y = [], 60
    for i, (z, n, prom, med) in enumerate(datos):
        t = prom / max_prom
        color = escala_color(1 - i / 9) if modo == "caras" else escala_color((i / 9) * .45)
        w = max(24, round(700 * t))
        filas.append(FILA.format(y=y, zona=z, n=n, w=w, color=color, prom=fmt_k(prom)))
        y += 100
    svg = ('<svg viewBox="0 0 960 ' + str(y + 30) + '" width="100%" class="barras">'
           + '<text x="960" y="26" class="zhead" text-anchor="end">PROMEDIO DE VENTA</text>'
           + "".join(filas) + "</svg>")
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo=titulo,
        sub=f"Ordenadas por promedio · mínimo {min(d[1] for d in datos)} listados activos",
        cuerpo=svg,
        extra_head="""
<style>
  svg.barras .znombre{font-size:28px;font-weight:700;fill:__T__}
  svg.barras .zlist{font-size:22px;fill:__G__}
  svg.barras .zval{font-size:28px;font-weight:800;fill:__T__}
  svg.barras .zhead{font-size:19px;letter-spacing:2px;fill:__G__;font-weight:600}
  svg.barras .zval .zmed{font-size:21px;font-weight:400;fill:__G__}
</style>
""".replace("__T__", TXT).replace("__G__", GRIS),
        extra_js="",
        pie="Interpretación en el siguiente slide",
        fondo_mapa=BG)


def html_consideracion():
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo="⚠️ Consideración importante",
        sub="Sobre los datos de este análisis",
        cuerpo="""
<div class="grande">
  KW, QuieroCasa, Momotombo, Sovinic y Discover muestran el <b>segmento formal del mercado</b>:
  casas comercializadas por agencias inmobiliarias.
</div>
<div class="caja" style="border-color:#E15759">
  <div class="caja-t" style="color:#E15759">LO QUE ESTOS PROMEDIOS SÍ SON</div>
  <div class="caja-b">Un <b>acercamiento al mercado formal</b>: útil para comparar
    zonas entre sí y detectar dónde está el valor.</div>
</div>
<div class="caja" style="border-color:#5B9BD5">
  <div class="caja-t" style="color:#5B9BD5">LO QUE NO SON</div>
  <div class="caja-b">El precio real de <b>todas</b> las casas del Área Metropolitana
    de Managua: las ventas entre particulares y el mercado informal
    <b>no aparecen en estos portales</b>.</div>
</div>
""",
        extra_head="""
<style>
  .grande{font-size:42px;line-height:1.4;color:__T__;text-align:center;
    background:#141d33;border-radius:16px;padding:34px 30px;margin-bottom:26px}
  .grande b{color:#F2C14E}
  .caja{border:3px solid;border-radius:16px;padding:28px 32px;margin-top:26px}
  .caja-t{font-size:29px;font-weight:800;letter-spacing:2px;text-align:center;margin-bottom:12px}
  .caja-b{font-size:29px;line-height:1.45;text-align:center;color:__T__}
  .caja-b b{color:#fff}
</style>
""".replace("__T__", TXT).replace("__G__", GRIS),
        extra_js="",
        pie="Con esa lectura, empecemos",
        fondo_mapa=BG)


def html_oportunidades():
    seccion = lambda color, titulo, texto: CAJA.format(color=color, titulo=titulo, texto=texto)
    cajas = [
        seccion("#C9A0DC", "MÁS FUENTES DE DATOS",
                "<b>Encuentra24</b>, <b>Facebook Marketplace</b> y otros sitios web de "
                "clasificados y <b>ventas entre particulares</b>, para cubrir el mercado "
                "informal que hoy queda fuera."),
        seccion(AZUL, "PRECIO POR METRO CUADRADO",
                "Analizar el <b>$/m² de construcción</b> y el <b>$/m² de lote</b> por zona: "
                "permite comparar propiedades de distinto tamaño y medir plusvalía real."),
        seccion(AMARILLO, "HISTÓRICO Y VENDIDAS",
                "Series históricas de precios y <b>propiedades vendidas</b> (no solo "
                "listadas): el precio de oferta y el de venta final no son lo mismo."),
        seccion("#57A773", "MÁS SEGMENTOS",
                "Extender el análisis a <b>alquileres</b> y a otros tipos: apartamentos, "
                "oficinas, terrenos y fincas, cada uno con su propio mapa de calor."),
    ]
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo="Oportunidades futuras",
        sub="Por dónde crece este análisis",
        cuerpo="".join(cajas),
        extra_head="""
<style>
  .caja{border:2px solid;border-radius:16px;padding:24px 30px;margin-top:24px}
  .caja-t{font-size:27px;font-weight:800;letter-spacing:2px;text-align:center;margin-bottom:10px}
  .caja-b{font-size:26px;line-height:1.42;text-align:center;color:__T__}
  .caja-b b{color:#fff}
</style>
""".replace("__T__", TXT).replace("__G__", GRIS),
        extra_js="",
        pie="Análisis con OpenCode + GLM 5.3 Flash (Z.ai) · septiembre 2026",
        fondo_mapa=BG)


def html_interpretacion(titulo, sub, cajas):
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo=titulo,
        sub=sub,
        cuerpo="".join(cajas),
        extra_head="""
<style>
  .caja{border:3px solid;border-radius:16px;padding:30px 34px;margin-top:30px}
  .caja-t{font-size:31px;font-weight:800;letter-spacing:2px;text-align:center;margin-bottom:14px}
  .caja-b{font-size:30px;line-height:1.45;text-align:center;color:__T__}
  .caja-b b{color:#fff}
</style>
""".replace("__T__", TXT).replace("__G__", GRIS),
        extra_js="",
        pie="Datos: kwnicaragua.kw.com + quierocasa.com + momotomborealestate.com + sovinic.com.ni + discovernica.com · septiembre 2026",
        fondo_mapa=BG)


CAJA = """
<div class="caja" style="border-color:{color}">
  <div class="caja-t" style="color:{color}">{titulo}</div>
  <div class="caja-b">{texto}</div>
</div>"""

def html_metodologia(nkw, nqc, nmb, nsv, ndn, ndup, total):
    seccion = lambda color, titulo, texto: CAJA.format(color=color, titulo=titulo, texto=texto)
    cajas = [
        seccion("#8B95AB", "HERRAMIENTAS",
                "Pipeline construido con <b>OpenCode</b> usando el modelo "
                "<b>GLM 5.3 Flash</b> de Z.ai para el análisis de datos y el "
                "<b>vibe coding</b> de estos slides."),
        seccion(AMARILLO, "FUENTES (solo casas)",
                f"<b>KW Nicaragua</b> ({nkw}): API GraphQL pública con coordenadas nativas. "
                f"<b>QuieroCasa</b> ({nqc}), <b>Momotombo</b> ({nmb}) y <b>Sovinic</b> ({nsv}): "
                f"HTML sin API ni coordenadas — geocodificadas por ubicación del título/slug. "
                f"<b>Discover</b> ({ndn}): API JSON propia, geocodificada por zona del título."),
        seccion(AZUL, "GEOCODIFICACIÓN",
                "Para ubicar QuieroCasa en el mapa se geocodificó el <b>nombre de la zona</b> "
                "con OpenStreetMap/Nominatim (119 zonas únicas, cache local, 1 consulta/seg). "
                "Precisión por <b>cuadra</b>, no por propiedad."),
        seccion("#5FA36C", "CONSOLIDACIÓN",
                f"Clasificador <b>solo casas</b> (fuera terrenos, locales y oficinas) y "
                f"<b>{ndup} repetidos</b> eliminados (misma ubicación ±110 m y precio) "
                f"→ <b>{total} casas únicas</b>. Filtro: Managua, Ciudad Sandino "
                "y Ticuantepe (Nindirí excluido). Ranking por <b>promedio</b> de venta "
                "por zona."),
    ]
    return PLANTILLA.format(
        BG=BG, T=TXT, G=GRIS,
        titulo="Metodología",
        sub="Cómo se construyó este análisis",
        cuerpo="".join(cajas),
        extra_head="""
<style>
  .caja{border:2px solid;border-radius:16px;padding:24px 30px;margin-top:24px}
  .caja-t{font-size:27px;font-weight:800;letter-spacing:2px;text-align:center;margin-bottom:10px}
  .caja-b{font-size:26px;line-height:1.42;text-align:center;color:__T__}
  .caja-b b{color:#fff}
</style>
""".replace("__T__", TXT).replace("__G__", GRIS),
        extra_js="",
        pie="Análisis con OpenCode + GLM 5.3 Flash (Z.ai) · septiembre 2026",
        fondo_mapa=BG)


PLANTILLA = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<style>
* {{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:{fondo_mapa}}}
body{{font-family:'Inter','Segoe UI',Roboto,system-ui,sans-serif}}
.wrap{{position:absolute;inset:0;background:{BG};padding:190px 216px 190px 60px;display:flex;flex-direction:column}}
h1{{font-size:58px;font-weight:800;color:{T};text-align:center;line-height:1.15;letter-spacing:-.5px}}
.sub{{font-size:29px;color:{G};text-align:center;margin-top:16px}}
.cuerpo{{margin-top:42px;flex:1;display:flex;flex-direction:column}}
.pie{{text-align:center;font-size:22px;color:{G};padding-top:16px}}
</style>
{extra_head}
</head><body>
<div class="wrap">
  <h1>{titulo}</h1>
  <div class="sub">{sub}</div>
  <div class="cuerpo">
{cuerpo}
  </div>
  <div class="pie">{pie}</div>
</div>
{extra_js}
</body></html>"""


async def render(tareas):
    from playwright.async_api import async_playwright
    # CHROME_PATH permite usar el Chrome del sistema cuando no hay Chromium de Playwright.
    extra = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"], **extra)
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        for html, png in tareas:
            await page.goto(f"file://{os.path.abspath(html)}")
            await page.wait_for_timeout(9000)
            await page.screenshot(path=png)
            print("✓", png)
        await browser.close()


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    tareas = []

    if CASAS:
        items, st = cargar()
        caras, baratas = agg_por_celdas(items)
        c1, c2 = caras[0], caras[1]
        ratio = c1[2] / c1[3] if c1[3] else 1
        nota = ("Una sola propiedad de élite infla ese promedio — la mayoría de las "
                f"casas de la zona cuestan menos.") if ratio > 1.4 else \
               ("El promedio representa bien a la zona: precios consistentes.")
        interp = {
            "mapa": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto="El foco rojo está en el corredor <b>Carretera a Masaya "
                                  "km 11–13</b> y <b>Villa Fontana Sur</b>. El centro concentra "
                                  "<b>volumen, no precio</b>."),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto=f"La casa típica cuesta <b>{fmt_k(st['media'])}</b> y la mitad "
                                  f"de las ofertas está entre <b>{fmt_k(st['p25'])}</b> y "
                                  f"<b>{fmt_k(st['p75'])}</b>. Solo casas dentro del municipio "
                                  "de Managua."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto="Universo <b>expandido con clasificador</b>: casas rescatadas de "
                                  "“Other”, “Mobile Home”, “Condominium” y más. Verde = oportunidades "
                                  "de entrada."),
            ],
            "caras": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto=f"<b>{c1[0]}</b> promedia <b>{fmt_k(c1[2])}</b> y <b>{c2[0]}</b> "
                                  f"{fmt_k(c2[2])}. {nota}"),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto="El ranking ordena las zonas por el <b>promedio de venta</b>: "
                                  "barra más larga, zona más cara en promedio."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto="La zona cara consolidada es el <b>corredor Carretera a Masaya "
                                  "km 11–14</b>. En zonas con pocos listados, una propiedad de "
                                  "élite puede inflar el promedio: pide el rango completo."),
            ],
            "baratas": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto=f"<b>{baratas[0][0]}</b> es la más accesible: promedio "
                                  f"<b>{fmt_k(baratas[0][2])}</b> — la casa típica de Managua cuesta "
                                  f"{fmt_k(st['media'])}."),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto="Barato no significa malo: son zonas periféricas o en desarrollo a "
                                  "minutos del centro. El precio baja por <b>ubicación y plusvalía</b>, "
                                  "no por mala calidad."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto="Con casas compara el <b>$/m² de construcción</b> y el estado del "
                                  "inmueble; verifica títulos, accesos y servicios antes de comprar."),
            ],
        }
        sub_mapa = f"Mapa de calor de precios · {st['n']} casas en venta (KW Nicaragua)"
        pie_datos = f"Datos: kwnicaragua.kw.com · {st['n']} casas (clasificador) · septiembre 2026"
    else:
        items, st, nkw, nqc, nmb, nsv, ndn, ndup = cargar_consolidado()
        caras, baratas = agg_por_zona(items)
        interp = {
            "mapa": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto="El calor caro se enciende en el <b>corredor Carretera a Masaya "
                                  "km 11–13</b>: Santo Domingo, Balcones y Villa Fontana. El centro "
                                  "y el este concentran <b>volumen, no precio</b>."),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto=f"La casa típica cuesta <b>{fmt_k(st['media'])}</b> y la "
                                  f"mitad de las ofertas está entre <b>{fmt_k(st['p25'])}</b> y "
                                  f"<b>{fmt_k(st['p75'])}</b>. Datos de <b>KW, QuieroCasa, "
                                  "Momotombo, Sovinic y Discover</b> dentro del municipio de Managua."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto="Los focos rojos son zonas caras <b>en cinco fuentes distintas</b>: "
                                  "es la señal más confiable. Nindirí quedó fuera: no es Managua; "
                                  "Ciudad Sandino y Ticuantepe sí se incluyen."),
            ],
            "caras": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto=f"<b>{caras[0][0]}</b> promedia <b>{fmt_k(caras[0][2])}</b> "
                                  f"y <b>{caras[1][0]}</b> {fmt_k(caras[1][2])}. Todas están en el "
                                  "corredor Carretera a Masaya / Santo Domingo — la zona cara "
                                  "consolidada de la ciudad."),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto="El ranking ordena las zonas por el <b>promedio de venta</b>: barra más "
                                  "larga, zona más cara en promedio."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto=f"Ojo: en zonas con pocos listados (ej. “{max(caras, key=lambda t: t[2]/(t[3] or 1))[0]}”), "
                                  "una sola propiedad de élite puede inflar el promedio. "
                                  "Pide siempre el rango completo de precios antes de ofertar."),
            ],
            "baratas": [
                CAJA.format(color=AMARILLO, titulo="HALLAZGO",
                            texto=f"<b>{baratas[0][0]}</b> es la más accesible: promedio "
                                  f"<b>{fmt_k(baratas[0][2])}</b> — la casa típica de Managua "
                                  f"cuesta {fmt_k(st['media'])}."),
                CAJA.format(color=AZUL, titulo="EN LENGUAJE SENCILLO",
                            texto="Barato no significa malo: son zonas céntricas populares o en "
                                  "desarrollo. El precio baja por <b>ubicación y plusvalía</b>, no "
                                  "por mala calidad."),
                CAJA.format(color=ROJO, titulo="PARA LA DECISIÓN",
                            texto="En estas zonas manda el <b>precio del metro de lote</b>. Cruza "
                                  "ambas fuentes antes de pagar: el mismo inmueble puede variar de "
                                  "precio entre portales."),
            ],
        }
        sub_mapa = (f"Mapa de calor · {st['n']} casas en venta (5 portales) · "
                    "municipio de Managua")
        pie_datos = ("Datos: kwnicaragua.kw.com + quierocasa.com + momotomborealestate.com "
                     "+ sovinic.com.ni + discovernica.com · septiembre 2026")

    exp = 1.0 if CASAS else 1.15
    tareas = []
    with open(f"{OUT}/01{SUFIJ}.html", "w") as f:
        f.write(html_slide1(pesos_heat(items, st["p5"], st["p95"], exp), st))
    tareas.append((f"{OUT}/01{SUFIJ}.html", f"{OUT}/01_mapa_calor{SUFIJ}.png"))

    with open(f"{OUT}/02{SUFIJ}.html", "w") as f:
        f.write(html_interpretacion("Interpretación · Mapa de calor",
                                    f"{st['n']} casas · municipio de Managua",
                                    interp["mapa"]))
    tareas.append((f"{OUT}/02{SUFIJ}.html", f"{OUT}/02_interpretacion_mapa{SUFIJ}.png"))

    with open(f"{OUT}/03{SUFIJ}.html", "w") as f:
        f.write(html_consideracion())
    tareas.append((f"{OUT}/03{SUFIJ}.html", f"{OUT}/03_consideracion{SUFIJ}.png"))

    with open(f"{OUT}/04{SUFIJ}.html", "w") as f:
        f.write(html_slide_rank("Las 10 zonas MÁS CARAS de Managua", caras, "caras"))
    tareas.append((f"{OUT}/04{SUFIJ}.html", f"{OUT}/04_top10_zonas_caras{SUFIJ}.png"))

    with open(f"{OUT}/05{SUFIJ}.html", "w") as f:
        f.write(html_interpretacion("Interpretación · Zonas más caras",
                                    "Promedio vs mediana: cómo leer el ranking",
                                    interp["caras"]))
    tareas.append((f"{OUT}/05{SUFIJ}.html", f"{OUT}/05_interpretacion_caras{SUFIJ}.png"))

    with open(f"{OUT}/06{SUFIJ}.html", "w") as f:
        f.write(html_slide_rank("Las 10 zonas MÁS BARATAS de Managua", baratas, "baratas"))
    tareas.append((f"{OUT}/06{SUFIJ}.html", f"{OUT}/06_top10_zonas_baratas{SUFIJ}.png"))

    with open(f"{OUT}/07{SUFIJ}.html", "w") as f:
        f.write(html_interpretacion("Interpretación · Zonas más baratas",
                                    "Qué significa estar en la lista verde",
                                    interp["baratas"]))
    tareas.append((f"{OUT}/07{SUFIJ}.html", f"{OUT}/07_interpretacion_baratas{SUFIJ}.png"))

    if not CASAS:
        with open(f"{OUT}/08.html", "w") as f:
            f.write(html_metodologia(nkw, nqc, nmb, nsv, ndn, ndup, st["n"]))
        tareas.append((f"{OUT}/08.html", f"{OUT}/08_metodologia.png"))

        with open(f"{OUT}/09.html", "w") as f:
            f.write(html_oportunidades())
        tareas.append((f"{OUT}/09.html", f"{OUT}/09_oportunidades_futuras.png"))

    with open(f"{OUT}/pie.txt", "w") as f:
        f.write(pie_datos + "\n")

    print(f"[{'casas' if CASAS else 'consolidado'}] n={st['n']} mediana={st['mediana']:,.0f} | "
          f"caras: {[c[0] for c in caras[:3]]} | baratas: {[b[0] for b in baratas[:3]]}")
    asyncio.run(render(tareas))


if __name__ == "__main__":
    main()
