"""Descarga los polígonos de los distritos de Managua desde OpenStreetMap/Overpass
y los guarda como GeoJSON (distritos_managua.geojson) para el sitio y el pipeline.

Overpass devuelve las ways miembro con geometría inline ("out geom"); aquí se
ensamblan los anillos (outer/inner) por puntos compartidos.
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import json
import urllib.parse
import urllib.request

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = '''[out:json][timeout:120];
rel["name"~"^Distrito [IVX]+$"]["boundary"="administrative"](11.90,-86.60,12.35,-86.05);
out geom;'''
SALIDA = "distritos_managua.geojson"
UA = "analisis-managua/1.0 (distritos de managua)"


def armar_anillos(ways):
    """Encadena ways (listas de (lat,lng)) en anillos cerrados por extremos compartidos."""
    anillos = []
    pend = [list(w) for w in ways]
    while pend:
        anillo = pend.pop(0)
        while anillo[0] != anillo[-1]:
            for i, x in enumerate(pend):
                if x[0] == anillo[-1]:
                    anillo.extend(x[1:])
                elif x[-1] == anillo[-1]:
                    anillo.extend(list(reversed(x))[1:])
                else:
                    continue
                pend.pop(i)
                break
            else:
                break  # extremo suelto: no se pudo cerrar
        if anillo[0] == anillo[-1]:
            anillos.append(anillo)
    return anillos


def main():
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode(
        {"data": QUERY}).encode(), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)

    features = []
    for rel in data.get("elements", []):
        if rel.get("type") != "relation":
            continue
        outers, inners = [], []
        for m in rel.get("members", []):
            if m.get("type") != "way" or "geometry" not in m:
                continue
            pts = [(p["lat"], p["lon"]) for p in m["geometry"]]
            (inners if m.get("role") == "inner" else outers).append(pts)
        if not outers:
            continue
        outers = armar_anillos(outers)
        inners = armar_anillos(inners)
        if not outers:
            continue
        # un solo outer → Polygon; varios → MultiPolygon (agujeros en el primero)
        def rings_poly(outer):
            return [[list(p)[::-1] for p in outer]] + \
                   [[[list(p)[::-1] for p in h] for h in inners]]
        if len(outers) == 1:
            geom = {"type": "Polygon", "coordinates": rings_poly(outers[0])}
        else:
            geom = {"type": "MultiPolygon",
                    "coordinates": [rings_poly(o) for o in outers]}
        features.append({"type": "Feature",
                         "properties": {"nombre": rel["tags"].get("name", "")},
                         "geometry": geom})

    geojson = {"type": "FeatureCollection", "features": features}
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))
    print(f"→ {SALIDA}: {len(features)} distritos "
          f"({', '.join(ft['properties']['nombre'] for ft in features)})")


if __name__ == "__main__":
    main()
