"""Verifica el sitio servido por HTTP (datos, capas y sección Histórico).

Uso:
  python3 -m http.server 8931          # desde la raíz del repo
  python3 pipeline/verificar_sitio.py  # en otra terminal

Requiere Playwright con Chrome del sistema (`channel="chrome"`) o Chromium instalado.
Sale con código 1 si falta algún recurso o hay errores de JavaScript.
"""
import argparse
import sys
from urllib.parse import urljoin

CLAVES = ("hero", "fecha", "histKpis", "tb-hist", "tb-caras", "tb-baratas", "tb-gob", "gal-slides")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8931/docs/")
    ap.add_argument("--png", help="directorio donde guardar capturas (opcional)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    errores_js, http_malos = [], []
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        pg = navegador.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errores_js.append(str(e)))
        pg.on("response", lambda r: http_malos.append(f"{r.status} {r.url}")
              if r.status >= 400 and "favicon" not in r.url else None)
        pg.goto(args.url, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(2500)
        estado = pg.evaluate(
            """(claves) => {
                const q = id => document.getElementById(id);
                return {
                  hero: q('heroNums')?.textContent || '',
                  fecha: q('fechaExt')?.textContent || '',
                  histKpis: document.querySelectorAll('#histKpis .c').length,
                  'tb-hist': document.querySelectorAll('#tb-hist tr').length,
                  'tb-caras': document.querySelectorAll('#tb-caras tr').length,
                  'tb-baratas': document.querySelectorAll('#tb-baratas tr').length,
                  'tb-gob': document.querySelectorAll('#tb-gob tr').length,
                  'gal-slides': document.querySelectorAll('#gal-slides img').length,
                  mapa: !!document.querySelector('#mapa .leaflet-map-pane'),
                  capas: document.querySelectorAll('.ctrl-items input[type=checkbox]').length,
                  descargas: document.querySelectorAll('footer .descargas a').length,
                };
            }""", list(CLAVES))
        if args.png:
            import os
            os.makedirs(args.png, exist_ok=True)
            pg.screenshot(path=f"{args.png}/sitio.png")
            pg.evaluate("document.getElementById('historico')?.scrollIntoView()")
            pg.wait_for_timeout(1200)
            pg.screenshot(path=f"{args.png}/historico.png")
        navegador.close()

    faltantes = [k for k in CLAVES if not estado.get(k)]
    print(f"URL: {args.url}")
    for k, v in estado.items():
        print(f"  {k:>12}: {v}")
    if faltantes:
        print(f"ERROR secciones sin contenido: {faltantes}")
    if errores_js:
        print(f"ERROR JavaScript: {errores_js}")
    if http_malos:
        print(f"ERROR recursos HTTP: {http_malos}")
    if not estado.get("mapa"):
        print("ERROR el mapa Leaflet no se inicializó")
    return 1 if (faltantes or errores_js or http_malos or not estado.get("mapa")) else 0


if __name__ == "__main__":
    sys.exit(main())
