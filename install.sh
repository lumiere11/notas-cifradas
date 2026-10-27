#!/usr/bin/env bash
# Instala Notas Cifradas para el usuario actual (no necesita root).
#   ./install.sh              instalar o actualizar
#   ./install.sh --uninstall  desinstalar (NO borra tus notas)
#
# Si junto al script hay una carpeta bundle/ (versión autocontenida, ver build-bundle.sh) se instala
# esa y no hace falta ninguna dependencia. Si no, usa el Python y el Qt6 del sistema.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data/notas-cifradas/app"
bundle_dir="$data/notas-cifradas/bundle"
bin="$HOME/.local/bin/notas-cifradas"
desktop="$data/applications/notas-cifradas.desktop"
icon="$data/icons/hicolor/scalable/apps/notas-cifradas.svg"

refresh_menus() {
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database "$data/applications" 2>/dev/null || true
    fi
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -qtf "$data/icons/hicolor" 2>/dev/null || true
    fi
    # Plasma 6 / Plasma 5: refresca el menú de aplicaciones
    if command -v kbuildsycoca6 >/dev/null; then kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    elif command -v kbuildsycoca5 >/dev/null; then kbuildsycoca5 --noincremental >/dev/null 2>&1 || true; fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$app_dir" "$bundle_dir"
    rm -f "$bin" "$desktop" "$icon"
    refresh_menus
    echo "Desinstalado. Tus notas siguen en: $data/notas-cifradas/vault.ncv"
    exit 0
fi

mkdir -p "$(dirname "$bin")" "$(dirname "$desktop")" "$(dirname "$icon")"
rm -rf "$app_dir" "$bundle_dir"   # por si antes se instaló en el otro modo

if [[ -x "$here/bundle/notas-cifradas" ]]; then
    echo "Modo autocontenido: no se usan dependencias del sistema."
    mkdir -p "$data/notas-cifradas"
    cp -r "$here/bundle" "$bundle_dir"
    # shellcheck disable=SC2016  # el $ debe quedar literal en el lanzador generado
    printf '#!/usr/bin/env bash\nexec "%s/notas-cifradas" "$@"\n' "$bundle_dir" > "$bin"
    icon_src="$here/data/notas-cifradas.svg"
else
    if ! python3 - <<'PY' 2>/dev/null
import PySide6.QtWidgets
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
PY
    then
        cat >&2 <<'MSG'
Faltan dependencias. En CachyOS / Arch:

    sudo pacman -S --needed pyside6 python-cryptography

(python-cryptography debe ser >= 44 para tener Argon2id; ejecuta `sudo pacman -Syu` si dudas.)
O construye la versión autocontenida, que no necesita nada:  ./build-bundle.sh
MSG
        exit 1
    fi
    mkdir -p "$app_dir"
    cp -r "$here/notas_cifradas" "$app_dir/"
    find "$app_dir" -name __pycache__ -prune -exec rm -rf {} +
    # shellcheck disable=SC2016
    printf '#!/usr/bin/env bash\nexport PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}"\nexec python3 -m notas_cifradas "$@"\n' \
        "$app_dir" > "$bin"
    icon_src="$here/notas_cifradas/icon.svg"
fi
chmod 755 "$bin"

install -m 644 "$icon_src" "$icon"
sed "s|@BIN@|$bin|" "$here/data/notas-cifradas.desktop" > "$desktop"
chmod 644 "$desktop"
refresh_menus

echo "Instalado. Búscala como «Notas Cifradas» en el lanzador de aplicaciones, o ejecuta: $bin"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Aviso: $HOME/.local/bin no está en tu PATH (el lanzador del menú funciona igualmente).";; esac
