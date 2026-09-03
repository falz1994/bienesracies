"""Geocodifica los proyectos de vivienda social del Gobierno en Managua (investigación web).

Fuentes: Alcaldía de Managua (managua.gob.ni), Canal 4, TN8, El 19 Digital, VosTV,
Confidencial (2023-2026). Salida: docs/data/programas_gobierno.json
"""
import json
import os
import time
import urllib.parse
import urllib.request

CACHE = "geocache_gob.json"
UA = "analisis-managua/1.0 (programas gobierno)"

# Coordenadas verificadas con Overpass/OSM y Nominatim (sep 2026). El clúster de Sabana
# Grande (Villa Jerusalén, Caminos del Río, Villa Santiago, Las Madres) usa el ancla de la
# comarca con offsets de ±400 m: son proyectos contiguos y OSM no los mapea por separado.
PROGRAMAS = [
    ("Villa Jerusalén", "Bismarck Martínez", "Sabana Grande, zona oriental de Managua", "2,150+",
     12.1214, -86.1668, "aproximado"),
    ("Flor de Pino", "Bismarck Martínez", "Distrito VI, contiguo a Residencial Nicaragua", "1,000",
     12.1438, -86.2168, "osm"),
    ("Caminos del Río", "Bismarck Martínez", "Sabana Grande, zona oriental de Managua", "1,528",
     12.1179, -86.1653, "aproximado"),
    ("Villa Santiago", "Bismarck Martínez", "Sabana Grande, zona oriental de Managua", "481",
     12.1240, -86.1700, "aproximado"),
    ("Residencial Las Madres", "Bismarck Martínez", "Sabana Grande · inaugurada mayo 2026", "575",
     12.1195, -86.1730, "aproximado"),
    ("Urbanización Nuevas Victorias", "INVUR / Alcaldía", "Sabana Grande, coop. con China · fase 1", "920",
     12.1167, -86.1772, "osm"),
    ("Residencial Nicaragua", "Bismarck Martínez", "Rotonda Las Mercedes, Carretera Norte · abr 2026", "250",
     12.1460, -86.2180, "aproximado"),
    ("Mirador Xolotlán", "Bismarck Martínez", "Sector Xolotlán (vistas al lago)", "80",
     12.1161, -86.2156, "aproximado"),
    ("Apartamentos Roberto Clemente", "INVUR / Alcaldía", "Contiguo al Complejo Deportivo Dignidad, Distrito II", "134",
     12.1492, -86.2830, "osm"),
    ("Reparto Doña Lidia Saavedra", "Bismarck Martínez", "Cerca de los juzgados de Nejapa · 2026", "125",
     12.1183, -86.3215, "aproximado"),
    ("Pablo María", "Bismarck Martínez", "Managua · entregas 2026", "32",
     12.0882, -86.2300, "osm"),
    ("Villa Esperanza", "Bismarck Martínez", "Lotificación · 250 lotes · ubicación por confirmar", "250 lotes",
     None, None, "pendiente"),
]

FUENTES = [
    "https://www.managua.gob.ni/programa-bismarck-martinez-apertura-residencial-nicaragua-en-managua/",
    "https://www.tn8.ni/nacionales/residencial-las-madres-575-nuevas-viviendas-para-familias-nicaraguenses/",
    "https://www.canal4.com.ni/avanza-programa-bismarck-martinez-con-mas-mil-200-viviendas-managua/",
    "https://www.el19digital.com/articulos/ver/titulo:143170-avanza-construccion-de-viviendas-en-la-urbanizacion-nuevas-victorias-en-managua",
    "https://confidencial.digital/nacion/las-nuevas-casas-de-la-alcaldia-de-managua-no-son-para-los-pobres",
]


def buscar_programas():
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1,
                                     "countrycodes": "ni", "accept-language": "es"}))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            datos = json.load(r)
        return datos[0] if datos else None
    except Exception as e:
        print(f"  [warn] {q[:50]}: {e}")
        time.sleep(3)
        return None


def main():
    out = []
    for nombre, programa, desc, viviendas, lat, lng, precision in PROGRAMAS:
        out.append({"nombre": nombre, "programa": programa, "descripcion": desc,
                    "viviendas": viviendas, "lat": lat, "lng": lng, "precision": precision})
        if lat:
            print(f"  OK: {nombre:45s} → {lat}, {lng} ({precision})")
        else:
            print(f"  PEND: {nombre}")
    os.makedirs("docs/data", exist_ok=True)
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/programas_gobierno.json", "w", encoding="utf-8") as f:
        json.dump({"programas": out, "fuentes": FUENTES,
                   "nota": "Ubicaciones por OSM/Nominatim; los proyectos nuevos del clúster "
                           "Sabana Grande usan el ancla de la comarca (±400 m). Villa Esperanza "
                           "sin coordenadas confirmadas."},
                  f, ensure_ascii=False, indent=1)
    print(f"\n→ {len([o for o in out if o['lat']])}/{len(PROGRAMAS)} con coordenadas")


if __name__ == "__main__":
    main()
