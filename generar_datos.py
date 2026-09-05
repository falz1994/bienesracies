"""Genera los datos estáticos del sitio (data/*.json) desde el pipeline de análisis.

Fuentes: KW Nicaragua, QuieroCasa, Momotombo y Sovinic (venta, Managua + Ciudad Sandino + Ticuantepe).
Uso: python3 generar_datos.py   (requiere los CSVs en /home/devni/analisis bienes raices/)
"""
import csv
import datetime
import json
import os
import re
import shutil
import statistics
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
ANALISIS = "/home/devni/analisis bienes raices"
sys.path.insert(0, ANALISIS)

MANAGUA_OK = {"managua", "ciudad sandino", "ticuantepe"}
BBOX = {"s": 11.98, "n": 12.26, "o": -86.48, "e": -86.10}

# --- clasificador de casas (conservador) ---
# KW: misma lógica validada de clasificar_casas.py (pipeline local)
KW_AUTO_CASA = {"SINGLE FAMILY DETACHED", "SINGLE FAMILY ATTACHED", "TOWNHOUSE", "DUPLEX"}
KW_AUTO_NO = {"APARTMENT", "OFFICE", "RETAIL", "WAREHOUSE", "INDUSTRIAL", "HOTEL MOTEL",
              "HOTEL-MOTEL", "OWN YOUR OWN", "STOCK COOPERATIVE", "DEEDED PARKING", "CABIN"}
KW_POS_FUERTE = [r"\bcasas?\b", r"\bvivienda\b", r"\bresidencia\s", r"🏡", r"\bplanta alta\b",
                 r"\bdos plantas\b", r"\bun nivel\b", r"\bdos niveles\b"]
KW_POS_HAB = [r"\b\d+\s*(habitaciones|dormitorios|recamaras|recámaras)\b", r"\bhabitaciones\b",
              r"\bdormitorios\b", r"\bclosets?\b", r"\bsala[- ]comedor\b"]
KW_NEG = [r"\bterrenos?\b", r"\blotes?\b", r"\bvara[s]?\b", r"\bv²\b", r"\bfinca\b", r"\bbodega",
          r"\blocal comercial\b", r"\bapartamentos?\b", r"\bproyecto\b", r"para construir",
          r"\bedificios?\b"]

NEG_TEXTO_RE = re.compile(
    r"\bterrenos?\b|\blotes?\b|\bvara[s]?\b|\bfinca\b|\bbodega|\blocal comercial\b|"
    r"\bedificios?\b|\bproyecto\b|para construir|\boficinas?\b", re.I)
CASA_TEXTO_RE = re.compile(r"\bcasas?\b", re.I)


def casa_por_texto(*textos):
    """Casa si menciona 'casa' como sujeto del anuncio (las palabras no habitacionales
    solo descalifican cuando aparecen ANTES de 'casa': 'terreno con casa' no es casa,
    'casa con terreno amplio' sí lo es)."""
    t = " ".join(x or "" for x in textos)
    m = CASA_TEXTO_RE.search(t)
    if not m:
        return False
    return not NEG_TEXTO_RE.search(t[:m.start()])


def kw_es_casa(r):
    t = (r.get("tipo_propiedad") or "").upper()
    if t in KW_AUTO_CASA:
        return True
    if t in KW_AUTO_NO:
        return False
    texto = f"{r.get('descripcion') or ''} {r.get('direccion') or ''}".lower()
    pos = sum(len(re.findall(p, texto)) for p in KW_POS_FUERTE) + 0.5 * sum(
        len(re.findall(p, texto)) for p in KW_POS_HAB)
    neg = sum(len(re.findall(p, texto)) for p in KW_NEG)
    if re.search(r"\bconstrucc[ií]on\b", texto) and re.search(r"\bcasas?\b", texto):
        pos += 1
    return pos >= 2 and pos > neg


def qc_es_casa(r):
    return (r.get("tipo") or "").strip().lower() == "casa"


def mb_es_casa(r):
    t = (r.get("tipo") or "").strip().lower()
    if t == "casa":
        return True
    return not t and casa_por_texto(r.get("titulo"))


def sv_es_casa(r):
    return casa_por_texto(r.get("titulo"), r.get("slug"))


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _i(x):
    f = _f(x)
    if f is None:
        return None
    return int(f) if f == int(f) else f


def en_bbox(lat, lng):
    return lat is not None and lng is not None and \
        BBOX["s"] <= lat <= BBOX["n"] and BBOX["o"] <= lng <= BBOX["e"]


def kw_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/kw_listados_venta.csv", encoding="utf-8-sig")):
        if (r.get("ciudad") or "").strip().lower() not in MANAGUA_OK or not r["precio"]:
            continue
        if not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": r["id"], "fuente": "kw", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["direccion"] or "").split(",")[0].strip().title(),
               "hab": _i(r["habitaciones"]), "banos": _i(r["banos"]),
               "m2": _f(r["area_m2"]), "lote": _f(r["lote_m2"]),
               "tipo": (r["tipo_propiedad"] or "").title(),
               "url": r["url"], "img": r["imagen"], "ciudad": (r["ciudad"] or "").strip(),
               "dir": r["direccion"] or "", "casa": kw_es_casa(r)}


def qc_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/quierocasa_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": r["codigo"], "fuente": "qc", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["zona"] or "").strip().title(),
               "hab": _i(r["hab"]), "banos": _i(r["banos"]), "m2": _f(r["m2_constr"]),
               "lote": _f(r["terreno"]), "tipo": (r["tipo"] or "").title(),
               "url": r["url"], "img": r["imagen"], "ciudad": (r.get("municipio") or "").strip(),
               "dir": r["zona"] or "", "casa": qc_es_casa(r)}


