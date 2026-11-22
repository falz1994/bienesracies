"""Genera los datos estáticos del sitio (docs/data/*.json) desde el pipeline de análisis.

Fuentes: KW Nicaragua, QuieroCasa, Momotombo, Sovinic y Discover (venta,
Managua + Ciudad Sandino + Ticuantepe).

Uso: python3 pipeline/generar_datos.py   (desde cualquier directorio)

Lee los CSVs de trabajo de ``pipeline/datos/``; si alguno no existe (clon limpio)
lo toma de ``docs/data/``, que es la copia publicada y versionada.
"""
import csv
import datetime
import json
import math
import os
import shutil
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rutas  # noqa: E402

from clasificador_casas import kw_es_casa, qc_es_casa, mb_es_casa, sv_es_casa, dn_es_casa  # noqa: E402

REPO = str(rutas.REPO)
ANALISIS = str(rutas.DATOS)

# Bootstrap para clones limpios: si falta un CSV/geojson de trabajo pero está
# publicado en docs/data/, se copia a pipeline/datos/ para poder consolidar.
rutas.DATOS.mkdir(parents=True, exist_ok=True)
for _n in rutas.CSVS + rutas.GEOJSONS:
    _destino = rutas.DATOS / _n
    _origen = rutas.PUB / _n
    if not _destino.exists() and _origen.exists():
        shutil.copy2(_origen, _destino)


def es_alquiler(*textos):
    """True si el aviso es de alquiler: operación explícita o título que empieza
    con "en renta/alquiler" sin mencionar venta (hay portales que mezclan ambos)."""
    bajo = " ".join(str(x or "") for x in textos).lower()
    if re.search(r"\b(en\s+(renta|alquiler)\b)", bajo) and not re.search(r"\bventa\b", bajo):
        return True
    return False

MANAGUA_OK = {"managua", "ciudad sandino", "ticuantepe"}
BBOX = {"s": 11.98, "n": 12.26, "o": -86.48, "e": -86.10}

# polígonos de los distritos de Managua (extraídos de OSM por extraer_distritos.py)
try:
    _DIST_GEO = json.load(open(f"{ANALISIS}/distritos_managua.geojson", encoding="utf-8"))
except FileNotFoundError:
    _DIST_GEO = {"features": []}


def _pipo(lat, lng, poly):
    """point-in-polygon (ray casting) con agujeros; poly = [rings] de [lng,lat]."""
    def dentro(x, y, ring):
        c = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c
    if not dentro(lng, lat, poly[0]):
        return False
    return not any(dentro(lng, lat, h) for h in poly[1:])


_CACHE_DIST = {}


def distrito_de(lat, lng, ciudad):
    if lat is None or lng is None:
        return ""
    k = (round(lat, 5), round(lng, 5))
    if k not in _CACHE_DIST:
        d = ""
        for f in _DIST_GEO["features"]:
            geom = f["geometry"]
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            if any(_pipo(lat, lng, p) for p in polys):
                d = f["properties"]["nombre"]
                break
        if not d:
            d = (ciudad or "").strip().title() or "Managua (otros)"
        _CACHE_DIST[k] = d
    return _CACHE_DIST[k]


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


# barrios y residenciales nombrados de OSM (extraídos por extraer_barrios.py)
try:
    _BAR_GEO = json.load(open(f"{ANALISIS}/barrios_managua.geojson", encoding="utf-8"))
except FileNotFoundError:
    _BAR_GEO = {"features": []}

_BAR_AREAS, _BAR_NODOS = [], []
for _f_ in _BAR_GEO["features"]:
    _g = _f_["geometry"]
    if _g["type"] == "Point":
        _BAR_NODOS.append((_f_["properties"]["nombre"], _g["coordinates"][1],
                           _g["coordinates"][0]))
        continue
    _polys = [_g["coordinates"]] if _g["type"] == "Polygon" else _g["coordinates"]
    _pts = [pt for p in _polys for r in p for pt in r]
    _o = min(p[0] for p in _pts); _s = min(p[1] for p in _pts)
    _e = max(p[0] for p in _pts); _n = max(p[1] for p in _pts)
    _BAR_AREAS.append((_f_["properties"]["nombre"], _polys, (_o, _s, _e, _n),
                       (_e - _o) * (_n - _s)))
_BAR_AREAS.sort(key=lambda x: x[3])

_CACHE_BAR = {}


def barrio_de(lat, lng):
    """Barrio/residencial OSM: polígono más pequeño que contiene el punto,
    o nodo con nombre más cercano (<700 m). None si no hay match."""
    if lat is None or lng is None:
        return None
    k = (round(lat, 5), round(lng, 5))
    if k in _CACHE_BAR:
        return _CACHE_BAR[k]
    nom = None
    for nombre, polys, (o, s, e, n), _a in _BAR_AREAS:
        if lng < o or lng > e or lat < s or lat > n:
            continue
        if any(_pipo(lat, lng, p) for p in polys):
            nom = nombre
            break
    if nom is None:
        mejor = 0.7
        for nombre, nlat, nlng in _BAR_NODOS:
            dx = (nlng - lng) * 111 * math.cos(math.radians(12.13))
            dy = (nlat - lat) * 111
            d = math.hypot(dx, dy)
            if d < mejor:
                mejor, nom = d, nombre
    _CACHE_BAR[k] = nom
    return nom


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
               "dir": r["direccion"] or "", "casa": kw_es_casa(r),
               "distrito": distrito_de(_f(r["lat"]), _f(r["lng"]), r.get("ciudad"))}


