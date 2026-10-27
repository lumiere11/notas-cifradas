#!/bin/sh
export PYTHONPATH=/app/share/notas-cifradas${PYTHONPATH:+:$PYTHONPATH}
exec python3 -m notas_cifradas "$@"
