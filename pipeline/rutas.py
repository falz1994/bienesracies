"""Rutas únicas del proyecto (una sola fuente de verdad).

Contrato:
- ``pipeline/datos/``  → datos de trabajo: CSVs crudos, caches de geocodificación,
  intermedios (``kw_listados.json``), slides recién renderizados. NO se versiona.
- ``docs/data/``       → datos publicados: JSON del sitio, CSVs de descarga y geojson.
  SÍ se versiona (es lo que sirve Vercel).
- ``docs/slides/``     → PNG publicados.
- ``history/``         → snapshots y diffs versionados para análisis de cambios.

Los extractores y geocodificadores escriben y leen en ``DATOS``; solo
``generar_datos.py`` publica en ``PUB``.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "pipeline"
DATOS = PIPELINE / "datos"
DOCS = REPO / "docs"
PUB = DOCS / "data"
SLIDES_PUB = DOCS / "slides"
SLIDES_OUT = DATOS / "slides"
HISTORY = REPO / "history"
SNAPSHOTS = HISTORY / "snapshots"
DIFFS = HISTORY / "diffs"

CSVS = (
    "kw_listados_venta.csv",
    "quierocasa_venta.csv",
    "momotombo_venta.csv",
    "sovinic_venta.csv",
    "discovernica_venta.csv",
)
GEOJSONS = ("distritos_managua.geojson", "barrios_managua.geojson")


def dato(nombre, crear=False):
    """Ruta de un archivo de trabajo en pipeline/datos/."""
    if crear:
        DATOS.mkdir(parents=True, exist_ok=True)
    return DATOS / nombre


def publicado(nombre):
    """Ruta de un archivo publicado en docs/data/."""
    return PUB / nombre


def entrar_datos():
    """Coloca el cwd en pipeline/datos/ (los scripts de extracción usan
    nombres de archivo relativos, así que deben ejecutarse desde ahí)."""
    DATOS.mkdir(parents=True, exist_ok=True)
    os.chdir(DATOS)
