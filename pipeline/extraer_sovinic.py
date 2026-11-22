"""Extrae listados de sovinic.com.ni (WordPress/Elementor, sin API).

- Resultados server-rendered: /resultados-de-busqueda/ + /page/N/
- Sin coordenadas ni dirección estructurada: la ubicación se obtiene del slug de
  la URL de la propiedad ("casa-en-venta-managua-colonia-unidad-de-proposito")
  y se geocodifica aparte.
- Salida: sovinic_venta.csv (checkpoint por página).
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
import urllib.request

BASE = "https://www.sovinic.com.ni"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CATS = ("location&property_category%5B0%5D=casas&keyword&componentsbeds&componentsbaths"
        "&price_low=0&price_max=5500000&price_label_component_&submit=Buscar&elementor_form_id=31546")
PREFIJOS = ("venta-de-propiedad-en-", "se-venden-y-o-renta-casa-en-", "se-vende-casa-en-",
            "casa-amueblada-con-terreno-amplio-en-", "casa-con-terreno-amplio-en-",
            "casa-amplia-para-habitar-u-oficinas-en-", "propiedad-de-lujo-en-",
            "venta-renta-de-casa-de-lujo-en-", "casa-residencia-en-", "casa-de-lujo-en-",
            "venta-de-casa-de-lujo-en-", "casa-en-venta-en-", "casa-en-venta-",
            "casa-de-venta-en-", "casa-de-venta-", "venta-de-casa-", "casa-en-renta-",
            "casa-en-", "casas-en-", "venta-renta-de-", "venta-de-", "se-vende-",
            "ubicada-en-el-")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="ignore")


def limpiar(t):
    return ihtml.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()


def loc_de_slug(slug):
    s = slug.strip("/")
    low = s.lower()
    for p in PREFIJOS:
        if low.startswith(p):
            s = s[len(p):]
            break
    s = re.sub(r"\bkm-(\d+)-(\d+)\b", r"km \1.\2", s, flags=re.I)
    s = re.sub(r"klm|kilometro", "km", s, flags=re.I)
    s = re.sub(r"(-\d+)+$", "", s)
    partes = [p for p in s.split("-") if p and not p.isdigit()]
    while partes and partes[0].lower() in ("en", "de", "nicaragua"):
        partes.pop(0)
    if partes and partes[0].lower() in ("managua", "granada", "leon", "león", "masaya",
                                        "matagalpa", "jinotepe", "esteli", "estelí",
                                        "somoto", "nindiri", "ticuantepe", "nueva"):
        partes = partes[1:] + [partes[0]]
    return " ".join(partes)


def parsear_pagina(h):
    out = []
    for bloque in h.split("data-listid=")[1:]:
        lid = (re.match(r'"(\d+)"', bloque) or [None, ""])[1]
        m = re.search(r'href="(https://www\.sovinic\.com\.ni/propiedades/[^"]+)"', bloque)
        if not m:
            continue
        url = m.group(1)
        slug = url.split("/propiedades/")[-1]
        pm = re.search(r"price_wrapper[^>]*>\s*\$([\d,\.]+)", bloque)
        precio = pm.group(1).replace(",", "") if pm else ""

        def amen(titulo):
            x = re.search(r'title="' + titulo + r'"[^>]*>.*?</div>\s*([^<]+)</div>', bloque, re.S)
            return limpiar(x.group(1)) if x else ""

        hab = amen("Habitaciones")
        banos = amen("Baños")
        lote = amen("Tamaño del lote")
        area = amen("Área de la propiedad")
        img = re.search(r'<img[^>]*src="(https://[^"]*uploads/[^"]*)"', bloque)

        out.append({"id": lid, "titulo": limpiar(loc_de_slug(slug)), "slug": slug,
                    "loc": limpiar(loc_de_slug(slug)), "precio": precio, "moneda": "USD",
                    "hab": hab, "banos": banos, "lote": lote, "area": area,
                    "url": url, "imagen": img.group(1) if img else ""})
    return out


def main():
    cols = ["id", "titulo", "slug", "loc", "precio", "moneda", "hab", "banos", "lote",
            "area", "url", "imagen"]
    salida = "sovinic_venta.csv"
    vistos = {}
    if os.path.exists(salida):
        for r in csv.DictReader(open(salida, encoding="utf-8-sig")):
            vistos[r["id"]] = r

    todo = dict(vistos)
    pag, vacias = 1, 0
    while vacias < 3 and pag < 200:
        url = (f"{BASE}/resultados-de-busqueda/?{CATS}" if pag == 1 else
               f"{BASE}/resultados-de-busqueda/page/{pag}/?{CATS}")
        tarjetas = parsear_pagina(get(url))
        for t in tarjetas:
            if t["id"] and t["id"] not in vistos:
                todo[t["id"]] = t
        vacias = 0 if tarjetas else vacias + 1
        print(f"  pág {pag} → {len(tarjetas)} tarjetas, {len(todo)} únicos", flush=True)
        pag += 1
        time.sleep(0.8)
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(todo.values())
    print(f"→ {salida}: {len(todo)} listados")


if __name__ == "__main__":
    main()
