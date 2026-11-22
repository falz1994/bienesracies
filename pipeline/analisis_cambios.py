"""Análisis de cambios entre dos extracciones.

Combina tres fuentes:
- los snapshots (`history/snapshots/<fecha>.json`) → qué pasó en el dataset consolidado;
- los CSV crudos del pipeline → qué pasó en cada portal (sin filtros ni dedupe);
- el backup de los CSV anteriores (`pipeline/datos/_backup_<fecha>/`).

Uso:
  python3 pipeline/analisis_cambios.py                       # las dos últimas extracciones
  python3 pipeline/analisis_cambios.py --desde 2026-09-03 --hasta 2026-11-21
  python3 pipeline/analisis_cambios.py --md history/analisis-2026-11-21.md
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rutas  # noqa: E402

CSV_FUENTE = {"kw": "kw_listados_venta.csv", "qc": "quierocasa_venta.csv",
              "mb": "momotombo_venta.csv", "sv": "sovinic_venta.csv",
              "dn": "discovernica_venta.csv"}
COL_ID = {"kw": ("id",), "qc": ("codigo",), "mb": ("id", "codigo"),
          "sv": ("id",), "dn": ("id",)}
PREFIJO = {"kw": "", "qc": "", "mb": "", "sv": "sv", "dn": "dn"}
NOMBRE = {"kw": "KW Nicaragua", "qc": "QuieroCasa", "mb": "Momotombo",
          "sv": "Sovinic", "dn": "Discover"}
BUCKETS = [(0.5, "≤0,5%"), (2, "0,5–2%"), (5, "2–5%"), (10, "5–10%"),
           (20, "10–20%"), (1e9, ">20%")]


def leer_snapshot(fecha):
    ruta = rutas.SNAPSHOTS / f"{fecha}.json"
    if not ruta.exists():
        raise SystemExit(f"falta el snapshot {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def ids_crudos(ruta, fuente):
    """Ids de portal presentes en un CSV crudo (misma clave que usa el consolidado)."""
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    import generar_datos as gd  # filtro compartido de alquileres
    ids = set()
    for r in filas:
        if (r.get("operacion") or "").strip().lower() in ("renta", "alquiler"):
            continue
        if gd.es_alquiler(r.get("titulo"), r.get("slug"), r.get("slug_es")):
            continue
        valor = ""
        for col in COL_ID.get(fuente, ()):
            if (r.get(col) or "").strip():
                valor = r[col].strip()
                break
        if valor:
            ids.add(valor)
    return ids


def ids_crudos_por_fuente(directorio):
    if directorio is None or not Path(directorio).exists():
        return {}
    base = Path(directorio)
    return {f: ids_crudos(base / nombre, f) for f, nombre in CSV_FUENTE.items()}


def pct(a, b):
    return None if not a else (b - a) / a * 100


def bucket(p):
    for limite, etiqueta in BUCKETS:
        if abs(p) <= limite:
            return etiqueta
    return BUCKETS[-1][1]


def analizar(desde, hasta, raw_antes_dir, raw_ahora_dir):
    a, b = leer_snapshot(desde), leer_snapshot(hasta)
    la, lb = a["l"], b["l"]
    ka, kb = set(la), set(lb)
    nuevos, retirados, comunes = kb - ka, ka - kb, ka & kb

    out = {"desde": desde, "hasta": hasta}
    out["dataset"] = {
        "listados_antes": len(ka), "listados_ahora": len(kb),
        "delta": len(kb) - len(ka), "delta_pct": round(pct(len(ka), len(kb)) or 0, 2),
        "casas_antes": (a.get("stats", {}).get("casas") or {}).get("n"),
        "casas_ahora": (b.get("stats", {}).get("casas") or {}).get("n"),
        "nuevos": len(nuevos), "retirados": len(retirados), "comunes": len(comunes),
        "supervivencia_pct": round(len(comunes) / len(ka) * 100, 2),
        "retirados_pct": round(len(retirados) / len(ka) * 100, 2),
        "nuevos_pct": round(len(nuevos) / len(kb) * 100, 2),
    }

    # --- por portal: crudo (portal) y consolidado (dataset)
    raw_a = ids_crudos_por_fuente(raw_antes_dir)
    raw_b = ids_crudos_por_fuente(raw_ahora_dir)
    portales = {}
    for f in ("kw", "qc", "mb", "sv", "dn"):
        da = {k for k in ka if k.split(":", 1)[0] == f}
        db = {k for k in kb if k.split(":", 1)[0] == f}
        ra, rb = raw_a.get(f), raw_b.get(f)
        item = {
            "nombre": NOMBRE[f],
            "dataset_antes": len(da), "dataset_ahora": len(db),
            "dataset_nuevos": len(db - da), "dataset_retirados": len(da - db),
            "portal_antes": len(ra) if ra is not None else None,
            "portal_ahora": len(rb) if rb is not None else None,
        }
        if ra is not None and rb is not None:
            item["portal_siguen"] = len(ra & rb)
            item["portal_salieron"] = len(ra - rb)
            item["portal_entraron"] = len(rb - ra)
            item["portal_salieron_pct"] = round(len(ra - rb) / len(ra) * 100, 1) if ra else None
            # de los que salieron del dataset, cuántos seguían publicados en el portal
            item["retirados_que_siguen_en_portal"] = sum(
                1 for k in (da - db) if k.split(":", 1)[1] in rb)
        portales[f] = item
    out["portales"] = portales

    # --- precios de los avisos que siguen publicados
    comunes_p = [k for k in comunes if la[k].get("p") and lb[k].get("p")]
    cambios = [(k, la[k]["p"], lb[k]["p"], pct(la[k]["p"], lb[k]["p"])) for k in comunes_p]
    cambios = [c for c in cambios if c[3] is not None]
    subieron = [c for c in cambios if c[3] > 0.5]
    bajaron = [c for c in cambios if c[3] < -0.5]
    iguales = len(cambios) - len(subieron) - len(bajaron)
    camb_pct = sorted(round(c[3], 2) for c in cambios if abs(c[3]) > 0.5)
    dist = {}
    for p in camb_pct:
        dist[bucket(p)] = dist.get(bucket(p), 0) + 1
    atipicos = [c for c in cambios if abs(c[3]) > 100]
    normales = [c for c in cambios if abs(c[3]) <= 100]
    camb_norm = sorted(round(c[3], 2) for c in normales if abs(c[3]) > 0.5)
    out["precio"] = {
        "comparables": len(cambios),
        "cambiaron": len(camb_pct),
        "pct_cambiaron": round(len(camb_pct) / len(cambios) * 100, 2) if cambios else None,
        "subieron": len(subieron), "bajaron": len(bajaron),
        "pct_bajaron_de_cambios": round(len(bajaron) / len(camb_pct) * 100, 1) if camb_pct else None,
        "mediana_pct_cambios": round(statistics.median(camb_pct), 2) if camb_pct else None,
        "media_pct_cambios": round(statistics.mean(camP := camb_pct), 2) if camb_pct else None,
        "media_pct_cambios_sin_atipicos": round(statistics.mean(camb_norm), 2) if camb_norm else None,
        "atipicos": [{"id": c[0], "antes": c[1], "despues": c[2], "pct": round(c[3], 1)}
                     for c in atipicos],
        "p25_pct_cambios": round(camb_pct[len(camb_pct) // 4], 2) if camb_pct else None,
        "p75_pct_cambios": round(camb_pct[3 * len(camb_pct) // 4], 2) if camb_pct else None,
        "buckets": dist,
        "mayor_bajada": min(cambios, key=lambda c: c[3])[:4] if cambios else None,
        "mayor_subida": max(cambios, key=lambda c: c[3])[:4] if cambios else None,
        "por_fuente": {
            f: {"cambiaron": len([c for c in cambios if c[0].startswith(f + ":") and abs(c[3]) > 0.5]),
                 "subieron": len([c for c in subieron if c[0].startswith(f + ":")]),
                 "bajaron": len([c for c in bajaron if c[0].startswith(f + ":")])}
            for f in ("kw", "qc", "mb", "sv", "dn")
        },
    }

    # --- por zona (mismos sitios)
    zonas = {}

    def zona_de(nombre):
        return zonas.setdefault(nombre, {"zona": nombre, "antes": 0, "ahora": 0,
                                         "nuevos": 0, "retirados": 0,
                                         "_pa": [], "_pb": [], "_pct": []})

    for k, v in la.items():
        d = zona_de(v.get("z") or "(sin zona)")
        d["antes"] += 1
        if v.get("p"):
            d["_pa"].append(v["p"])
    for k, v in lb.items():
        d = zona_de(v.get("z") or "(sin zona)")
        d["ahora"] += 1
        if v.get("p"):
            d["_pb"].append(v["p"])
    for k in nuevos:
        zona_de(lb[k].get("z") or "(sin zona)")["nuevos"] += 1
    for k in retirados:
        zona_de(la[k].get("z") or "(sin zona)")["retirados"] += 1
    for k in comunes:
        pa_v, pb_v = la[k].get("p"), lb[k].get("p")
        if pa_v and pb_v:
            pc = pct(pa_v, pb_v)
            if pc is not None and abs(pc) > 0.5:      # solo avisos repreciados
                zona_de(lb[k].get("z") or "(sin zona)")["_pct"].append(pc)

    for d in zonas.values():
        pa_v, pb_v, ps = d.pop("_pa"), d.pop("_pb"), d.pop("_pct")
        d["delta"] = d["ahora"] - d["antes"]
        d["n_repreciados"] = len(ps)
        d["repreciados_pct"] = round(statistics.median(ps), 2) if len(ps) >= 3 else None
        # mediana de precio de la zona (todas sus propiedades), comparable entre fechas
        if len(pa_v) >= 8 and len(pb_v) >= 8:
            d["mediana_antes"] = round(statistics.median(pa_v))
            d["mediana_ahora"] = round(statistics.median(pb_v))
            d["mediana_pct"] = round(pct(d["mediana_antes"], d["mediana_ahora"]), 2)
        else:
            d["mediana_antes"] = d["mediana_ahora"] = d["mediana_pct"] = None
    out["zonas"] = {
        "total_zonas": len(zonas),
        "subieron_listados": sorted([d for d in zonas.values() if d["delta"] > 0],
                                    key=lambda d: -d["delta"])[:10],
        "bajaron_listados": sorted([d for d in zonas.values() if d["delta"] < 0],
                                   key=lambda d: d["delta"])[:10],
        "precio_bajo": sorted([d for d in zonas.values() if d["mediana_pct"] is not None],
                              key=lambda d: d["mediana_pct"])[:8],
        "precio_alto": sorted([d for d in zonas.values() if d["mediana_pct"] is not None],
                              key=lambda d: -d["mediana_pct"])[:8],
    }

    # --- inmobiliarias más activas: retirados por portal ya arriba; aquí solo el neto
    return out


def comision(d, e):
    return len([k for k in d if k.split(":", 1)[1] not in e])


def resumen_markdown(r):
    ds, pr, po = r["dataset"], r["precio"], r["portales"]
    L = [f"# Cambios entre extracciones: {r['desde']} → {r['hasta']}", ""]
    L += ["## Dataset consolidado", "",
          "| Métrica | Antes | Ahora | Δ |", "|---|---|---|---|",
          f"| Listados | {ds['listados_antes']:,} | {ds['listados_ahora']:,} | "
          f"{ds['delta']:+,} ({ds['delta_pct']:+.1f}%) |",
          f"| Casas | {ds['casas_antes']:,} | {ds['casas_ahora']:,} | "
          f"{(ds['casas_ahora'] or 0) - (ds['casas_antes'] or 0):+,} |",
          "",
          f"- **{ds['retirados']:,} anuncios desaparecieron** ({ds['retirados_pct']:.1f}% de la "
          f"extracción anterior).",
          f"- **{ds['nuevos']:,} anuncios nuevos** ({ds['nuevos_pct']:.1f}% del total actual).",
          f"- {ds['comunes']:,} siguen publicados ({ds['supervivencia_pct']:.1f}% de supervivencia).",
          ""]
    L += ["## Por portal", "",
          "| Portal | Dataset antes | Dataset ahora | Nuevos | Retirados | Avisos que salieron del portal | Avisos en el portal ahora |",
          "|---|---|---|---|---|---|---|"]
    for f, x in po.items():
        L.append(f"| {x['nombre']} | {x['dataset_antes']} | {x['dataset_ahora']} | "
                 f"+{x['dataset_nuevos']} | −{x['dataset_retirados']} | "
                 f"{x.get('portal_salieron', '—')} ({x.get('portal_salieron_pct', '—')}%) | "
                 f"{x.get('portal_ahora', '—')} |")
    L += ["", "## Precio (avisos que siguen publicados)", "",
          f"- Comparables: {pr['comparables']:,} anuncios con precio en ambas extracciones.",
          f"- Cambiaron de precio: **{pr['cambiaron']:,}** ({pr['pct_cambiaron']}%).",
          f"- De esos: **{pr['bajaron']} bajaron** ({pr['pct_bajaron_de_cambios']}%) y "
          f"**{pr['subieron']} subieron**.",
          f"- Mediana del cambio: **{pr['mediana_pct_cambios']}%** "
          f"(p25 {pr['p25_pct_cambios']}%, p75 {pr['p75_pct_cambios']}%).",
          "",
          "| Magnitud del cambio | Avisos |", "|---|---|"]
    for etiqueta in [b[1] for b in BUCKETS]:
        if etiqueta in pr["buckets"]:
            L.append(f"| {etiqueta} | {pr['buckets'][etiqueta]} |")
    L += ["", "| Portal | Cambiaron | Subieron | Bajaron |", "|---|---|---|---|"]
    for f, x in pr["por_fuente"].items():
        L.append(f"| {NOMBRE[f]} | {x['cambiaron']} | {x['subieron']} | {x['bajaron']} |")
    if pr.get("atipicos"):
        L += ["", "Atípicos excluidos de la media (error de carga en el portal o cambio de "
              "tipología): " + ", ".join(f"{a['id']} {a['antes']:,.0f}→{a['despues']:,.0f} "
                                         f"({a['pct']:+.0f}%)" for a in pr["atipicos"][:5]), ""]
    L += ["", "## Mismos sitios (barrios)", "",
          f"{r['zonas']['total_zonas']} zonas con actividad en alguna de las dos extracciones.", "",
          "### Zonas que ganaron más listados", "",
          "| Zona | Antes | Ahora | Δ | Nuevos | Retirados |", "|---|---|---|---|---|---|"]
    for z in r["zonas"]["subieron_listados"]:
        L.append(f"| {z['zona']} | {z['antes']} | {z['ahora']} | +{z['delta']} | "
                 f"+{z['nuevos']} | −{z['retirados']} |")
    L += ["", "### Zonas que perdieron más listados", "",
          "| Zona | Antes | Ahora | Δ | Nuevos | Retirados |", "|---|---|---|---|---|---|"]
    for z in r["zonas"]["bajaron_listados"]:
        L.append(f"| {z['zona']} | {z['antes']} | {z['ahora']} | {z['delta']} | "
                 f"+{z['nuevos']} | −{z['retirados']} |")
    for titulo, clave in (("Precio: zonas que más bajaron", "precio_bajo"),
                          ("Precio: zonas que más subieron", "precio_alto")):
        L += ["", f"### {titulo} (≥8 avisos con precio en ambas fechas)", "",
              "| Zona | Mediana de la zona | Avisos con precio | Listados ahora |",
          "|---|---|---|---|"]
        for z in r["zonas"][clave]:
            L.append(f"| {z['zona']} | {z['mediana_antes']:,.0f} → {z['mediana_ahora']:,.0f} "
                     f"({z['mediana_pct']:+.2f}%) | {z['n_repreciados']} | {z['ahora']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", help="fecha del snapshot inicial (YYYY-MM-DD)")
    ap.add_argument("--hasta", help="fecha del snapshot final")
    ap.add_argument("--raw-antes", help="directorio con los CSV crudos anteriores")
    ap.add_argument("--raw-ahora", default=str(rutas.DATOS), help="directorio de los CSV crudos actuales")
    ap.add_argument("--md", help="escribir el informe markdown en esta ruta")
    ap.add_argument("--json", help="escribir los datos crudos del análisis en esta ruta")
    args = ap.parse_args()

    snaps = sorted(p.stem for p in rutas.SNAPSHOTS.glob("*.json"))
    desde = args.desde or (snaps[-2] if len(snaps) >= 2 else None)
    hasta = args.hasta or (snaps[-1] if snaps else None)
    if not desde or not hasta:
        raise SystemExit("se necesitan dos snapshots (history/snapshots/)")

    raw_antes = args.raw_antes
    if not raw_antes:
        backups = sorted(rutas.DATOS.glob("_backup_*"))
        raw_antes = str(backups[-1]) if backups else None

    r = analizar(desde, hasta, raw_antes, args.raw_ahora)
    r["fuentes_crudas"] = {"antes": raw_antes, "ahora": args.raw_ahora}

    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"json → {args.json}")
    if args.md:
        Path(args.md).write_text(resumen_markdown(r), encoding="utf-8")
        print(f"markdown → {args.md}")

    ds, pr = r["dataset"], r["precio"]
    print(f"\n{desde} → {hasta}")
    print(f"  listados {ds['listados_antes']} → {ds['listados_ahora']} ({ds['delta']:+d}, {ds['delta_pct']:+.1f}%)")
    print(f"  nuevos {ds['nuevos']} · retirados {ds['retirados']} · permanecen {ds['comunes']} "
          f"(supervivencia {ds['supervivencia_pct']}%)")
    print(f"  precio: {pr['cambiaron']}/{pr['comparables']} cambiaron ({pr['pct_cambiaron']}%) — "
          f"{pr['subieron']} arriba / {pr['bajaron']} abajo, mediana {pr['mediana_pct_cambios']}%")
    for f, x in r["portales"].items():
        print(f"  {f:>3}: dataset {x['dataset_antes']}→{x['dataset_ahora']} "
              f"(+{x['dataset_nuevos']}/−{x['dataset_retirados']}) | portal "
              f"{x.get('portal_antes')}→{x.get('portal_ahora')} "
              f"(salieron {x.get('portal_salieron')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
