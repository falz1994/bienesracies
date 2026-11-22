"""Cruce entre fuentes: detecta la misma propiedad publicada en varios portales.

El pipeline ya deduplica (±110 m + precio en el mismo millar) y **descarta** la copia.
Esto hace lo contrario: conserva los pares, mide la diferencia de precio entre portales
y deja la evidencia para auditarla.

Cómo empareja (todas las señales disponibles, no una sola):
  1. precio: el más caro no supera al más barato en más de 8 %;
  2. tamaño: m² construidos (±2 %) y/o lote en m² (±2 %, convirtiendo varas² de Discover);
  3. programa: habitaciones y baños iguales (cuando ambos los publican);
  4. ubicación: misma zona normalizada o ≤ 300 m (las fuentes geocodificadas comparten el
     centroide del barrio, así que la distancia sola no basta);
  5. texto: tokens distintivos del título/dirección/descripción (calles, condominios, números).
Cada propiedad se empareja como máximo con una de cada otro portal (asignación uno a uno
por par de fuentes, de mayor a menor puntaje), lo que evita los falsos positivos típicos
de barrios con casas parecidas.

Uso:
  python3 pipeline/cruzar_fuentes.py                       # todas las fuentes
  python3 pipeline/cruzar_fuentes.py --json history/cruces.json --md history/cruces.md
  python3 pipeline/cruzar_fuentes.py --min-confianza media # solo alta/media
"""
import argparse
import csv
import difflib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rutas  # noqa: E402
import generar_datos as gd  # noqa: E402

FUENTES = ("kw", "qc", "mb", "sv", "dn")
NOMBRE = {"kw": "KW Nicaragua", "qc": "QuieroCasa", "mb": "Momotombo",
          "sv": "Sovinic", "dn": "Discover"}
CSV = {"kw": "kw_listados_venta.csv", "qc": "quierocasa_venta.csv",
       "mb": "momotombo_venta.csv", "sv": "sovinic_venta.csv",
       "dn": "discovernica_venta.csv"}
VARA2_M2 = 0.698896  # 1 vara² ≈ 0,6989 m²

STOP = set("""casa casas en venta de del la las el los y con sin para por un una se vende venta
residencial residencia propiedad hermosa espectacular excelente oportunidad exclusiva exclusivo
inmueble bienes raices nicaragua managua area m2 metros construccion terreno lote cuarto cuartos
habitacion habitaciones bano banos parqueo parqueos garaje piscina jardin patio """.
              split())


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s or "")
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def tokens(s):
    return {t for t in re.findall(r"[a-z0-9.]+", norm(s))
            if (len(t) >= 4 or t.isdigit()) and t not in STOP}


RE_TIPO = [
    ("terreno", re.compile(r"\b(terreno|lote|lotificaci[oó]n|parcela|finca|quinta)\b", re.I)),
    ("comercial", re.compile(r"\b(oficina|local|bodega|nave|galera|comercial)\b", re.I)),
    ("apartamento", re.compile(r"\b(apartamento|apto|penthouse|studio)\b", re.I)),
    ("casa", re.compile(r"\b(casa|residencia|villa|townhouse|quinta)\b", re.I)),
]


def tipo_inmueble(*textos):
    """Clasifica el tipo de inmueble a partir de los textos del aviso."""
    t = " ".join(x for x in textos if x)
    for etiqueta, rx in RE_TIPO:
        if rx.search(t):
            return etiqueta
    return ""