def qc_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/quierocasa_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if es_alquiler(r.get("titulo")):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": r["codigo"], "fuente": "qc", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["zona"] or "").strip().title(),
               "hab": _i(r["hab"]), "banos": _i(r["banos"]), "m2": _f(r["m2_constr"]),
               "lote": _f(r["terreno"]), "tipo": (r["tipo"] or "").title(),
               "url": r["url"], "img": r["imagen"], "ciudad": (r.get("municipio") or "").strip(),
               "dir": r["zona"] or "", "casa": qc_es_casa(r),
               "distrito": distrito_de(_f(r["lat"]), _f(r["lng"]), r.get("municipio"))}


def mb_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/momotombo_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if (r.get("operacion") or "").strip().lower() in ("renta", "alquiler"):
            continue
        if es_alquiler(r.get("titulo")):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": r["id"] or r["codigo"], "fuente": "mb", "lat": _f(r["lat"]),
               "lng": _f(r["lng"]), "p": _f(r["precio"]),
               "zona": (r["zona"] or "").strip().title(), "hab": _i(r["hab"]),
               "banos": _i(r["banos"]), "m2": None, "lote": None,
               "tipo": (r["tipo"] or "").title(), "url": r["url"], "img": r["imagen"],
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["zona"] or "",
               "casa": mb_es_casa(r),
               "distrito": distrito_de(_f(r["lat"]), _f(r["lng"]), r.get("municipio"))}


def sv_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/sovinic_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if es_alquiler(r.get("titulo"), r.get("slug")):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": "sv" + r["id"], "fuente": "sv", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["loc"] or "").strip().title(),
               "hab": _i(r["hab"]), "banos": _i(r["banos"]), "m2": _f(r["area"]),
               "lote": _f(r["lote"]),                "tipo": "Casa", "url": r["url"], "img": r["imagen"],
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["loc"] or "",
               "casa": sv_es_casa(r),
               "distrito": distrito_de(_f(r["lat"]), _f(r["lng"]), r.get("municipio"))}


def dn_rows():
    for r in csv.DictReader(open(f"{ANALISIS}/discovernica_venta.csv", encoding="utf-8-sig")):
        m = (r.get("municipio") or "").strip().lower()
        d = (r.get("departamento") or "").strip().lower()
        if m not in MANAGUA_OK and not (m == "" and d in MANAGUA_OK):
            continue
        if es_alquiler(r.get("titulo")):
            continue
        if not r["precio"] or not en_bbox(_f(r["lat"]), _f(r["lng"])):
            continue
        yield {"id": "dn" + r["id"], "fuente": "dn", "lat": _f(r["lat"]), "lng": _f(r["lng"]),
               "p": _f(r["precio"]), "zona": (r["zona"] or "").strip().title(),
               "hab": _i(r["hab"]), "banos": _i(r["banos"]), "m2": _f(r["m2"]),
               "lote": _f(r["lote_vrs"]), "tipo": "Casa", "url": r["url"], "img": r["imagen"],
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["zona"] or "",
               "casa": dn_es_casa(r),
               "distrito": distrito_de(_f(r["lat"]), _f(r["lng"]), r.get("municipio"))}


ORDEN_FUENTES = {"kw": 0, "qc": 1, "mb": 2, "sv": 3, "dn": 4}
LADO_CELDA = 0.0015  # ~165 m


