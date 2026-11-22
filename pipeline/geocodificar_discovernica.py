"""Geocodifica las zonas de discovernica.com (zona → lat/lng).

Estrategia (Nominatim no conoce bien los barrios si no se le dice la ciudad):
  1. "{zona}, Nicaragua" y "{zona}, Managua, Nicaragua"
  2. Se acepta el primer resultado DENTRO del BBOX metro (12.0–12.26, -86.48–-86.10);
     fuera del BBOX se descarta (evita el Santo Domingo de Chontales, Las Colinas de
     Diriamba, etc.)
  3. Zonas con keyword de otra ciudad (Granada, Masaya, Diriamba...) → no se
     geocodifican: quedan excluidas por municipio.
Cache en geocache_dn.json, 1 req/seg. Añade lat, lng, geo_tipo, municipio,
departamento al CSV.
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

CACHE_F = "geocache_dn.json"
UA = "analisis-managua/1.0 (geocodificacion discovernica)"
BBOX = {"s": 12.0, "n": 12.26, "o": -86.48, "e": -86.10}

# keywords de municipios NO metro → skip (excluidos por municipio después)
OTROS_MUNIS = {"granada": "Granada", "masaya": "Masaya", "nindiri": "Nindirí",
               "nindirí": "Nindirí", "masatepe": "Masatepe", "diriamba": "Diriamba",
               "jinotepe": "Jinotepe", "leon": "León", "león": "León",
               "matagalpa": "Matagalpa", "esteli": "Estelí", "estelí": "Estelí",
               "rivas": "Rivas", "somoto": "Somoto", "juigalpa": "Juigalpa"}


def search(q):
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1,
                                     "countrycodes": "ni", "accept-language": "es",
                                     "addressdetails": 1}))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            datos = json.load(r)
        return datos[0] if datos else None
    except Exception as e:
        print(f"  [warn] {q[:50]}: {e}")
        time.sleep(3)
        return None


def en_bbox(r):
    try:
        lat, lng = float(r["lat"]), float(r["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return BBOX["s"] <= lat <= BBOX["n"] and BBOX["o"] <= lng <= BBOX["e"]


def municipio_de(zona):
    low = " " + zona.lower() + " "
    for tok, muni in OTROS_MUNIS.items():
        if tok in low:
            return muni
    if "managua" in low or "ciudad sandino" in low or "ticuantepe" in low:
        return "Managua"
    return ""


def muni_de_nominatim(r):
    addr = r.get("address") or {}
    muni = addr.get("city") or addr.get("municipality") or addr.get("town") or \
        addr.get("village") or addr.get("county") or ""
    depto = addr.get("state") or ""
    return muni, depto


def main():
    cache = json.load(open(CACHE_F, encoding="utf-8")) if os.path.exists(CACHE_F) else {}
    resumen = {"ok": 0, "fail": 0, "otro_muni": 0}
    filas = list(csv.DictReader(open("discovernica_venta.csv", encoding="utf-8-sig")))
    cols = list(filas[0].keys()) + ["municipio", "departamento", "lat", "lng", "geo_tipo"]
    for f in filas:
        zona = f["zona"]
        otro = municipio_de(zona)
        if otro and otro != "Managua":
            f["municipio"], f["departamento"] = otro, ""
            f["lat"] = f["lng"] = f["geo_tipo"] = ""
            resumen["otro_muni"] += 1
            continue
        base = zona or "Managua"
        queries = [f"{base}, Nicaragua"] + ([] if "managua" in base.lower() else
                                            [f"{base}, Managua, Nicaragua"])
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
            if r and en_bbox(r):
                break
            r = None
        if r:
            f["lat"] = r["lat"]
            f["lng"] = r["lon"]
            f["geo_tipo"] = r.get("type", "")
            muni, depto = muni_de_nominatim(r)
            f["municipio"] = muni or otro or ("Managua" if not zona else "")
            f["departamento"] = depto or ("Managua" if (muni or otro) else "")
            resumen["ok"] += 1
        else:
            f["lat"] = f["lng"] = f["geo_tipo"] = ""
            f["municipio"] = f["departamento"] = ""
            resumen["fail"] += 1
    with open("discovernica_venta.csv", "w", newline="", encoding="utf-8-sig") as fo:
        w = csv.DictWriter(fo, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"geocodificado: ok={resumen['ok']} otro_muni={resumen['otro_muni']} "
          f"fail={resumen['fail']}")


if __name__ == "__main__":
    main()
