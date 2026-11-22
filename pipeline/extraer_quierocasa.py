"""Extrae todos los listados de quierocasa.com (venta + alquiler).

Los resultados son server-rendered en /resultados/venta-propiedades.htm y
/resultados/alquiler-propiedades.htm con paginación --N.htm (no hay API de datos;
fetchdata-sql.php es solo el autocompletado y ajax.beta.php los dropdowns).

Salida: quierocasa_venta.csv / quierocasa_alquiler.csv (checkpoint por página).
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

BASE = "https://www.quierocasa.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def limpiar(t):
    return ihtml.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()


def parsear_pagina(html):
    tarjetas = []
    for bloque in html.split('class="single-property"')[1:]:
        m = re.search(r'<a id="ttl\d+" class="titlelnk" href="([^"]+)"[^>]*>(.*?)</a>', bloque, re.S)
        if not m:
            continue
        url, titulo = m.group(1), limpiar(m.group(2))
        codigo = (re.search(r"/anuncio/([a-zA-Z0-9]+)/", url) or [None, ""])[1]

        tipo = zona = depto = muni = ""
        h3 = re.search(r"<h3[^>]*>(.*?)</h\d>", bloque, re.S)
        if h3:
            sub = limpiar(h3.group(1))
            mm = re.search(r"(.+?)\s+en (Venta|Alquiler)(?:\s+en\s+(.*))?$", sub, re.I)
            if mm:
                tipo = mm.group(1).strip()
                loc = mm.group(3) or ""
            else:
                loc = sub
            partes = [p.strip() for p in loc.split(",")]
            if len(partes) >= 3:
                zona, depto, muni = partes[0], partes[1], partes[2]
            elif len(partes) == 2:
                zona, depto = partes
            elif partes:
                zona = partes[0]

        desc = ""
        dp = re.search(r"</h\d>\s*<p[^>]*>(.*?)</p>", bloque, re.S)
        if dp:
            desc = limpiar(dp.group(1))

        def icono(alt):
            mm = re.search(rf'alt="{alt}"[^>]*/>([^<]*)', bloque)
            return limpiar(mm.group(1)) if mm else ""

        m2c = re.search(r'alt="área construida"[^>]*/>\s*([\d.,]+)\s*(\w[^\s<&]*)', bloque)
        ter = re.search(r'alt="área del terreno"[^>]*/>\s*([\d.,]+)\s*(\w[^\s<&]*)', bloque)

        precio = moneda = ""
        pm = re.search(r"<b>(Venta|Alquiler):\s*\$?\s*([\d.,]+)", bloque)
        if pm:
            moneda = "USD"
            precio = pm.group(2).replace(",", "")

        img = re.search(r'src="([^"]*/gallery/[^"]+)"', bloque)

        tarjetas.append({
            "codigo": codigo, "titulo": titulo, "tipo": tipo, "zona": zona,
            "departamento": depto, "municipio": muni,
            "hab": icono("habitaciones"), "banos": icono("baños"), "parqueos": icono("paqueos"),
            "m2_constr": m2c.group(1) if m2c else "", "unidad_m2": m2c.group(2) if m2c else "",
            "terreno": ter.group(1) if ter else "", "unidad_terreno": ter.group(2) if ter else "",
            "precio": precio, "moneda": moneda, "descripcion": desc[:1500],
            "url": url, "imagen": img.group(1) if img else "",
        })
    return tarjetas


def extraer(nombre, seccion, salida):
    cols = ["codigo", "titulo", "tipo", "zona", "departamento", "municipio", "hab", "banos",
            "parqueos", "m2_constr", "unidad_m2", "terreno", "unidad_terreno", "precio",
            "moneda", "descripcion", "url", "imagen"]
    vistos = {}
    if os.path.exists(salida):  # checkpoint: reanudar
        for r in csv.DictReader(open(salida, encoding="utf-8-sig")):
            vistos[r["codigo"]] = r

    base = f"{BASE}/resultados/{seccion}.htm"
    html0 = get(base)
    total = int((re.search(r"(\d+)\s+Propiedades", html0) or [None, "0"])[1])
    # la paginación del sitio es una ventana móvil; el número real de páginas es total/10
    max_pag = max(1, -(-total // 10))
    print(f"{nombre}: {total} propiedades, {max_pag} páginas")

    todo = dict(vistos)
    for pag in range(1, max_pag + 1):
        url = base if pag == 1 else f"{BASE}/resultados/{seccion}--{pag}.htm"
        for t in parsear_pagina(get(url)):
            if t["codigo"] and t["codigo"] not in vistos:
                todo[t["codigo"]] = t
        print(f"  pág {pag}/{max_pag} → {len(todo)} únicos", flush=True)
        time.sleep(0.7)
        if pag % 5 == 0 or pag == max_pag:  # checkpoint
            with open(salida, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(todo.values())
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(todo.values())
    print(f"  → {salida}: {len(todo)} listados\n")


if __name__ == "__main__":
    extraer("VENTA", "venta-propiedades", "quierocasa_venta.csv")
    extraer("ALQUILER", "alquiler-propiedades", "quierocasa_alquiler.csv")
