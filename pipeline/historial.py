"""Histórico de datos: snapshots, diffs entre extracciones y serie para el sitio.

Uso:
  python3 pipeline/historial.py --snapshot              # snapshot de la extracción actual
  python3 pipeline/historial.py --desde-git <sha>       # snapshot reconstruido de un commit
  python3 pipeline/historial.py --diff                  # diff entre los dos últimos snapshots
  python3 pipeline/historial.py --serie                 # docs/data/historico.json

Un snapshot guarda, por listado (clave ``fuente:id``), solo lo necesario para medir
cambios: precio, m², lote, zona, distrito, flag de casa y coordenadas redondeadas.
"""
import argparse
import datetime
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rutas  # noqa: E402

V = 1
CLAVES_STATS = ("global", "casas", "kw", "qc", "mb", "sv", "dn", "casas_fuente", "repetidos")


def _r(x, nd=0):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd)


def _leer_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _leer_de_git(sha, ruta):
    out = subprocess.run(["git", "show", f"{sha}:{ruta}"], check=True,
                         capture_output=True, text=True, cwd=rutas.REPO)
    return json.loads(out.stdout)


def construir_snapshot(listados, stats, origen):
    """Arma el snapshot compacto a partir de listados.json + stats.json."""
    fecha = stats.get("fecha") or datetime.date.today().isoformat()
    l = {}
    for x in listados:
        clave = f"{x.get('fuente')}:{x.get('id')}"
        l[clave] = {
            "p": _r(x.get("p")),
            "m": _r(x.get("m2")),
            "l": _r(x.get("lote")),
            "z": x.get("zona") or "",
            "d": x.get("distrito") or "",
            "c": 1 if x.get("casa") else 0,
            "a": _r(x.get("lat"), 4),
            "o": _r(x.get("lng"), 4),
        }
    return {
        "v": V,
        "fecha": fecha,
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "origen": origen,
        "stats": {k: stats.get(k) for k in CLAVES_STATS if k in stats},
        "n": len(l),
        "l": l,
    }


def guardar_snapshot(snap):
    rutas.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    destino = rutas.SNAPSHOTS / f"{snap['fecha']}.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    kb = destino.stat().st_size / 1024
    print(f"snapshot {snap['fecha']}: {snap['n']} listados → {destino.relative_to(rutas.REPO)} ({kb:.0f} KB)")
    return destino


def snapshot_desde_csv(directorio, fecha):
    """Reconstruye un snapshot aplicando la misma consolidación a un directorio de
    CSV crudos (p. ej. un backup), para backfill de la serie histórica."""
    import generar_datos as gd

    gd.ANALISIS = str(directorio)
    items = (list(gd.kw_rows()) + list(gd.qc_rows()) + list(gd.mb_rows())
             + list(gd.sv_rows()) + list(gd.dn_rows()))
    unicos, dups = gd.dedupe(items)
    for x in unicos:
        b = gd.barrio_de(x["lat"], x["lng"])
        if b and b != x["zona"]:
            x["zona_orig"] = x["zona"]
            x["zona"] = b
    stats = {
        "fecha": fecha,
        "global": {"n": len(unicos)},
        "casas": {"n": sum(1 for x in unicos if x["casa"])},
        **{f: {"n": sum(1 for x in unicos if x["fuente"] == f)}
           for f in ("kw", "qc", "mb", "sv", "dn")},
        "repetidos": dups,
    }
    listados = [{"fuente": x["fuente"], "id": x["id"], "p": x["p"], "m2": x["m2"],
                 "lote": x["lote"], "zona": x["zona"], "distrito": x["distrito"],
                 "casa": x["casa"], "lat": x["lat"], "lng": x["lng"]} for x in unicos]
    return guardar_snapshot(construir_snapshot(listados, stats, f"csv:{Path(directorio).name}"))


def _lista_snapshots():
    return sorted(rutas.SNAPSHOTS.glob("*.json"))


def _pct(antes, despues):
    if not antes or not despues:
        return None
    return (despues - antes) / antes * 100.0


