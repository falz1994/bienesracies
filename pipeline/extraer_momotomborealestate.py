"""Extrae listados de momotomborealestate.com (WordPress + Houzez, sin API).

- Resultados server-rendered en /search-result-page/?type[]=family-home con
  paginación /search-result-page/page/N/
- Sin coordenadas ni dirección: la ubicación se parsea del título
  ("Casa en Venta Dolores, Carazo, Dolores") y se geocodifica aparte.
- Salida: momotombo_venta.csv (checkpoint por página).
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import csv
import html as ihtml
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "https://momotomborealestate.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="ignore")


def limpiar(t):
    return ihtml.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()


def parsear_pagina(h):
    out = []
    for bloque in h.split("item-listing-wrap"):
        if "item-title" not in bloque:
            continue
        m = re.search(r'<a target=_\w*\s*href="([^"]+)"[^>]*>(.*?)</a>', bloque, re.S)
        if not m:
            continue
        url, titulo = m.group(1), limpiar(m.group(2))
        lid = re.search(r'data-listid="(\d+)"', bloque) or re.search(r"data-listing_id=\"(\d+)\"", bloque)
        codigo = (re.search(r"ID:\s*([A-Za-z0-9\-]+)", bloque) or [None, ""])[1]

        tipo = zona = depto = muni = oper = ""
        mm = re.search(r"(.+?)\s+en (Venta|Alquiler|Renta)\s+(.+)", titulo, re.I)
        if mm:
            tipo, oper, loc = mm.group(1).strip(), mm.group(2), mm.group(3).strip()
            partes = [p.strip() for p in loc.split(",")]
            if len(partes) >= 3:
                zona, depto, muni = partes[0], partes[1], partes[2]
            elif len(partes) == 2:
                zona, depto = partes
            elif partes:
                zona = partes[0]
        else:
            loc = titulo
            partes = [p.strip() for p in titulo.split(",")]
            if len(partes) >= 3:
                zona, depto, muni = partes[-3], partes[-2], partes[-1]
            elif len(partes) == 2:
                zona, depto = partes

        precio = ""
        pm = re.search(r"item-price[^>]*>\s*(?:<li[^>]*>)?\s*U\$([\d,\.]+)", bloque)
        if pm:
            precio = pm.group(1).replace(",", "")
        img = re.search(r'src="(https://[^"]*uploads/[^"]*)"', bloque)

        def am(p):
            x = re.search(p, bloque)
            return x.group(1) if x else ""

        out.append({
            "id": lid.group(1) if lid else "", "codigo": codigo, "titulo": titulo,
            "tipo": tipo, "operacion": oper.lower(), "zona": zona,
            "departamento": depto, "municipio": muni,
            "hab": am(r"Habitaci[oó]n(?:es)?:\s*(\d+)"),
            "banos": am(r"Cuartos de ba[ñn]o(?:s)?:\s*(\d+)"),
            "garaje": am(r"Garaje(?:s)?:\s*(\d+)"),
            "precio": precio, "moneda": "USD",
            "url": url, "imagen": img.group(1) if img else "",
        })
    return out


def main():
    cols = ["id", "codigo", "titulo", "tipo", "operacion", "zona", "departamento",
            "municipio", "hab", "banos", "garaje", "precio", "moneda", "url", "imagen"]
    salida = "momotombo_venta.csv"
    vistos = {}
    if os.path.exists(salida):
        for r in csv.DictReader(open(salida, encoding="utf-8-sig")):
            vistos[r["id"]] = r

    h1 = get(BASE + "/search-result-page/?type[]=family-home&keyword=&min-price=&max-price=&property_id=")
    max_pag = max([int(n) for n in re.findall(r"/page/(\d+)/", h1)] + [1])
    print(f"páginas detectadas: {max_pag}")

    todo = dict(vistos)
    vacias = 0
    for pag in range(1, max_pag + 1):
        url = (BASE + "/search-result-page/?type[]=family-home&keyword=&min-price=&max-price=&property_id="
               if pag == 1 else
               BASE + f"/search-result-page/page/{pag}/?type%5B0%5D=family-home&#038;keyword&#038;min-price&#038;max-price&#038;property_id")
        for t in parsear_pagina(get(url)):
            if t["id"] and t["id"] not in vistos:
                todo[t["id"]] = t
        print(f"  pág {pag}/{max_pag} → {len(todo)} únicos", flush=True)
        time.sleep(0.8)
        if pag % 5 == 0 or pag == max_pag:
            with open(salida, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(todo.values())
    print(f"→ {salida}: {len(todo)} listados")


if __name__ == "__main__":
    main()
