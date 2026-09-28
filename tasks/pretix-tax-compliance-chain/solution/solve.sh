#!/bin/bash
set -euo pipefail
cd /app
git apply --whitespace=nowarn /solution/gold.patch
cd /app/src
python -c "import django; import pretix"
