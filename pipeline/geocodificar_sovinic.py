"""Geocodifica las ubicaciones de sovinic.com.ni (loc → lat/lng) con Nominatim.

Query: "loc, Nicaragua". Cache en geocache_sv.json, 1 req/seg.
Añade lat, lng, geo_tipo al CSV.
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import csv
import json
import os
import time
import urllib.parse
import urllib.request

CACHE_F = "geocache_sv.json"
UA = "analisis-managua/1.0 (geocodificacion sovinic)"


def search(q):
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1,
                                     "countrycodes": "ni", "accept-language": "es"}))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            datos = json.load(r)
        return datos[0] if datos else None
    except Exception as e:
        print(f"  [warn] {q[:50]}: {e}")
        time.sleep(3)
        return None


CIUDADES_NI = [("ciudad sandino", "Ciudad Sandino", "Managua"), ("ticuantepe", "Ticuantepe", "Managua"),
               ("managua", "Managua", "Managua"), ("nindiri", "Nindirí", "Masaya"),
               ("nindirí", "Nindirí", "Masaya"), ("masaya", "Masaya", "Masaya"),
               ("granada", "Granada", "Granada"), ("leon", "León", "León"),
               ("león", "León", "León"), ("jinotepe", "Jinotepe", "Carazo"),
               ("somoto", "Somoto", "Madriz"), ("matagalpa", "Matagalpa", "Matagalpa"),
               ("esteli", "Estelí", "Estelí"), ("estelí", "Estelí", "Estelí")]


def municipio_de(loc):
    low = " " + loc.lower() + " "
    for tok, muni, depto in CIUDADES_NI:
        if tok in low:
            return muni, depto
    return "", ""


def main():
    cache = json.load(open(CACHE_F, encoding="utf-8")) if os.path.exists(CACHE_F) else {}
    resumen = {"ok": 0, "fail": 0}
    filas = list(csv.DictReader(open("sovinic_venta.csv", encoding="utf-8-sig")))
    cols = list(filas[0].keys()) + ["municipio", "departamento", "lat", "lng", "geo_tipo"]
    for f in filas:
        muni, depto = municipio_de(f["loc"])
        f["municipio"], f["departamento"] = muni, depto
        queries = [f"{f['loc']}, Nicaragua"]
        if muni:
            queries.append(f"{muni}, {depto}, Nicaragua")
        r = None
        for q in queries:
            if q in cache:
                r = cache[q]
            else:
                r = search(q)
                cache[q] = r
                with open(CACHE_F, "w", encoding="utf-8") as fo:
                    json.dump(cache, fo, ensure_ascii=False)
                time.sleep(1.1)
            if r:
                break
        if r:
            f["lat"] = r["lat"]
            f["lng"] = r["lon"]
            f["geo_tipo"] = r.get("type", "")
            resumen["ok"] += 1
        else:
            f["lat"] = f["lng"] = f["geo_tipo"] = ""
            resumen["fail"] += 1
    with open("sovinic_venta.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.DictWriter(fo, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"geocodificado: ok={resumen['ok']} fail={resumen['fail']}")


if __name__ == "__main__":
    main()
