"""Clasifica qué listados de KW son casas habitacionales usando descripción + dirección.

- Tipos inherentemente casa → es_casa=True (Single Family Detached/Attached, Townhouse, Duplex)
- Tipos inherentemente NO casa → es_casa=False (Apartment, Office, Retail, Warehouse, Industrial,
  Hotel, Own Your Own, Stock Cooperative, Deeded Parking, Cabin)
- Resto (Other, Mobile Home, Manufactured, Mixed Use, Multi Family, Vacation Home, Business,
  Condominium, Agriculture, Unimproved Land, Timeshare, Ranch, Farm, Adult Community...)
  → clasificación por puntaje de palabras clave.

Salida: kw_casas_venta.csv / kw_casas_alquiler.csv (solo las filas es_casa=True,
con columnas extra: es_casa, origen_casa) + reporte en pantalla.
"""

# --- rutas del proyecto (inyectado por la migración) ---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from rutas import entrar_datos as _entrar_datos
if __name__ == "__main__":
    _entrar_datos()
import csv
import random
import re

AUTO_CASA = {"SINGLE FAMILY DETACHED", "SINGLE FAMILY ATTACHED", "TOWNHOUSE", "DUPLEX"}
AUTO_NO = {"APARTMENT", "OFFICE", "RETAIL", "WAREHOUSE", "INDUSTRIAL", "HOTEL MOTEL",
           "HOTEL-MOTEL", "OWN YOUR OWN", "STOCK COOPERATIVE", "DEEDED PARKING", "CABIN"}

POS_FUERTE = [r"\bcasas?\b", r"\bvivienda\b", r"\bresidencia\s", r"🏡", r"\bplanta alta\b",
              r"\bdos plantas\b", r"\bun nivel\b", r"\bdos niveles\b"]
POS_HAB = [r"\b\d+\s*(habitaciones|dormitorios|recamaras|recámaras)\b", r"\bhabitaciones\b",
           r"\bdormitorios\b", r"\bclosets?\b", r"\bsala[- ]comedor\b"]
NEG = [r"\bterrenos?\b", r"\blotes?\b", r"\bvara[s]?\b", r"\bv²\b", r"\bfinca\b", r"\bbodega",
       r"\blocal comercial\b", r"\bapartamentos?\b", r"\bproyecto\b", r"para construir",
       r"\bedificios?\b"]


def puntaje(texto):
    t = texto.lower()
    pos = sum(len(re.findall(p, t)) for p in POS_FUERTE) + 0.5 * sum(
        len(re.findall(p, t)) for p in POS_HAB)
    neg = sum(len(re.findall(p, t)) for p in NEG)
    if re.search(r"\bconstrucc[ií]on\b", t) and re.search(r"\bcasas?\b", t):
        pos += 1  # "Casa ... Construcción: 250m²" es casa segura
    return pos, neg


def es_casa(tipo, descripcion, direccion):
    """Retorna (bool, origen)."""
    t = (tipo or "").upper()
    if t in AUTO_CASA:
        return True, "tipo original"
    if t in AUTO_NO:
        return False, "tipo excluido"
    pos, neg = puntaje(f"{descripcion or ''} {direccion or ''}")
    ok = pos >= 2 and pos > neg
    return ok, ("keywords" if ok else f"keywords-rechazado (pos={pos:.1f}, neg={neg:.1f})")


def procesar(archivo, salida):
    filas = list(csv.DictReader(open(archivo, encoding="utf-8-sig")))
    resumen = {}
    casas = []
    for r in filas:
        ok, origen = es_casa(r["tipo_propiedad"], r["descripcion"], r["direccion"])
        r["es_casa"] = "True" if ok else "False"
        r["origen_casa"] = origen
        t = (r["tipo_propiedad"] or "").upper() or "OTRO"
        d = resumen.setdefault(t, {"n": 0, "casa": 0})
        d["n"] += 1
        if ok:
            d["casa"] += 1
            casas.append(r)

    cols = list(filas[0].keys())
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(casas)

    print(f"\n=== {archivo}: {len(filas)} filas → {len(casas)} casas ({salida})")
    for t, d in sorted(resumen.items(), key=lambda kv: -kv[1]["casa"]):
        print(f"  {t:28s} n={d['n']:4d}  casas={d['casa']:4d}")
    return casas, filas


def main():
    random.seed(7)
    for archivo, salida in (("kw_listados_venta.csv", "kw_casas_venta.csv"),
                            ("kw_listados_alquiler.csv", "kw_casas_alquiler.csv")):
        casas, todas = procesar(archivo, salida)

    # --- muestra para validar a ojo (solo venta) ---
    filas_venta = list(csv.DictReader(open("kw_listados_venta.csv", encoding="utf-8-sig")))
    rescata = [r for r in filas_venta
               if (r["tipo_propiedad"] or "").upper() not in AUTO_CASA
               and es_casa(r["tipo_propiedad"], r["descripcion"], r["direccion"])[0]]
    print(f"\n--- MUESTRA RESCATADAS ({len(rescata)} en venta fuera de Single Family) ---")
    for r in random.sample(rescata, min(8, len(rescata))):
        print(f"  [{(r['tipo_propiedad'] or '')[:12]:12s}] {(r['direccion'] or '')[:55]:55s} | "
              f"{(r['descripcion'] or '')[:60]}")

    posibles_perdidas = [r for r in filas_venta
                         if (r["tipo_propiedad"] or "").upper() not in AUTO_CASA | AUTO_NO
                         and re.search(r"\bcasas?\b", ((r["descripcion"] or "") + " " +
                                                       (r["direccion"] or "")).lower())
                         and not es_casa(r["tipo_propiedad"], r["descripcion"], r["direccion"])[0]]
    print(f"\n--- POSIBLES PERDIDAS ({len(posibles_perdidas)}) ---")
    for r in random.sample(posibles_perdidas, min(6, len(posibles_perdidas))):
        print(f"  [{(r['tipo_propiedad'] or '')[:12]:12s}] {(r['direccion'] or '')[:55]:55s} | "
              f"{(r['descripcion'] or '')[:60]}")


if __name__ == "__main__":
    main()