def _dist_m(lat1, lng1, lat2, lng2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _razon(a, b):
    try:
        return max(a, b) / min(a, b)
    except (TypeError, ZeroDivisionError):
        return None


def _mismo_inmueble(a, b):
    """¿Dos avisos son la misma propiedad? Exige evidencia positiva; el precio y la
    cercanía solos NO alcanzan porque las fuentes geocodificadas comparten el
    centroide del barrio (fusionarlas borraría casas distintas del mismo barrio)."""
    if not a["p"] or not b["p"]:
        return False
    if a["fuente"] == b["fuente"]:
        # dentro de un portal, dos avisos parecidos suelen ser unidades distintas
        # del mismo proyecto (p. ej. lotes #2, #3, #4 de un residencial): no se fusionan
        return False
    rp = _razon(a["p"], b["p"])
    if rp is None or rp > 1.03:
        return False

    m2a, m2b = a.get("m2"), b.get("m2")
    lota, lotb = a.get("lote"), b.get("lote")
    if a["fuente"] == "dn" and lota:
        lota = lota * 0.698896            # Discover publica varas²
    if b["fuente"] == "dn" and lotb:
        lotb = lotb * 0.698896

    # veto: si ambos publican programa y no coincide, son inmuebles distintos
    hab_a, hab_b = a.get("hab"), b.get("hab")
    ban_a, ban_b = a.get("banos"), b.get("banos")
    if hab_a is not None and hab_b is not None and hab_a != hab_b:
        return False
    if ban_a is not None and ban_b is not None and abs(float(ban_a) - float(ban_b)) > 0.01:
        return False

    evidencia = False
    if m2a and m2b:
        if _razon(m2a, m2b) > 1.05:
            return False
        evidencia = True
    elif lota and lotb:
        if _razon(lota, lotb) > 1.05:
            return False
        evidencia = True
    if not evidencia and hab_a is not None and hab_a == hab_b and \
            ban_a is not None and ban_a == ban_b:
        evidencia = True                  # mismo programa completo
    if not evidencia:
        # sin m², lote ni programa no hay forma de probar que sea el mismo inmueble
        # (las fuentes geocodificadas comparten el centroide del barrio): se conservan ambos
        return False
    return True


def dedupe(items):
    """Deduplica por cercanía + evidencia de que es el mismo inmueble.
    Devuelve (únicos, n_descartados) y deja la auditoría en pipeline/datos/."""
    ordenados = sorted((x for x in items if x["lat"] and x["lng"] and x["p"]),
                       key=lambda x: (ORDEN_FUENTES.get(x["fuente"], 9), str(x["id"])))
    grilla, out, audit = {}, [], []
    for it in ordenados:
        cx, cy = int(it["lat"] / LADO_CELDA), int(it["lng"] / LADO_CELDA)
        match = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for prev in grilla.get((cx + dx, cy + dy), ()):
                    if _dist_m(prev["lat"], prev["lng"], it["lat"], it["lng"]) > 110:
                        continue
                    if _mismo_inmueble(prev, it):
                        match = prev
                        break
                if match:
                    break
            if match:
                break
        if match:
            audit.append({"se_descarta": f"{it['fuente']}:{it['id']}",
                          "precio": it["p"], "m2": it.get("m2"), "hab": it.get("hab"),
                          "se_conserva": f"{match['fuente']}:{match['id']}",
                          "precio_conservado": match["p"], "m2_conservado": match.get("m2"),
                          "hab_conservado": match.get("hab"), "zona": it.get("zona")})
            continue
        out.append(it)
        grilla.setdefault((cx, cy), []).append(it)
    try:
        import json as _json
        with open(f"{ANALISIS}/_dedupe_audit.json", "w", encoding="utf-8") as f:
            _json.dump(audit, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return out, len(audit)


def main():
    items = list(kw_rows()) + list(qc_rows()) + list(mb_rows()) + list(sv_rows()) + \
        list(dn_rows())
    unicos, dups = dedupe(items)
    print(f"total={len(items)} únicos={len(unicos)} repetidos={dups}")
    n_bar = 0
    for x in unicos:
        b = barrio_de(x["lat"], x["lng"])
        if b and b != x["zona"]:
            x["zona_orig"] = x["zona"]
            x["zona"] = b
            n_bar += 1
    print(f"barrio OSM asignado/corregido: {n_bar}/{len(unicos)}")
    for f in ("kw", "qc", "mb", "sv", "dn"):
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
                   "sovinic_venta.csv", "discovernica_venta.csv"))
    stats_json = {"fecha": datetime.date.fromtimestamp(fecha_m).isoformat(),
                  "global": stats(unicos),
                  "casas": stats([x for x in unicos if x["casa"]]),
                  "kw": stats([x for x in unicos if x["fuente"] == "kw"]),
                  "qc": stats([x for x in unicos if x["fuente"] == "qc"]),
                  "mb": stats([x for x in unicos if x["fuente"] == "mb"]),
                  "sv": stats([x for x in unicos if x["fuente"] == "sv"]),
                  "dn": stats([x for x in unicos if x["fuente"] == "dn"]),
                  "casas_fuente": {f: sum(1 for x in unicos if x["fuente"] == f and x["casa"])
                                   for f in ("kw", "qc", "mb", "sv", "dn")},
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
                   "sovinic_venta.csv", "discovernica_venta.csv"):
        shutil.copy(f"{ANALISIS}/{nombre}", f"{REPO}/docs/data/{nombre}")
    shutil.copy(f"{ANALISIS}/distritos_managua.geojson", f"{REPO}/docs/data/distritos_managua.geojson")
    if os.path.exists(f"{ANALISIS}/barrios_managua.geojson"):
        shutil.copy(f"{ANALISIS}/barrios_managua.geojson", f"{REPO}/docs/data/barrios_managua.geojson")
    for png in (sorted(os.listdir(f"{ANALISIS}/slides"))
                if os.path.isdir(f"{ANALISIS}/slides") else []):
        if png.endswith(".png"):
            shutil.copy(f"{ANALISIS}/slides/{png}", f"{REPO}/docs/slides/{png}")
    print("data/ y slides/ listos")
    print("zonas caras:", [z[0] for z in caras[:5]])
    print("zonas baratas:", [z[0] for z in baratas[:5]])


if __name__ == "__main__":
    main()
