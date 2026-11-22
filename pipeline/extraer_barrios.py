
# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
#!/usr/bin/env python3
"""Descarga barrios y residenciales nombrados del Área Metropolitana de Managua
desde OpenStreetMap (Overpass) → barrios_managua.geojson.

Fuentes:
  - place=neighbourhood|quarter|suburb  → barrios/sectores (polígonos y nodos)
  - landuse=residential con nombre      → residenciales/urbanizaciones
Un nombre puede venir de varios ways/relations → se fusiona en MultiPolygon.
Cache del XML crudo en geocache_barrios_raw.json (borrar para re-consultar).
"""
import json
import os
import urllib.parse
import urllib.request

BBOX = "12.0,-86.48,12.26,-86.10"
RUTA_OUT = "barrios_managua.geojson"
RUTA_CACHE = "geocache_barrios_raw.json"
UA = "analisis-bienes-raices/1.0 (pipeline local)"

QUERY = """[out:json][timeout:120];
(
  nwr["place"~"^(neighbourhood|quarter|suburb)$"](%(bb)s);
  nwr["landuse"="residential"]["name"~"."](%(bb)s);
);
out geom;""" % {"bb": BBOX}


def pedir_overpass():
    if os.path.exists(RUTA_CACHE):
        with open(RUTA_CACHE) as f:
            return json.load(f)
    print("Consultando Overpass (puede tardar ~1 min)…")
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        js = json.loads(r.read())
    with open(RUTA_CACHE, "w") as f:
        json.dump(js, f)
    return js


def ensamblar(segmentos):
    """Une segmentos por extremos → anillos cerrados [(lon, lat), …]."""
    pend = [list(map(tuple, s)) for s in segmentos]
    anillos = []
    while pend:
        a = pend.pop(0)
        cambio = True
        while cambio:
            cambio = False
            for s in list(pend):
                if s[0] == a[-1]:
                    a += s[1:]
                elif s[-1] == a[0]:
                    a = s[:-1] + a
                elif s[-1] == a[-1]:
                    a += s[::-1][1:]
                elif s[0] == a[0]:
                    a = s[1:][::-1] + a
                else:
                    continue
                pend.remove(s)
                cambio = True
        if len(a) >= 4:
            if a[0] != a[-1]:
                a.append(a[0])
            anillos.append(a)
    return anillos


def r5(v):
    return round(v, 5)


def main():
    js = pedir_overpass()
    els = js.get("elements", [])
    por_nombre = {}
    nodos = []
    for e in els:
        tags = e.get("tags") or {}
        nombre = (tags.get("name") or "").strip()
        if not nombre:
            continue
        tipo = ("barrio" if tags.get("place") in ("neighbourhood", "quarter",
                                                  "suburb") else "residencial")
        if e["type"] == "node":
            nodos.append({"nombre": nombre, "tipo": tipo,
                          "lat": e["lat"], "lng": e["lon"]})
        elif e["type"] == "way":
            g = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
            if len(g) >= 4:
                por_nombre.setdefault(nombre, {"tipo": tipo, "rings": []})["rings"].append(g)
        elif e["type"] == "relation":
            outs = [(p["lon"], p["lat"]) for m in e.get("members", [])
                    if m.get("role") in ("", "outer") and m.get("geometry")
                    for p in m["geometry"]]
            for anillo in ensamblar([outs]):
                por_nombre.setdefault(nombre, {"tipo": tipo, "rings": []})["rings"].append(anillo)

    features = []
    for nombre, d in por_nombre.items():
        rings = []
        for a in d["rings"]:
            rr = [(r5(x), r5(y)) for x, y in a]
            if rr[0] != rr[-1]:
                rr.append(rr[0])
            if len(rr) >= 4:
                rings.append(rr)
        if not rings:
            continue
        geom = ({"type": "Polygon", "coordinates": rings} if len(rings) == 1
                else {"type": "MultiPolygon", "coordinates": [[r] for r in rings]})
        features.append({"type": "Feature",
                         "properties": {"nombre": nombre, "tipo": d["tipo"]},
                         "geometry": geom})
    for n in nodos:
        features.append({"type": "Feature",
                         "properties": {"nombre": n["nombre"], "tipo": n["tipo"],
                                        "nodo": True},
                         "geometry": {"type": "Point",
                                      "coordinates": [r5(n["lng"]), r5(n["lat"])]}})

    gj = {"type": "FeatureCollection", "features": features}
    with open(RUTA_OUT, "w") as f:
        json.dump(gj, f, ensure_ascii=False)
    polis = sum(1 for x in features if "nodo" not in x["properties"])
    print(f"{len(features)} zonas → {RUTA_OUT} "
          f"({polis} polígonos, {len(nodos)} nodos)")


if __name__ == "__main__":
    main()
