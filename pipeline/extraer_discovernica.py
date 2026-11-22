"""Extrae CASAS EN VENTA de discovernica.com (Discover Real Estate).

- API JSON pública: POST https://discovernica.com/properties/filter
  ({"limit":"3000","offset":0}) → las ~2,900 propiedades en una sola llamada.
- Filtro local: venta=1, categoria en {2,46,32,52} (Casas 1 piso, 2+ pisos/Townhouse,
  Quintas, Lujosas), estado="Disponible", precio no vacío. FUERA: apartamentos,
  terrenos, bodegas, edificios, fincas, playa.
- Sin coordenadas ni dirección estructurada: la zona se parsea del título
  ("... en Santo Domingo") y se geocodifica aparte.
- Salida: discovernica_venta.csv (sobrescribe: la API entrega todo de una vez).
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import csv
import json
import re
import urllib.request

API = "https://discovernica.com/properties/filter"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CATEGORIAS_CASA = {2, 46, 32, 52}  # 1 piso, 2+ pisos/Townhouse, Quintas, Lujosas
SALIDA = "discovernica_venta.csv"


def post(url, cuerpo):
    req = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


JUNK_RE = re.compile(r"^(?:venta|renta|venta/?renta|venta y renta|venta o renta|casa|casas|"
                     r"se vende|se alquila|quinta|condominio|residencial|propiedad|precio|"
                     r"oportunidad|etapa)\b", re.I)


def zona_de_titulo(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    t = re.sub(r"\bID\s*\d+\s*$", "", t, flags=re.I).strip()
    partes = t.split(" en ")
    z = partes[-1].strip() if len(partes) > 1 else t          # último " en " = la zona
    z = re.split(r"\s+[-–]\s+", z)[0].split(",")[0]           # "Santo Domingo - Zona exclusiva"
    z = re.sub(r"^(?:venta(?:\s*(?:y\s*o)?\s*renta)?|venta/?renta|venta\s+o\s+renta|renta)"
               r"\s+en\s+", "", z, flags=re.I)
    z = re.sub(r"^(?:condominio|residencial|casa|quinta)s?\s+en\s+", "", z, flags=re.I)
    z = re.sub(r"^\s*(?:la\s+ciudad\s+de|en)\s+", "", z, flags=re.I)
    z = re.sub(r"\s+(?:con|frente a|ideal|cerca|de la ciudad|excelente)\b.*$", "", z, flags=re.I)
    z = z.strip(" .,-")
    if JUNK_RE.match(z):  # el título no trae ubicación real
        return ""
    return z


def main():
    data = post(API, {"limit": "3000", "offset": 0})
    filas = []
    for r in data.get("data") or []:
        precio = (r.get("precio_venta") or "").strip()
        if r.get("venta") != 1 or r.get("categoria") not in CATEGORIAS_CASA:
            continue
        if (r.get("estado") or "").strip().lower() != "disponible" or not precio:
            continue
        filas.append({
            "id": r["id"],
            "titulo": re.sub(r"\s+", " ", r.get("tituloEsp") or "").strip(),
            "zona": zona_de_titulo(r.get("tituloEsp")),
            "categoria": r["categoria"],
            "precio": precio.replace(",", ""),
            "moneda": "USD",
            "hab": r.get("habitaciones") or "",
            "banos": r.get("banos") or "",
            "m2": (r.get("med_mts") or "").strip(),
            "lote_vrs": (r.get("med_vrs") or "").strip(),
            "url": f"https://discovernica.com/propiedades/detalles/{r['id']}/{(r.get('des_SeoEs') or 'x').strip() or 'x'}",
            "imagen": (f"https://discovernica.com/assets/images/properties/{r['pathImagen']}"
                       if r.get("pathImagen") and r["pathImagen"] != "0" else ""),
        })

    cols = ["id", "titulo", "zona", "categoria", "precio", "moneda", "hab", "banos",
            "m2", "lote_vrs", "url", "imagen"]
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"→ {SALIDA}: {len(filas)} casas en venta (Disponible) de "
          f"{len(data.get('data') or [])} listados")


if __name__ == "__main__":
    main()
