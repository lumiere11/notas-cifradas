#!/usr/bin/env bash
# Construye una versión AUTOCONTENIDA: Python + Qt6 + OpenSSL/Argon2 empaquetados.
# El resultado (release/notas-cifradas-linux-<arq>.tar.gz) no necesita pacman, pip ni Python.
# Requisitos para construir: python3 (con venv) y acceso a PyPI.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
arch="$(uname -m)"
work="$here/build"
rel="$here/release/notas-cifradas-linux-$arch"

rm -rf "$work" "$rel"
mkdir -p "$work"

echo "==> Entorno virtual aislado con las versiones fijadas"
python3 -m venv "$work/venv"
"$work/venv/bin/pip" install --quiet --disable-pip-version-check -r "$here/requirements-build.txt"

echo "==> Empaquetando con PyInstaller"
cd "$here"
"$work/venv/bin/pyinstaller" --noconfirm --clean --log-level WARN \
    --name notas-cifradas \
    --distpath "$work/dist" --workpath "$work/pyi" --specpath "$work" \
    --paths "$here" \
    --add-data "$here/notas_cifradas/icon.svg:notas_cifradas" \
    --hidden-import PySide6.QtSvg --hidden-import PySide6.QtDBus \
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc \
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtOpenGL \
    --exclude-module PySide6.QtPdf --exclude-module PySide6.QtSql \
    --exclude-module PySide6.QtTest --exclude-module PySide6.QtXml \
    "$here/packaging/entry.py"

echo "==> Montando el paquete de instalación"
mkdir -p "$rel/data"
cp -r "$work/dist/notas-cifradas" "$rel/bundle"
cp "$here/install.sh" "$here/README.md" "$rel/"
cp "$here/data/notas-cifradas.desktop" "$rel/data/"
cp "$here/notas_cifradas/icon.svg" "$rel/data/notas-cifradas.svg"
tar -C "$here/release" -czf "$rel.tar.gz" "$(basename "$rel")"
( cd "$here/release" && sha256sum "$(basename "$rel").tar.gz" | tee "$(basename "$rel").tar.gz.sha256" )

echo
echo "Listo: $rel.tar.gz ($(du -h "$rel.tar.gz" | cut -f1), instalado ~$(du -sh "$rel/bundle" | cut -f1))"
echo "Probar:      $rel/bundle/notas-cifradas --selftest"
echo "Instalar:    $rel/install.sh"
