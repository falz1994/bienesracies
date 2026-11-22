"""Valida los datos publicados antes de commitear/deployar.

Comprueba invariantes del sitio y de la serie histórica. Sale con código 1 si
algo no cuadra, para que `run.sh` frene antes de publicar.

Uso: python3 pipeline/validar_datos.py
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rutas  # noqa: E402

BBOX = {"s": 11.98, "n": 12.26, "o": -86.48, "e": -86.10}
FUENTES = ("kw", "qc", "mb", "sv", "dn")

errores, avisos, ok = [], [], []


def check(cond, msg):
    (ok if cond else errores).append(msg)
    return cond


def leer(nombre):
    return json.loads(rutas.publicado(nombre).read_text(encoding="utf-8"))


def sha(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def main():
    listados = leer("listados.json")
    stats = leer("stats.json")
    zonas = leer("zonas.json")

    n = len(listados)
    check(n == stats["global"]["n"], f"listados.json ({n}) == stats.global.n ({stats['global']['n']})")
    casas = sum(1 for x in listados if x.get("casa"))
    check(casas == stats["casas"]["n"], f"casas ({casas}) == stats.casas.n ({stats['casas']['n']})")

    por_fuente = {f: sum(1 for x in listados if x.get("fuente") == f) for f in FUENTES}
    for f in FUENTES:
        check(por_fuente[f] > 0, f"fuente {f} con listados ({por_fuente[f]})")

    sin_coord = [x for x in listados if x.get("lat") is None or x.get("lng") is None]
    check(not sin_coord, f"sin coordenadas: {len(sin_coord)}")
    fuera = [x for x in listados
             if x.get("lat") is not None and not (BBOX["s"] <= x["lat"] <= BBOX["n"]
                                                  and BBOX["o"] <= x["lng"] <= BBOX["e"])]
    check(not fuera, f"fuera del BBOX metropolitano: {len(fuera)}")

    con_distrito = sum(1 for x in listados if x.get("distrito"))
    pct_dist = con_distrito / n * 100 if n else 0
    check(pct_dist >= 95, f"distrito asignado {pct_dist:.1f}% (>=95%)")
    sin_zona = sum(1 for x in listados if not (x.get("zona") or "").strip())
    check(sin_zona / n * 100 <= 5 if n else False, f"listados sin zona {sin_zona} (<=5%)")

    precios = [x["p"] for x in listados if x.get("p")]
    check(len(precios) > 0, f"precios válidos: {len(precios)}")
    check(all(p > 0 for p in precios), "ningún precio <= 0")
    sospechosos = sum(1 for p in precios if p < 5000)
    if sospechosos / len(precios) * 100 > 1:
        avisos.append(f"{sospechosos} precios < $5,000 ({sospechosos / len(precios) * 100:.1f}%)")

    check(bool(zonas.get("caras")) and bool(zonas.get("baratas")),
          f"zonas.json con caras ({len(zonas.get('caras', []))}) y baratas ({len(zonas.get('baratas', []))})")

    # CSVs publicados == copias de trabajo
    for nombre in rutas.CSVS:
        trabajo = rutas.DATOS / nombre
        si_no = rutas.publicado(nombre)
        if trabajo.exists() and si_no.exists():
            check(sha(trabajo) == sha(si_no), f"CSV {nombre} idéntico trabajo↔publicado")
    for nombre in rutas.GEOJSONS:
        check(rutas.publicado(nombre).exists(), f"geojson publicado {nombre}")

    # histórico
    serie = leer("historico.json")
    ex = serie.get("extracciones") or []
    fechas = [e["fecha"] for e in ex]
    check(len(ex) >= 2, f"serie histórica con {len(ex)} extracciones (>=2)")
    check(fechas == sorted(fechas), "serie ordenada por fecha")
    check(len(set(fechas)) == len(fechas), "sin fechas duplicadas en la serie")
    if ex:
        ultima = ex[-1]
        check(ultima["fecha"] == stats["fecha"],
              f"última extracción ({ultima['fecha']}) == stats.fecha ({stats['fecha']})")
        check(ultima["listados"] == stats["global"]["n"],
              f"última extracción con {ultima['listados']} listados == stats ({stats['global']['n']})")

    snap = rutas.SNAPSHOTS / f"{stats['fecha']}.json"
    if snap.exists():
        s = json.loads(snap.read_text(encoding="utf-8"))
        check(s["n"] == stats["global"]["n"], f"snapshot {stats['fecha']} tiene {s['n']} == stats")
    else:
        avisos.append(f"falta snapshot {snap.name}")

    # slides
    pngs = sorted(p for p in rutas.SLIDES_PUB.glob("*.png")) if rutas.SLIDES_PUB.exists() else []
    if pngs:
        check(len(pngs) >= 9, f"slides publicados: {len(pngs)}")

    print(f"errores={len(errores)} avisos={len(avisos)} checks_ok={len(ok)}")
    for e in errores:
        print(f"  ERROR   {e}")
    for a in avisos:
        print(f"  aviso   {a}")
    for o in ok:
        print(f"  ok      {o}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
