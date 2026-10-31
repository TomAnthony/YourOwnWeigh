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
"$patch_python" -m unittest discover -s tools -p test_probe_withings_firmware.py -v
"$patch_python" -m unittest discover -s tools -p test_capture_wbs13_http.py -v
"$patch_python" -m unittest discover -s firmware/wbs13/v1311 -p test_body_composition.py -v
node --check server/static/firmware.js
printf 'Offline checks passed. Review skipped private-image tests; hardware is not exercised.\n'