def texto_sim(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    seq = difflib.SequenceMatcher(None, norm(a)[:400], norm(b)[:400]).ratio()
    # el Jaccard de tokens es la señal; difflib solo corrobora textos largos
    if jac >= 0.25 or (jac >= 0.15 and seq >= 0.55 and len(norm(a)) > 60):
        return round(max(jac, seq), 3)
    return 0.0


def dist_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def razon(a, b):
    """1.0 = idénticos; cuánto se aparta el mayor del menor."""
    if not a or not b:
        return None
    return max(a, b) / min(a, b)


# ---------------------------------------------------------------- carga
def cargar_textos():
    """Título / dirección / descripción por (fuente, id)."""
    idx = {}
    for f, nombre in CSV.items():
        ruta = rutas.DATOS / nombre
        if not ruta.exists():
            continue
        for r in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            if (r.get("operacion") or "").strip().lower() in ("renta", "alquiler"):
                continue
            if gd.es_alquiler(r.get("titulo"), r.get("slug")):
                continue
            kid = (r.get("id") or r.get("codigo") or "").strip()
            if not kid:
                continue
            idx[(f, kid)] = {
                "titulo": r.get("titulo") or "",
                "direccion": r.get("direccion") or r.get("calle") or "",
                "descripcion": (r.get("descripcion") or "")[:600],
                "url": r.get("url") or "",
            }
    return idx


def cargar_listados(textos):
    """Listados filtrados como los publica el sitio, con texto y tamaños normalizados."""
    rows = []
    for x in (list(gd.kw_rows()) + list(gd.qc_rows()) + list(gd.mb_rows())
              + list(gd.sv_rows()) + list(gd.dn_rows())):
        t = textos.get((x["fuente"], str(x["id"])), {})
        m2 = x.get("m2") if (x.get("m2") or 0) >= 30 else None
        lote = x.get("lote")
        if lote and x["fuente"] == "dn":
            lote = lote * VARA2_M2                       # Discover publica varas²
        if not lote or not (100 <= lote <= 60000):
            lote = None
        rows.append({
            **x, "m2": m2, "lote_m2": lote,
            "texto": " ".join(filter(None, [t.get("titulo"), t.get("direccion"),
                                            t.get("descripcion")])),
            "tipo_norm": tipo_inmueble(t.get("titulo"), x.get("tipo")),
            "titulo": t.get("titulo") or "", "url": t.get("url") or x.get("url") or "",
            "zona_norm": norm(x.get("zona")),
        })
    return rows


# ---------------------------------------------------------------- emparejado
TOL = {"precio": 1.08, "m2": 1.05, "lote": 1.05, "hab": 0, "banos": 0.01}


def evaluar(a, b, tol=None):
    """Devuelve (puntaje, señales) o None si el par no es candidato."""
    tol = {**TOL, **(tol or {})}
    if a["fuente"] == b["fuente"] or not a["p"] or not b["p"]:
        return None
    rp = razon(a["p"], b["p"])
    if rp is None or rp > tol["precio"]:
        return None
    misma_zona = bool(a["zona_norm"]) and a["zona_norm"] == b["zona_norm"]
    d = dist_m(a["lat"], a["lng"], b["lat"], b["lng"])
    if not misma_zona and d > 600:
        return None

    if a.get("tipo_norm") and b.get("tipo_norm") and a["tipo_norm"] != b["tipo_norm"]:
        return None          # casa vs terreno/oficina: no es el mismo inmueble

    señales, peso = [], 0.0
    rm2 = razon(a["m2"], b["m2"])
    if rm2 is not None:
        if rm2 <= 1.02:
            señales.append("m2"); peso += 3
        elif rm2 <= tol["m2"]:
            señales.append("m2~"); peso += 1.5
        else:
            return None                      # tamaños incompatibles: no es la misma
    rl = razon(a["lote_m2"], b["lote_m2"])
    if rl is not None:
        if rl <= 1.02:
            señales.append("lote"); peso += 3
        elif rl <= tol["lote"]:
            señales.append("lote~"); peso += 1.5
        else:
            return None
    if a["hab"] is not None and b["hab"] is not None:
        if abs(float(a["hab"]) - float(b["hab"])) > tol["hab"]:
            return None
        if a["hab"] == b["hab"]:
            señales.append("hab"); peso += 1
        else:
            señales.append("hab±"); peso += 0.4
    if a["banos"] is not None and b["banos"] is not None:
        if abs(float(a["banos"]) - float(b["banos"])) > tol["banos"]:
            return None
        señales.append("baños"); peso += 1

    sim = texto_sim(a["texto"], b["texto"])
    if sim >= 0.35:
        señales.append("texto"); peso += 2
    if rp <= 1.02:
        señales.append("precio="); peso += 2
    elif rp <= 1.05:
        señales.append("precio~"); peso += 1
    if misma_zona:
        peso += 0.5
    if d <= 150:
        peso += 0.5

    # huella mínima: tamaño, lote o (programa + texto) — el precio solo no empareja
    huella = any(s in señales for s in ("m2", "lote", "texto")) or \
        ("hab" in señales and "baños" in señales)
    if not huella:
        return None
    confianza = "alta" if peso >= 6 else "media" if peso >= 4 else "baja"
    return {"score": round(peso, 2), "confianza": confianza, "senales": señales,
            "dist_m": round(d), "razon_precio": round(rp, 4),
            "razon_m2": round(rm2, 4) if rm2 else None,
            "razon_lote": round(rl, 4) if rl else None,
            "sim_texto": sim}


def emparejar(rows, min_confianza="baja", tol=None):
    orden = {"baja": 0, "media": 1, "alta": 2}
    pares = []
    for i, f1 in enumerate(FUENTES):
        for f2 in FUENTES[i + 1:]:
            a_list = [x for x in rows if x["fuente"] == f1]
            b_list = [x for x in rows if x["fuente"] == f2]
            candidatos = []
            for a in a_list:
                for b in b_list:
                    ev = evaluar(a, b, tol)
                    if ev and orden[ev["confianza"]] >= orden[min_confianza]:
                        candidatos.append((ev["score"], a, b, ev))
            candidatos.sort(key=lambda c: -c[0])
            usados_a, usados_b = set(), set()
            for score, a, b, ev in candidatos:
                if id(a) in usados_a or id(b) in usados_b:
                    continue
                usados_a.add(id(a)); usados_b.add(id(b))
                pares.append({"a": a, "b": b, **ev})
    return pares


def agrupar(rows, pares):
    """Une los pares en grupos (misma propiedad en 2+ portales)."""
    padre = {}

    def find(x):
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    def union(x, y):
        padre[find(x)] = find(y)

    por_clave = {(r["fuente"], str(r["id"])): r for r in rows}
    for p in pares:
        union((p["a"]["fuente"], str(p["a"]["id"])), (p["b"]["fuente"], str(p["b"]["id"])))
    grupos = {}
    for clave in list(padre):
        grupos.setdefault(find(clave), []).append(clave)

    salida = []
    for claves in grupos.values():
        avisos = [por_clave[c] for c in claves]
        if len({x["fuente"] for x in avisos}) < 2:
            continue
        precios = [x["p"] for x in avisos if x["p"]]
        if len(precios) < 2:
            continue
        caro = max(avisos, key=lambda x: x["p"])
        barato = min(avisos, key=lambda x: x["p"])
        spread = (caro["p"] - barato["p"]) / barato["p"] * 100
        pares_grupo = [p for p in pares
                       if (p["a"]["fuente"], str(p["a"]["id"])) in claves
                       and (p["b"]["fuente"], str(p["b"]["id"])) in claves]
        conf = min((p["confianza"] for p in pares_grupo),
                   key=lambda c: {"alta": 2, "media": 1, "baja": 0}[c])
        señales = sorted({s for p in pares_grupo for s in p["senales"]})
        salida.append({
            "confianza": conf,
            "señales": señales,
            "zona": barato.get("zona") or "",
            "distrito": barato.get("distrito") or "",
            "precio_min": round(barato["p"]),
            "precio_max": round(caro["p"]),
            "spread_pct": round(spread, 2),
            "mas_barato": barato["fuente"],
            "mas_caro": caro["fuente"],
            "m2": barato["m2"] or caro["m2"],
            "lote_m2": round(barato["lote_m2"] or caro["lote_m2"] or 0) or None,
            "avisos": [{"fuente": x["fuente"], "id": str(x["id"]), "precio": round(x["p"]),
                        "m2": x["m2"], "zona": x.get("zona"), "url": x["url"],
                        "titulo": x["titulo"][:110]} for x in avisos],
        })
    salida.sort(key=lambda g: (-{"alta": 2, "media": 1, "baja": 0}[g["confianza"]],
                               -g["spread_pct"]))
    return salida


# ---------------------------------------------------------------- informe
def resumen(rows, grupos):
    por_conf = {c: sum(1 for g in grupos if g["confianza"] == c) for c in ("alta", "media", "baja")}
    pares = {}
    for g in grupos:
        fuentes = sorted({a["fuente"] for a in g["avisos"]})
        for i, f1 in enumerate(fuentes):
            for f2 in fuentes[i + 1:]:
                pares[f"{f1}-{f2}"] = pares.get(f"{f1}-{f2}", 0) + 1
    spreads = sorted(g["spread_pct"] for g in grupos)
    tramos = {"≤2%": 0, "2-5%": 0, "5-10%": 0, "10-20%": 0, ">20%": 0}
    for s in spreads:
        k = ("≤2%" if s <= 2 else "2-5%" if s <= 5 else "5-10%" if s <= 10
             else "10-20%" if s <= 20 else ">20%")
        tramos[k] += 1
    barato = {}
    caro = {}
    for g in grupos:
        barato[g["mas_barato"]] = barato.get(g["mas_barato"], 0) + 1
        caro[g["mas_caro"]] = caro.get(g["mas_caro"], 0) + 1
    ids = {a["fuente"] + ":" + str(a["id"]) for g in grupos for a in g["avisos"]}
    return {
        "listados_analizados": len(rows),
        "grupos": len(grupos),
        "avisos_en_grupos": len(ids),
        "pct_del_dataset": round(len(ids) / len(rows) * 100, 2) if rows else None,
        "por_confianza": por_conf,
        "por_par_de_fuentes": dict(sorted(pares.items(), key=lambda kv: -kv[1])),
        "spread_mediana_pct": round(spreads[len(spreads) // 2], 2) if spreads else None,
        "spread_media_pct": round(sum(spreads) / len(spreads), 2) if spreads else None,
        "tramos": tramos,
        "veces_mas_barato": dict(sorted(barato.items(), key=lambda kv: -kv[1])),
        "veces_mas_caro": dict(sorted(caro.items(), key=lambda kv: -kv[1])),
        "discrepancias_gt10": sum(1 for s in spreads if s > 10),
    }


def markdown(r, grupos, limite=15):
    L = ["# Propiedades repetidas entre portales y diferencia de precios", "",
         f"- Listados analizados: **{r['listados_analizados']:,}** (ventas, área metropolitana).",
         f"- Grupos de la misma propiedad en ≥2 portales: **{r['grupos']:,}** "
         f"({r['avisos_en_grupos']:,} avisos, {r['pct_del_dataset']}% del dataset).",
         f"- Confianza: {r['por_confianza']['alta']} alta · {r['por_confianza']['media']} media · "
         f"{r['por_confianza']['baja']} baja.",
         f"- Diferencia de precio: mediana **{r['spread_mediana_pct']}%**, "
         f"media {r['spread_media_pct']}% · {r['discrepancias_gt10']} grupos con >10%.",
         "", "## Pares de portales", "", "| Par | Grupos |", "|---|---|"]
    for k, v in r["por_par_de_fuentes"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Diferencia de precio", "", "| Tramo | Grupos |", "|---|---|"]
    for k, v in r["tramos"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Quién publica más barato / más caro", "",
          "| Portal | Más barato | Más caro |", "|---|---|---|"]
    for f in FUENTES:
        if r["veces_mas_barato"].get(f) or r["veces_mas_caro"].get(f):
            L.append(f"| {NOMBRE[f]} | {r['veces_mas_barato'].get(f, 0)} | "
                     f"{r['veces_mas_caro'].get(f, 0)} |")
    L += ["", "## Casos con mayor diferencia (verificar con los enlaces)", ""]
    for g in grupos[:limite]:
        ids = ", ".join(f"{NOMBRE[a['fuente']]} {a['id']} ${a['precio']:,}" for a in g["avisos"])
        L.append(f"- **{g['zona']} · ${g['precio_min']:,}–${g['precio_max']:,} "
                 f"({g['spread_pct']:+.2f}%)** · confianza {g['confianza']} · {ids}")
        for a in g["avisos"]:
            L.append(f"  - {NOMBRE[a['fuente']]}: {a['url']}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-confianza", default="baja", choices=("baja", "media", "alta"))
    ap.add_argument("--json", help="ruta del JSON de salida")
    ap.add_argument("--md", help="ruta del informe markdown")
    ap.add_argument("--ejemplos", type=int, default=8)
    ap.add_argument("--tol-precio", type=float, default=1.08)
    ap.add_argument("--tol-m2", type=float, default=1.05)
    ap.add_argument("--tol-lote", type=float, default=1.05)
    ap.add_argument("--tol-hab", type=int, default=0)
    ap.add_argument("--amplio", action="store_true",
                    help="tolerancias amplias (más recall, más falsos positivos)")
    args = ap.parse_args()

    tol = {"precio": args.tol_precio, "m2": args.tol_m2, "lote": args.tol_lote,
           "hab": args.tol_hab}
    if args.amplio:
        tol.update({"precio": 1.15, "m2": 1.15, "lote": 1.20, "hab": 1})

    textos = cargar_textos()
    rows = cargar_listados(textos)
    pares = emparejar(rows, args.min_confianza, tol)
    grupos = agrupar(rows, pares)
    r = resumen(rows, grupos)
    r["params"] = {"min_confianza": args.min_confianza,
                   "tolerancias": {k: round(v, 3) for k, v in tol.items()}}

    print(f"listados analizados: {r['listados_analizados']}")
    print(f"grupos (misma propiedad en 2+ portales): {r['grupos']} · "
          f"{r['avisos_en_grupos']} avisos ({r['pct_del_dataset']}% del dataset)")
    print(f"confianza: {r['por_confianza']}")
    print(f"spread: mediana {r['spread_mediana_pct']}% · media {r['spread_media_pct']}% · "
          f"{r['discrepancias_gt10']} grupos >10%")
    print(f"tramos: {r['tramos']}")
    print(f"pares: {r['por_par_de_fuentes']}")
    print(f"más barato en: {r['veces_mas_barato']}")
    print(f"más caro en:   {r['veces_mas_caro']}")
    print("\nejemplos:")
    for g in grupos[:args.ejemplos]:
        ids = " | ".join(f"{a['fuente']}:{a['id']} ${a['precio']:,}" for a in g["avisos"])
        print(f"  {g['zona'][:28]:<28} ${g['precio_min']:,}–${g['precio_max']:,} "
              f"({g['spread_pct']:+.1f}%) [{g['confianza']}] {ids}")

    if args.json:
        Path(args.json).write_text(json.dumps({"resumen": r, "grupos": grupos},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\njson → {args.json}")
    if args.md:
        Path(args.md).write_text(markdown(r, grupos), encoding="utf-8")
        print(f"markdown → {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
