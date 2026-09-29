#!/bin/bash
# Clean-machine proof for one task, on one platform:
#   1. build the task's environment/ with no layer cache and a fresh pull of the pinned base image
#   2. nop:    run tests/test.sh on the untouched image           -> overall must be 0.0
#   3. oracle: run solution/solve.sh as the agent user, then test.sh -> overall must be 1.0
# Plain docker (no Harbor), so there is no verifier timeout: emulated platforms are slow.
# Usage: harness/verify_clean_build.sh tasks/<slug> linux/amd64|linux/arm64
set -u
TASK=$(cd "$1" && pwd); PLATFORM=$2; SLUG=$(basename "$TASK"); ARCH=${PLATFORM#linux/}
OUT=$(cd "$(dirname "$0")/.." && pwd)/output/verify/$SLUG-$ARCH; mkdir -p "$OUT"
TAG=clean-$SLUG:$ARCH
t0=$(date +%s)
docker buildx build --platform "$PLATFORM" --no-cache --pull --load -t "$TAG" "$TASK/environment" > "$OUT/build.log" 2>&1
build_rc=$?; t1=$(date +%s)
run() {  # $1 = label, $2 = extra step before the verifier
  docker run --rm --platform "$PLATFORM" -v "$TASK/tests:/tests:ro" -v "$TASK/solution:/solution:ro" "$TAG" \
    bash -c "$2 bash /tests/test.sh" > "$OUT/$1.log" 2>&1
  python3 - "$OUT/$1.log" <<'PY'
import json, sys
t = open(sys.argv[1]).read(); i = t.rfind('{\n  "overall"')
print(json.dumps(json.loads(t[i:t.rfind("}") + 1])) if i >= 0 else "null")
PY
}
if [ $build_rc -eq 0 ]; then
  nop=$(run nop ""); t2=$(date +%s)
  oracle=$(run oracle "su agent -s /bin/bash -c 'bash /solution/solve.sh' &&"); t3=$(date +%s)
else nop=null; oracle=null; t2=$t1; t3=$t1; fi
image_id=$(docker image inspect "$TAG" --format '{{.Id}} {{.Os}}/{{.Architecture}}' 2>/dev/null)
cat > "$OUT/result.json" <<J
{"task": "$SLUG", "platform": "$PLATFORM", "image": "$image_id", "build_rc": $build_rc,
 "build_seconds": $((t1-t0)), "nop_seconds": $((t2-t1)), "oracle_seconds": $((t3-t2)),
 "nop": $nop, "oracle": $oracle}
J
cat "$OUT/result.json"
