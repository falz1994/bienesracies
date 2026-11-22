"""Extrae todos los listados de kwnicaragua.kw.com vía su API GraphQL pública.

Output: kw_listados_venta.csv / kw_listados_alquiler.csv + kw_listados.json
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import csv
import json
import time
import urllib.request

GRAPHQL = "https://graph.prod.consumer.kw.com/"
ORIGIN = "https://kwnicaragua.kw.com"

# Viewport de todo el país (el mismo que usa el sitio en el link "Nicaragua")
BOUNDS_PAIS = [14.580392335841047, -82.91656474609374, 11.16438886059978, -87.11883525390624]

QUERY = """query ListingSearch($location: Location!, $filters: SearchFilters, $sorting: Sorting, $first: Float, $after: Float) {
  listings(location: $location, filters: $filters, sorting: $sorting, first: $first, after: $after) {
    listings {
      id
      description
      pricing { sale { amount currency } rent { amount currency } sold { amount currency } }
      address { displayAddress streetName streetNo zipcode city state unitNo country primaryAddress secondaryAddress }
      images
      facets {
        bedrooms bathrooms
        homeSize { value unitType }
        lotSize { value unitType }
      }
      listingDate
      geometry { type coordinates }
      listingCategory
      propertyType
      mlsId
      mlsNumber
      urlPath
      listingStatus
      mlsListStatus
      closeDate
      listingPublishDateTime
    }
    totalCount
    groupedResults {
      grouped { id duplicates { id mlsId urlPath relationship } }
    }
  }
}"""


def buscar(categoria, first=300, after=0):
    variables = {
        "location": {"boundaryIds": [], "viewport": {"bounds": BOUNDS_PAIS}},
        "filters": {
            "listingCategory": [categoria],
            "listingStatus": ["active", "comingSoon"],
            "brandedSiteOrgId": 6293,
            "hideVowListings": True,
        },
        "sorting": {"sortBy": "listingUpdateDate", "sortDirection": "desc"},
        "first": first,
        "after": after,
    }
    payload = json.dumps({"query": QUERY, "variables": variables, "operationName": None}).encode()
    req = urllib.request.Request(GRAPHQL, data=payload, headers={
        "Content-Type": "application/json",
        "Origin": ORIGIN,
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def extraer_categoria(categoria):
    listados, duplicados = {}, set()
    total, after = None, 0
    while True:
        data = buscar(categoria, 300, after)
        if data.get("errors"):
            raise SystemExit(f"GraphQL errors: {data['errors']}")
        bloque = data["data"]["listings"]
        total = bloque["totalCount"]
        for l in bloque["listings"]:
            listados[l["id"]] = l
        for g in (bloque.get("groupedResults") or {}).get("grouped") or []:
            for d in (g.get("duplicates") or []):
                duplicados.add(d["id"])
        print(f"  {categoria}: {len(listados)}/{total} (after={after})", flush=True)
        after += 300
        if len(listados) >= total or not bloque["listings"]:
            break
        time.sleep(1)
    for lid in duplicados & set(listados):
        listados[lid]["_es_duplicado"] = True
    return list(listados.values()), total


def main():
    out = {}
    for categoria in ("sale", "rent"):
        print(f"Extrayendo {categoria}...")
        listados, total = extraer_categoria(categoria)
        out[categoria] = listados
        print(f"  {categoria}: {len(listados)} únicos (total={total})")
    with open("kw_listados.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    cols = ["id", "categoria", "precio", "moneda", "precio_usd", "lat", "lng",
            "ciudad", "direccion", "calle", "numero", "zip", "habitaciones", "banos",
            "area_m2", "area_unidad", "lote_m2", "lote_unidad", "estado", "mls_estado",
            "tipo_propiedad", "mls", "mls_numero", "url", "fecha_publicacion",
            "es_duplicado", "imagen", "descripcion"]

    def m2(valor, unidad):
        if valor is None:
            return ""
        u = (unidad or "").upper()
        if u.startswith("SQFT") or u in ("SQ FT", "FT"):
            return round(valor * 0.092903, 1)
        if u.startswith("HA"):
            return round(valor * 10000, 1)
        return valor  # ya en m² (o varas² se deja tal cual, se nota en la col unidad)

    for categoria, listados in out.items():
        with open(f"kw_listados_{'venta' if categoria == 'sale' else 'alquiler'}.csv", "w",
                  newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for l in listados:
                a, fc, geo = l.get("address") or {}, l.get("facets") or {}, l.get("geometry") or {}
                coords = geo.get("coordinates") or [None, None]
                p = (l.get("pricing") or {}).get(categoria) or {}
                hs, ls = fc.get("homeSize") or {}, fc.get("lotSize") or {}
                imgs = l.get("images") or []
                w.writerow({
                    "id": l["id"],
                    "categoria": categoria,
                    "precio": (p or {}).get("amount"),
                    "moneda": (p or {}).get("currency"),
                    "precio_usd": "",  # se llena en el análisis
                    "lat": coords[1],
                    "lng": coords[0],
                    "ciudad": a.get("city"),
                    "direccion": a.get("displayAddress"),
                    "calle": a.get("streetName"),
                    "numero": a.get("streetNo"),
                    "zip": a.get("zipcode"),
                    "habitaciones": fc.get("bedrooms"),
                    "banos": fc.get("bathrooms"),
                    "area_m2": m2(hs.get("value"), hs.get("unitType")),
                    "area_unidad": hs.get("unitType"),
                    "lote_m2": m2(ls.get("value"), ls.get("unitType")),
                    "lote_unidad": ls.get("unitType"),
                    "estado": l.get("listingStatus"),
                    "mls_estado": l.get("mlsListStatus"),
                    "tipo_propiedad": l.get("propertyType"),
                    "mls": l.get("mlsId"),
                    "mls_numero": l.get("mlsNumber"),
                    "url": f"{ORIGIN}{l.get('urlPath') or ''}",
                    "fecha_publicacion": l.get("listingPublishDateTime") or l.get("listingDate"),
                    "es_duplicado": bool(l.get("_es_duplicado")),
                    "imagen": imgs[0] if imgs else "",
                    "descripcion": (l.get("description") or "").replace("\n", " ")[:2000],
                })
        print(f"CSV {categoria} escrito")


if __name__ == "__main__":
    main()
