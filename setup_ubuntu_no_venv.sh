#!/usr/bin/env bash
# Setup script for Ubuntu (no virtualenv).
# Run from the project root: sudo ./setup_ubuntu_no_venv.sh

set -u

SUDO=""
if [ "$EUID" -ne 0 ]; then
  SUDO='sudo'
fi

REPORT="install_report.txt"
echo "Install report - $(date)" > "$REPORT"

log() {
  echo "$(date +'%Y-%m-%d %H:%M:%S') - $1" | tee -a "$REPORT"
}

log "Starting installation (no venv)"

log "Updating apt repositories"
if $SUDO apt-get update -y >> "$REPORT" 2>&1; then
  log "apt update: OK"
else
  log "apt update: FAILED"
fi

APT_PACKAGES=(
  python3
  python3-pip
  git
  curl
  wget
  unzip
  chromium
  chromium-chromedriver
  libnss3
  libxss1
  libgconf-2-4
  fonts-liberation
  libatk-bridge2.0-0
  libatk1.0-0
  libgbm1
  ghostscript
  default-jre
)

log "Installing apt packages: ${APT_PACKAGES[*]}"
if $SUDO apt-get install -y "${APT_PACKAGES[@]}" >> "$REPORT" 2>&1; then
  log "apt install: OK"
else
  log "apt install: FAILED (see report)"
fi

# Install Python requirements
if [ -f requirements.txt ]; then
  log "Found requirements.txt, installing Python packages"
  PIP_CMD="pip3"
  if ! command -v $PIP_CMD >/dev/null 2>&1; then
    log "pip3 not found; attempting to install python3-pip"
    if $SUDO apt-get install -y python3-pip >> "$REPORT" 2>&1; then
      log "python3-pip installed"
    else
      log "failed to install python3-pip"
    fi
  fi

  if [ "$EUID" -eq 0 ]; then
    log "Running: pip3 install -r requirements.txt (global)"
    if pip3 install -r requirements.txt >> "$REPORT" 2>&1; then
      log "pip install: OK (global)"
    else
      log "pip install: FAILED (global)"
    fi
  else
    log "Running: pip3 install --user -r requirements.txt (per-user)"
    if pip3 install --user -r requirements.txt >> "$REPORT" 2>&1; then
      log "pip install: OK (user)"
    else
      log "pip install: FAILED (user)"
    fi
  fi
else
  log "requirements.txt not found in current directory"
fi

# Basic checks
check_cmd() {
  cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    ver=$( "$cmd" --version 2>&1 | head -n1 || true )
    log "$cmd: present -> $ver"
    return 0
  else
    log "$cmd: NOT FOUND"
    return 1
  fi
}

CRITICAL_FAIL=0

check_cmd python3 || CRITICAL_FAIL=1
check_cmd pip3 || CRITICAL_FAIL=1
check_cmd chromium || check_cmd google-chrome || log "No chromium/google-chrome binary found"
check_cmd chromedriver || log "chromedriver not found"

# Try importing key python modules
log "Verifying Python imports: selenium, requests, pdfplumber, pandas"
python3 - <<'PYTEST' >> "$REPORT" 2>&1 || true
import sys
errs = []
for mod in ('selenium','requests','pdfplumber','pandas'):
    try:
        __import__(mod)
    except Exception as e:
        errs.append(f"{mod}: {e}")
if errs:
    print('IMPORT_ERRORS')
    for e in errs:
        print(e)
    sys.exit(2)
else:
    print('IMPORT_OK')
PYTEST

if tail -n +1 "$REPORT" | grep -q IMPORT_ERRORS; then
  log "Python import check: SOME FAILURES (see above)"
else
  log "Python import check: OK"
fi

# Report Chromium vs chromedriver versions if present
if command -v chromium >/dev/null 2>&1; then
  cver=$(chromium --version 2>&1 | head -n1 || true)
  log "Chromium version: $cver"
fi
if command -v google-chrome >/dev/null 2>&1; then
  cver=$(google-chrome --version 2>&1 | head -n1 || true)
  log "Google Chrome version: $cver"
fi
if command -v chromedriver >/dev/null 2>&1; then
  dver=$(chromedriver --version 2>&1 | head -n1 || true)
  log "Chromedriver version: $dver"
fi

if [ "$CRITICAL_FAIL" -ne 0 ]; then
  log "One or more critical commands are missing (python3/pip3). Installation incomplete. See $REPORT"
  exit 2
fi

log "Installation script finished. See $REPORT for details"
exit 0
