"""Punto de entrada para PyInstaller (el paquete usa imports relativos, así que no se puede
congelar notas_cifradas/__main__.py directamente)."""
import sys

from notas_cifradas.app import main

sys.exit(main())
