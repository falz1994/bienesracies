"""Genera los datos estáticos del sitio (data/*.json) desde el pipeline de análisis.

Fuentes: KW Nicaragua, QuieroCasa y Momotombo (venta, Managua + Ciudad Sandino + Ticuantepe).
Uso: python3 generar_datos.py   (requiere los CSVs en /home/devni/analisis bienes raices/)
"""
import csv
import json
import os
import shutil
import statistics
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
ANALISIS = "/home/devni/analisis bienes raices"
sys.path.insert(0, ANALISIS)

MANAGUA_OK = {"managua", "ciudad sandino", "ticuantepe"}
BBOX = {"s": 11.98, "n": 12.26, "o": -86.48, "e": -86.10}


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
               "dir": r["direccion"] or ""}


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
               "dir": r["zona"] or ""}


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
               "ciudad": (r.get("municipio") or "").strip(), "dir": r["zona"] or ""}


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
    items = list(kw_rows()) + list(qc_rows()) + list(mb_rows())
    unicos, dups = dedupe(items)
    print(f"total={len(items)} únicos={len(unicos)} repetidos={dups}")

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
    stats_json = {"global": stats(unicos),
                  "kw": stats([x for x in unicos if x["fuente"] == "kw"]),
                  "qc": stats([x for x in unicos if x["fuente"] == "qc"]),
                  "mb": stats([x for x in unicos if x["fuente"] == "mb"]),
                  "repetidos": dups}
    with open(f"{REPO}/docs/data/stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_json, f, ensure_ascii=False, indent=1)

    # ranking de zonas (misma lógica del pipeline, con geocodificación cacheada)
    from generar_slides import agg_por_zona
    items_basicos = [{"lat": x["lat"], "lng": x["lng"], "p": x["p"], "zona": x["zona"],
                      "dir": x["dir"], "fuente": x["fuente"]} for x in unicos]
    caras, baratas = agg_por_zona(items_basicos)
    zonas = {"caras": [{"zona": z, "n": n, "promedio": round(p), "mediana": round(m)}
                       for z, n, p, m in caras],
             "baratas": [{"zona": z, "n": n, "promedio": round(p), "mediana": round(m)}
                         for z, n, p, m in baratas]}
    with open(f"{REPO}/docs/data/zonas.json", "w", encoding="utf-8") as f:
        json.dump(zonas, f, ensure_ascii=False, indent=1)

    # CSVs para descarga + slides
    for nombre in ("kw_listados_venta.csv", "quierocasa_venta.csv", "momotombo_venta.csv"):
        shutil.copy(f"{ANALISIS}/{nombre}", f"{REPO}/docs/data/{nombre}")
    for png in sorted(os.listdir(f"{ANALISIS}/slides")):
        if png.endswith(".png"):
            shutil.copy(f"{ANALISIS}/slides/{png}", f"{REPO}/docs/slides/{png}")
    print("data/ y slides/ listos")
    print("zonas caras:", [z[0] for z in caras[:5]])
    print("zonas baratas:", [z[0] for z in baratas[:5]])


if __name__ == "__main__":
    main()
