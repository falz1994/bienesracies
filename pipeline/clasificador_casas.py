"""Clasificador conservador de casas habitacionales, compartido por el pipeline
(generar_slides.py) y el generador de datos del sitio (repo bienesracies).

- KW: tipos claros auto-clasificados + puntaje de keywords sobre descripción/dirección
      (misma lógica validada de clasificar_casas.py).
- QuieroCasa: solo tipo == "Casa" del portal.
- Momotombo: tipo == "Casa"; con tipo vacío, keywords sobre el título.
- Sovinic: "casa" como sujeto del título/slug (negativos antes de 'casa' descalifican:
  "terreno con casa" no es casa; "casa con terreno amplio" sí lo es).
"""
import re

KW_AUTO_CASA = {"SINGLE FAMILY DETACHED", "SINGLE FAMILY ATTACHED", "TOWNHOUSE", "DUPLEX"}
KW_AUTO_NO = {"APARTMENT", "OFFICE", "RETAIL", "WAREHOUSE", "INDUSTRIAL", "HOTEL MOTEL",
              "HOTEL-MOTEL", "OWN YOUR OWN", "STOCK COOPERATIVE", "DEEDED PARKING", "CABIN"}
KW_POS_FUERTE = [r"\bcasas?\b", r"\bvivienda\b", r"\bresidencia\s", r"🏡", r"\bplanta alta\b",
                 r"\bdos plantas\b", r"\bun nivel\b", r"\bdos niveles\b"]
KW_POS_HAB = [r"\b\d+\s*(habitaciones|dormitorios|recamaras|recámaras)\b", r"\bhabitaciones\b",
              r"\bdormitorios\b", r"\bclosets?\b", r"\bsala[- ]comedor\b"]
KW_NEG = [r"\bterrenos?\b", r"\blotes?\b", r"\bvara[s]?\b", r"\bv²\b", r"\bfinca\b", r"\bbodega",
          r"\blocal comercial\b", r"\bapartamentos?\b", r"\bproyecto\b", r"para construir",
          r"\bedificios?\b"]

NEG_TEXTO_RE = re.compile(
    r"\bterrenos?\b|\blotes?\b|\bvara[s]?\b|\bfinca\b|\bbodega|\blocal comercial\b|"
    r"\bedificios?\b|\bproyecto\b|para construir|\boficinas?\b", re.I)
CASA_TEXTO_RE = re.compile(r"\bcasas?\b", re.I)


def casa_por_texto(*textos):
    """Casa si menciona 'casa' como sujeto del anuncio (las palabras no habitacionales
    solo descalifican cuando aparecen ANTES de 'casa')."""
    t = " ".join(x or "" for x in textos)
    m = CASA_TEXTO_RE.search(t)
    if not m:
        return False
    return not NEG_TEXTO_RE.search(t[:m.start()])


def kw_es_casa(r):
    t = (r.get("tipo_propiedad") or "").upper()
    if t in KW_AUTO_CASA:
        return True
    if t in KW_AUTO_NO:
        return False
    texto = f"{r.get('descripcion') or ''} {r.get('direccion') or ''}".lower()
    pos = sum(len(re.findall(p, texto)) for p in KW_POS_FUERTE) + 0.5 * sum(
        len(re.findall(p, texto)) for p in KW_POS_HAB)
    neg = sum(len(re.findall(p, texto)) for p in KW_NEG)
    if re.search(r"\bconstrucc[ií]on\b", texto) and re.search(r"\bcasas?\b", texto):
        pos += 1
    return pos >= 2 and pos > neg


def qc_es_casa(r):
    return (r.get("tipo") or "").strip().lower() == "casa"


def mb_es_casa(r):
    t = (r.get("tipo") or "").strip().lower()
    if t == "casa":
        return True
    return not t and casa_por_texto(r.get("titulo"))


def sv_es_casa(r):
    return casa_por_texto(r.get("titulo"), r.get("slug"))


def dn_es_casa(r):
    # discovernica: el extractor ya filtra por categorías de casa; doble check
    return int(r.get("categoria") or 0) in {2, 46, 32, 52}