def _resumen_precio(snap_a, snap_b, comunes):
    cambios = []
    for k in comunes:
        pa, pb = snap_a["l"][k].get("p"), snap_b["l"][k].get("p")
        if pa and pb:
            cambios.append((k, pa, pb, _pct(pa, pb)))
    pcts = [c[3] for c in cambios if c[3] is not None]
    if not pcts:
        return {"con_precio": 0}
    pcts.sort()
    subieron = sum(1 for p in pcts if p > 0.5)
    bajaron = sum(1 for p in pcts if p < -0.5)
    iguales = len(pcts) - subieron - bajaron
    mayor_sub = max(cambios, key=lambda c: c[3] if c[3] is not None else -9e9)
    mayor_baj = min(cambios, key=lambda c: c[3] if c[3] is not None else 9e9)
    # la mayoría de avisos vigentes conserva el precio: la variación real se mide
    # sobre los que sí cambiaron, y la proporción de cambios va aparte
    cambios_pct = sorted(round(p, 2) for p in pcts if abs(p) > 0.5)
    return {
        "con_precio": len(pcts),
        "subieron": subieron,
        "bajaron": bajaron,
        "iguales": iguales,
        "cambiaron": len(cambios_pct),
        "pct_cambiaron": round(len(cambios_pct) / len(pcts) * 100, 2),
        "mediana_pct": round(statistics.median(pcts), 2),
        "media_pct": round(statistics.mean(pcts), 2),
        "p25_pct": round(pcts[len(pcts) // 4], 2),
        "p75_pct": round(pcts[3 * len(pcts) // 4], 2),
        "mediana_pct_cambios": round(statistics.median(cambios_pct), 2) if cambios_pct else None,
        "media_pct_cambios": round(statistics.mean(cambios_pct), 2) if cambios_pct else None,
        "p25_pct_cambios": round(cambios_pct[len(cambios_pct) // 4], 2) if cambios_pct else None,
        "p75_pct_cambios": round(cambios_pct[3 * len(cambios_pct) // 4], 2) if cambios_pct else None,
        "mayor_subida": _detalle_cambio(snap_b, mayor_sub),
        "mayor_bajada": _detalle_cambio(snap_b, mayor_baj),
    }


def _detalle_cambio(snap, cambio):
    k, pa, pb, pct = cambio
    it = snap["l"][k]
    return {"id": k, "zona": it.get("z"), "distrito": it.get("d"),
            "antes": pa, "despues": pb, "pct": round(pct, 2) if pct is not None else None}


def _fuente(clave):
    return clave.split(":", 1)[0]


def _zona(clave, snap):
    return snap["l"][clave].get("z") or "(sin zona)"


def construir_diff(snap_a, snap_b):
    a, b = set(snap_a["l"]), set(snap_b["l"])
    nuevos, retirados = sorted(b - a), sorted(a - b)
    comunes = sorted(a & b)

    por_fuente = {}
    for f in ("kw", "qc", "mb", "sv", "dn"):
        fa = {k for k in a if _fuente(k) == f}
        fb = {k for k in b if _fuente(k) == f}
        com = fa & fb
        res = _resumen_precio(snap_a, snap_b, com)
        por_fuente[f] = {
            "antes": len(fa), "ahora": len(fb),
            "nuevos": len(fb - fa), "retirados": len(fa - fb),
            "comunes": len(com),
            "subieron": res.get("subieron", 0),
            "bajaron": res.get("bajaron", 0),
            "cambiaron": res.get("cambiaron", 0),
            "mediana_pct": res.get("mediana_pct"),
            "mediana_pct_cambios": res.get("mediana_pct_cambios"),
        }

    zonas = {}
    for k in comunes:
        z = _zona(k, snap_b)
        d = zonas.setdefault(z, {"zona": z, "nuevos": 0, "retirados": 0, "comunes": 0, "_pcts": []})
        d["comunes"] += 1
        pa, pb = snap_a["l"][k].get("p"), snap_b["l"][k].get("p")
        pc = _pct(pa, pb)
        if pc is not None:
            d["_pcts"].append(pc)
    for k in nuevos:
        d = zonas.setdefault(_zona(k, snap_b), {"zona": _zona(k, snap_b), "nuevos": 0,
                                                "retirados": 0, "comunes": 0, "_pcts": []})
        d["nuevos"] += 1
    for k in retirados:
        z = _zona(k, snap_a)
        d = zonas.setdefault(z, {"zona": z, "nuevos": 0, "retirados": 0, "comunes": 0, "_pcts": []})
        d["retirados"] += 1
    for d in zonas.values():
        p = d.pop("_pcts")
        d["mediana_pct"] = round(statistics.median(p), 2) if p else None
    lista_zonas = sorted(zonas.values(), key=lambda d: -(d["nuevos"] + d["retirados"] + d["comunes"]))

    return {
        "v": V,
        "desde": snap_a["fecha"],
        "hasta": snap_b["fecha"],
        "n": {"desde": snap_a["n"], "hasta": snap_b["n"], "delta": snap_b["n"] - snap_a["n"]},
        "nuevos": nuevos,
        "retirados": retirados,
        "comunes": len(comunes),
        "precio": _resumen_precio(snap_a, snap_b, comunes),
        "por_fuente": por_fuente,
        "por_zona": lista_zonas[:25],
        "zonas_totales": len(lista_zonas),
    }


def guardar_diff(diff):
    rutas.DIFFS.mkdir(parents=True, exist_ok=True)
    destino = rutas.DIFFS / f"{diff['hasta']}.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False, indent=1)
    print(f"diff {diff['desde']} → {diff['hasta']} → {destino.relative_to(rutas.REPO)}")
    return destino


def imprimir_diff(d):
    n, p = d["n"], d["precio"]
    print(f"\n=== {d['desde']} → {d['hasta']} ===")
    print(f"listados: {n['desde']} → {n['hasta']}  (Δ {n['delta']:+d})")
    print(f"nuevos: {len(d['nuevos'])}   retirados: {len(d['retirados'])}   permanecen: {d['comunes']}")
    if p.get("con_precio"):
        print(f"precio (n={p['con_precio']} avisos vigentes): {p['subieron']} subieron · "
              f"{p['bajaron']} bajaron · {p['iguales']} igual ({p['pct_cambiaron']:.1f}% cambió)")
        if p.get("cambiaron"):
            print(f"  entre los {p['cambiaron']} que cambiaron: mediana "
                  f"{p['mediana_pct_cambios']:+.2f}%  p25 {p['p25_pct_cambios']:+.2f}%  "
                  f"p75 {p['p75_pct_cambios']:+.2f}%")
    for f, x in d["por_fuente"].items():
        print(f"  {f:>3}: {x['antes']:>4} → {x['ahora']:>4}  +{x['nuevos']:<4} -{x['retirados']:<4} "
              f"+{x['subieron']}/-{x['bajaron']} precios")


def construir_serie(con_diffs=True):
    extracciones = []
    for ruta in _lista_snapshots():
        snap = _leer_json(ruta)
        st = snap.get("stats") or {}
        precios = sorted(v["p"] for v in snap["l"].values() if v.get("p"))
        fila = {
            "fecha": snap["fecha"],
            "listados": snap["n"],
            "casas": (st.get("casas") or {}).get("n"),
            "mediana": round(statistics.median(precios)) if precios else None,
            "promedio": round(statistics.mean(precios)) if precios else None,
            "por_fuente": {f: (st.get(f) or {}).get("n", 0) for f in ("kw", "qc", "mb", "sv", "dn")},
            "nuevos": None,
            "retirados": None,
            "mediana_pct": None,
            "mediana_pct_cambios": None,
        }
        if con_diffs:
            druta = rutas.DIFFS / f"{snap['fecha']}.json"
            if druta.exists():
                d = _leer_json(druta)
                fila["nuevos"] = len(d["nuevos"])
                fila["retirados"] = len(d["retirados"])
                fila["mediana_pct"] = (d.get("precio") or {}).get("mediana_pct")
                fila["mediana_pct_cambios"] = (d.get("precio") or {}).get("mediana_pct_cambios")
                fila["pct_cambiaron"] = (d.get("precio") or {}).get("pct_cambiaron")
        extracciones.append(fila)

    ultimo_cambio = None
    if con_diffs and extracciones:
        druta = rutas.DIFFS / f"{extracciones[-1]['fecha']}.json"
        if druta.exists():
            d = _leer_json(druta)
            ultimo_cambio = {
                "desde": d["desde"], "hasta": d["hasta"],
                "nuevos": len(d["nuevos"]), "retirados": len(d["retirados"]),
                "comunes": d["comunes"], "precio": d.get("precio") or {},
                "por_fuente": d.get("por_fuente") or {},
                "zonas": (d.get("por_zona") or [])[:10],
            }
    serie = {"v": V,
             "generado": datetime.datetime.now().isoformat(timespec="seconds"),
             "extracciones": extracciones,
             "ultimo_cambio": ultimo_cambio}
    rutas.PUB.mkdir(parents=True, exist_ok=True)
    destino = rutas.publicado("historico.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(serie, f, ensure_ascii=False, indent=1)
    print(f"serie: {len(extracciones)} extracciones → {destino.relative_to(rutas.REPO)}")
    return serie


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", action="store_true", help="snapshot de la extracción actual")
    ap.add_argument("--desde-git", metavar="SHA", help="snapshot reconstruido de un commit")
    ap.add_argument("--desde-csv", metavar="DIR",
                    help="snapshot reconstruido desde un directorio de CSV crudos (backfill)")
    ap.add_argument("--fecha", help="fecha a usar con --desde-csv (YYYY-MM-DD)")
    ap.add_argument("--diff", action="store_true", help="diff entre los dos últimos snapshots")
    ap.add_argument("--serie", action="store_true", help="regenera docs/data/historico.json")
    args = ap.parse_args()

    if not (args.snapshot or args.desde_git or args.desde_csv or args.diff or args.serie):
        ap.print_help()
        return 1

    if args.desde_git:
        listados = _leer_de_git(args.desde_git, "docs/data/listados.json")
        stats = _leer_de_git(args.desde_git, "docs/data/stats.json")
        guardar_snapshot(construir_snapshot(listados, stats, f"git:{args.desde_git[:7]}"))

    if args.desde_csv:
        if not args.fecha:
            print("--desde-csv requiere --fecha", file=sys.stderr)
            return 1
        snapshot_desde_csv(Path(args.desde_csv), args.fecha)

    if args.snapshot:
        listados = _leer_json(rutas.publicado("listados.json"))
        stats = _leer_json(rutas.publicado("stats.json"))
        guardar_snapshot(construir_snapshot(listados, stats, "extraccion"))

    if args.diff:
        snaps = _lista_snapshots()
        if len(snaps) < 2:
            print("se necesitan al menos 2 snapshots para un diff", file=sys.stderr)
            return 1
        a, b = _leer_json(snaps[-2]), _leer_json(snaps[-1])
        diff = construir_diff(a, b)
        guardar_diff(diff)
        imprimir_diff(diff)

    if args.serie:
        construir_serie()
    return 0


if __name__ == "__main__":
    sys.exit(main())
