#!/usr/bin/env bash
# Refresco de datos de Bienes Raíces Managua.
#
#   ./run.sh              refresco completo (extraer → geocodificar → publicar → histórico → validar)
#   ./run.sh --extract    solo extracción (con guarda de regresión por fuente)
#   ./run.sh --datos      solo consolidación + histórico + validación
#   ./run.sh --slides     solo slides (requiere Playwright/Chromium o CHROME_PATH)
#   ./run.sh --validar    solo validación de lo publicado
#   ./run.sh --sin-backup refresco sin apartar los CSV de trabajo anteriores
#
# Los extractores y geocodificadores escriben en pipeline/datos/ (no versionado).
# Solo pipeline/generar_datos.py publica en docs/ (lo que sirve Vercel).
set -euo pipefail
cd "$(dirname "$0")"

FECHA=$(date +%F)
BACKUP="pipeline/datos/_backup_$FECHA"
CSVS=(kw_listados_venta.csv quierocasa_venta.csv momotombo_venta.csv sovinic_venta.csv discovernica_venta.csv)
MODO="${1:---todo}"
BACKUP_ON="si"
[[ "${2:-}${1:-}" == *"--sin-backup"* ]] && BACKUP_ON="no"
[[ "$MODO" == "--sin-backup" ]] && MODO="--todo" && BACKUP_ON="no"

log() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
aviso() { printf '\033[33m  ! %s\033[0m\n' "$*"; }

contar_csv() { # filas de datos (sin cabecera) de un CSV en pipeline/datos
  local f="pipeline/datos/$1"
  [[ -f "$f" ]] && echo $(( $(wc -l < "$f") - 1 )) || echo 0
}

backup_y_limpiar() {
  log "Backup de CSVs de trabajo → $BACKUP"
  mkdir -p "$BACKUP"
  for f in "${CSVS[@]}"; do
    [[ -f "pipeline/datos/$f" ]] && cp -a "pipeline/datos/$f" "$BACKUP/$f"
  done
  for f in pipeline/datos/geocache_*.json; do
    [[ -f "$f" ]] && cp -a "$f" "$BACKUP/"
  done
  # Los CSV son checkpoint de reanudación: en refresco completo se apartan para
  # que las propiedades retiradas del portal desaparezcan del consolidado.
  for f in quierocasa_venta.csv momotombo_venta.csv sovinic_venta.csv; do
    rm -f "pipeline/datos/$f"
  done
  echo "  $(ls -1 "$BACKUP" | wc -l) archivos respaldados"
}

podar_caches() {
  log "Purga de entradas nulas en caches de geocodificación"
  python3 - <<'PY'
import json, pathlib
for p in sorted(pathlib.Path("pipeline/datos").glob("geocache_*.json")):
    if p.name.startswith("geocache_barrios"):
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    nulos = [k for k, v in d.items() if v is None]
    if nulos:
        for k in nulos:
            del d[k]
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    print(f"  {p.name}: -{len(nulos)} nulos, quedan {len(d)}")
PY
}

extraer() {
  log "Extracción (5 fuentes)"
  for paso in "extraer_kw.py kw_listados_venta.csv" \
              "extraer_quierocasa.py quierocasa_venta.csv" \
              "extraer_momotomborealestate.py momotombo_venta.csv" \
              "extraer_sovinic.py sovinic_venta.csv" \
              "extraer_discovernica.py discovernica_venta.csv"; do
    set -- $paso
    local script="$1" csv="$2" antes ahora
    antes=$(contar_csv "$csv")
    echo "  · $script (antes: $antes filas)"
    if ! python3 "pipeline/$script"; then
      aviso "$script falló; se conserva el CSV anterior"
      [[ -f "$BACKUP/$csv" ]] && cp -a "$BACKUP/$csv" "pipeline/datos/$csv"
      continue
    fi
    ahora=$(contar_csv "$csv")
    echo "    → $ahora filas"
    if [[ "$antes" -gt 0 && "$ahora" -lt $(( antes * 7 / 10 )) ]]; then
      aviso "regresión en $csv ($antes → $ahora, <70%): se restaura el backup"
      [[ -f "$BACKUP/$csv" ]] && cp -a "$BACKUP/$csv" "pipeline/datos/$csv"
    fi
  done
  python3 pipeline/clasificar_casas.py || aviso "clasificar_casas.py falló"
}

geocodificar() {
  log "Geocodificación (4 fuentes)"
  for s in geocodificar_quierocasa.py geocodificar_momotomborealestate.py \
           geocodificar_sovinic.py geocodificar_discovernica.py; do
    echo "  · $s"
    python3 "pipeline/$s" || aviso "$s falló"
  done
}

datos() {
  log "Consolidación → docs/data"
  python3 pipeline/generar_datos.py
}

historico() {
  log "Histórico (snapshot + diff + serie)"
  python3 pipeline/historial.py --snapshot
  python3 pipeline/historial.py --diff || true
  python3 pipeline/historial.py --serie
}

slides() {
  log "Slides (9 PNG 1080×1920)"
  local env_extra=()
  if ! python3 -c "import playwright" 2>/dev/null; then
    aviso "Playwright no instalado: se omite la regeneración de slides"; return 0
  fi
  local browsers="pipeline/datos/.playwright"
  if [[ ! -d "$browsers" && ! -d "$HOME/.cache/ms-playwright" ]]; then
    echo "  instalando Chromium de Playwright en $browsers …"
    if ! PLAYWRIGHT_BROWSERS_PATH="$PWD/$browsers" python3 -m playwright install chromium; then
      aviso "no se pudo instalar Chromium"
    fi
  fi
  [[ -d "$browsers" ]] && env_extra+=("PLAYWRIGHT_BROWSERS_PATH=$PWD/$browsers")
  if [[ ${#env_extra[@]} -eq 0 && ! -d "$HOME/.cache/ms-playwright" && -x /usr/bin/google-chrome ]]; then
    env_extra+=("CHROME_PATH=/usr/bin/google-chrome")
  fi
  env "${env_extra[@]}" python3 pipeline/generar_slides.py || aviso "generación de slides falló"
  datos   # recopia slides + CSV a docs/
}

validar() { log "Validación de datos publicados"; python3 pipeline/validar_datos.py; }

case "$MODO" in
  --todo)    [[ "$BACKUP_ON" == "si" ]] && backup_y_limpiar; podar_caches; extraer; geocodificar
             datos; historico; slides; validar ;;
  --extract) [[ "$BACKUP_ON" == "si" ]] && backup_y_limpiar; podar_caches; extraer; geocodificar ;;
  --datos)   datos; historico; validar ;;
  --slides)  slides ;;
  --validar) validar ;;
  *) echo "uso: ./run.sh [--todo|--extract|--datos|--slides|--validar] [--sin-backup]"; exit 2 ;;
esac

log "Listo"