def mb_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/momotombo_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": r["id"] or r["codigo"], "fuente": "mb", "lat": _f(r["lat"]),
               "lng": _f(r["lng"]), "p": _f(r["precio"]),
               "zona": (r["zona"] or "").strip().title(), "hab": _i(r["hab"]),
               "banos": _i(r["banos"]), "m2": None, "lote": None,
               "tipo": (r["tipo"] or "").title(), "url": r["url"], "img": r["imagen"],
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["zona"] or "",
               "casa": mb_es_casa(r)}


def sv_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/sovinic_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": "sv" + r["id"], "fuente": "sv", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["loc"] or "").strip().title(),
               "hab": _i(r["hab"]), "banos": _i(r["banos"]), "m2": _f(r["area"]),
               "lote": _f(r["lote"]),                "tipo": "Casa", "url": r["url"], "img": r["imagen"],
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["loc"] or "",
               "casa": sv_es_casa(r)}


def dedupe(items):
    out, dups = [], 0
    vistos = set()
    for it in items:
        if not it["lat"] or not it["lng"] or not it["p"]:
            continue
        k = (round(it["lat"], 3), round(it["lng"], 3), int(it["p"] / 1000))
        if k in vistos:
            dups += 1
            continue
        vistos.add(k)
        out.append(it)
    return out, dups


def main():
    items = list(kw_rows()) + list(qc_rows()) + list(mb_rows()) + list(sv_rows())
    unicos, dups = dedupe(items)
    print(f"total={len(items)} únicos={len(unicos)} repetidos={dups}")
    for f in ("kw", "qc", "mb", "sv"):
        filas_f = [x for x in unicos if x["fuente"] == f]
        print(f"  {f}: {len(filas_f)} listados → {sum(1 for x in filas_f if x['casa'])} casas")

    os.makedirs(f"{REPO}/docs/data", exist_ok=True)
    os.makedirs(f"{REPO}/docs/slides", exist_ok=True)

    with open(f"{REPO}/docs/data/listados.json", "w", encoding="utf-8") as f:
        json.dump(unicos, f, ensure_ascii=False, separators=(",", ":"))

    # stats por fuente + global
    def stats(lista):
        ps = sorted(x["p"] for x in lista)
        return {"n": len(ps), "media": round(statistics.mean(ps)),
                "p25": round(ps[len(ps) // 4]), "p75": round(ps[3 * len(ps) // 4]),
                "p5": round(ps[int(len(ps) * .05)]), "p95": round(ps[int(len(ps) * .95)])}
    fecha_m = max(os.path.getmtime(f"{ANALISIS}/{n}") for n in
                  ("kw_listados_venta.csv", "quierocasa_venta.csv", "momotombo_venta.csv",
                   "sovinic_venta.csv"))
    stats_json = {"fecha": datetime.date.fromtimestamp(fecha_m).isoformat(),
                  "global": stats(unicos),
                  "casas": stats([x for x in unicos if x["casa"]]),
                  "kw": stats([x for x in unicos if x["fuente"] == "kw"]),
                  "qc": stats([x for x in unicos if x["fuente"] == "qc"]),
                  "mb": stats([x for x in unicos if x["fuente"] == "mb"]),
                  "sv": stats([x for x in unicos if x["fuente"] == "sv"]),
                  "casas_fuente": {f: sum(1 for x in unicos if x["fuente"] == f and x["casa"])
                                   for f in ("kw", "qc", "mb", "sv")},
                  "repetidos": dups}
    with open(f"{REPO}/docs/data/stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_json, f, ensure_ascii=False, indent=1)

    # ranking de zonas (misma lógica del pipeline, con geocodificación cacheada)
    # SOLO CASAS: el sitio analiza vivienda, no terrenos ni locales
    from generar_slides import agg_por_zona
    casas = [x for x in unicos if x["casa"]]
    items_basicos = [{"lat": x["lat"], "lng": x["lng"], "p": x["p"], "zona": x["zona"],
                      "dir": x["dir"], "fuente": x["fuente"]} for x in casas]
    caras, baratas = agg_por_zona(items_basicos)
    zonas = {"caras": [{"zona": z, "n": n, "promedio": round(p), "mediana": round(m)}
                       for z, n, p, m in caras],
             "baratas": [{"zona": z, "n": n, "promedio": round(p), "mediana": round(m)}
                         for z, n, p, m in baratas]}
    with open(f"{REPO}/docs/data/zonas.json", "w", encoding="utf-8") as f:
        json.dump(zonas, f, ensure_ascii=False, indent=1)

    # CSVs para descarga + slides
    for nombre in ("kw_listados_venta.csv", "quierocasa_venta.csv", "momotombo_venta.csv",
                   "sovinic_venta.csv"):
        shutil.copy(f"{ANALISIS}/{nombre}", f"{REPO}/docs/data/{nombre}")
    for png in sorted(os.listdir(f"{ANALISIS}/slides")):
        if png.endswith(".png"):
            shutil.copy(f"{ANALISIS}/slides/{png}", f"{REPO}/docs/slides/{png}")
    print("data/ y slides/ listos")
    print("zonas caras:", [z[0] for z in caras[:5]])
    print("zonas baratas:", [z[0] for z in baratas[:5]])


if __name__ == "__main__":
    main()
