"""Geocodifica las zonas de momotomborealestate.com (nombre → lat/lng) con Nominatim.

Query: "zona, municipio, departamento, Nicaragua" (+ fallback sin zona).
Cache en geocache_mb.json, 1 req/seg. Añade lat, lng, geo_tipo al CSV.
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

CACHE_F = "geocache_mb.json"
UA = "analisis-managua/1.0 (geocodificacion momotombo)"


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


def geocode(zona, muni, depto, cache):
    partes = [p for p in (zona, muni or depto, depto) if p]
    queries = [", ".join(partes + ["Nicaragua"])]
    if zona:
        queries.append(", ".join([p for p in (muni, depto) if p] + ["Nicaragua"]))
    for q in queries:
        if q in cache:
            r = cache[q]
        else:
            r = search(q)
            cache[q] = r
            with open(CACHE_F, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            time.sleep(1.1)
        if r:
            return r
    return None


def main():
    cache = json.load(open(CACHE_F, encoding="utf-8")) if os.path.exists(CACHE_F) else {}
    resumen = {"ok": 0, "fallback": 0, "fail": 0}
    filas = list(csv.DictReader(open("momotombo_venta.csv", encoding="utf-8-sig")))
    cols = list(filas[0].keys()) + ["lat", "lng", "geo_tipo"]
    for f in filas:
        r = geocode(f["zona"], f["municipio"], f["departamento"], cache)
        if r:
            f["lat"] = r["lat"]
            f["lng"] = r["lon"]
            f["geo_tipo"] = r.get("type", "")
            resumen["ok" if f["zona"] else "fallback"] += 1
        else:
            f["lat"] = f["lng"] = f["geo_tipo"] = ""
            resumen["fail"] += 1
    with open("momotombo_venta.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.DictWriter(fo, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"geocodificado: ok={resumen['ok']} fallback={resumen['fallback']} fail={resumen['fail']}")


if __name__ == "__main__":
    main()
