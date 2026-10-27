#!/usr/bin/env python3
"""Regenera python3-cryptography.json con las URL y sha256 de PyPI.

Flatpak construye sin red, así que cada archivo que descarga debe estar declarado con su hash.
Para subir de versión: cambia PINS, ejecuta este script y revisa el diff.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

PINS = {"cryptography": "50.0.1", "cffi": "2.1.1", "pycparser": "3.12"}
ARCHES = ("x86_64", "aarch64")
# El runtime puede llevar cualquiera de estos Python; pip elige la rueda compatible al instalar.
CFFI_PYTHONS = ("cp312", "cp313", "cp314")
OUT = Path(__file__).with_name("python3-cryptography.json")


def pypi_files(name: str, version: str) -> list[dict]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as resp:
        return json.load(resp)["urls"]


def pick(files: list[dict], pattern: str) -> dict:
    found = sorted((f for f in files if re.fullmatch(pattern, f["filename"])), key=lambda f: f["filename"])
    if not found:
        sys.exit(f"No hay rueda que cumpla {pattern!r}")
    return found[0]


def source(f: dict, arch: str | None) -> dict:
    entry = {"type": "file", "url": f["url"], "sha256": f["digests"]["sha256"]}
    if arch:
        entry["only-arches"] = [arch]
    return entry


def main() -> None:
    sources = []
    crypto = pypi_files("cryptography", PINS["cryptography"])
    cffi = pypi_files("cffi", PINS["cffi"])
    pycparser = pypi_files("pycparser", PINS["pycparser"])

    for arch in ARCHES:
        # abi3: una sola rueda sirve para todas las versiones de Python >= 3.11
        sources.append(source(pick(crypto, rf"cryptography-[^-]+-cp311-abi3-manylinux_2_28_{arch}\.whl"), arch))
        for py in CFFI_PYTHONS:
            sources.append(source(pick(cffi, rf"cffi-[^-]+-{py}-{py}-manylinux[^-]*{arch}\.whl"), arch))
    sources.append(source(pick(pycparser, r"pycparser-[^-]+-py3-none-any\.whl"), None))

    module = {
        "name": "python3-cryptography",
        "buildsystem": "simple",
        "build-commands": [
            "pip3 install --verbose --exists-action=i --no-index --find-links=\"file://${PWD}\" "
            "--prefix=${FLATPAK_DEST} --no-deps --no-build-isolation cryptography cffi pycparser"
        ],
        "sources": sources,
    }
    OUT.write_text(json.dumps(module, indent=4) + "\n")
    print(f"{OUT.name}: {len(sources)} archivos")
    for s in sources:
        print("  ", s["url"].rsplit("/", 1)[-1], s.get("only-arches", ["todas"])[0])


if __name__ == "__main__":
    main()
