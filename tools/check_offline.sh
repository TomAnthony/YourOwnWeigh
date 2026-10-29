#!/bin/sh
# Model-neutral regression suite; no hardware, network fetch, cloud deployment,
# personal database or Apple Health access. Install bridge and npm deps first.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
patch_python=${YOW_PYTHON:-.venv/bin/python}
npm run worker:typecheck
npm run server:typecheck
npm run server:test
"$patch_python" -m unittest discover -s bridge/tests -v
node --check server/static/firmware.js
printf 'Offline checks passed. Review skipped private-image tests; hardware is not exercised.\n'
