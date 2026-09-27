#!/bin/bash
# No `set -e`: a crashing test run must still end in a reward file.
mkdir -p /logs/verifier
echo '{"overall": 0.0, "must_turn_green": 0.0, "must_stay_green": 0.0, "integrity": 0.0}' > /logs/verifier/reward.json

# 1. Restore the whole test tree and the pytest config from the verifier's own copy.
rm -rf /app/src/tests
tar -xzf /tests/pristine.tar.gz -C /app

# 2. Remove anything that could hook into pytest from outside the restored tree:
#    stray conftest.py, pytest.ini/tox.ini, and new top-level entries in /app/src
#    (e.g. a pytest.py that shadows the real one).
: > /logs/verifier/removed.txt
find /app -path /app/src/tests -prune -o \
    \( -name conftest.py -o -name pytest.ini -o -name tox.ini -o -name sitecustomize.py -o -name usercustomize.py \) \
    -print >> /logs/verifier/removed.txt
grep -v '^/app/src/tests$' /logs/verifier/removed.txt | xargs -r rm -rf
for entry in /app/src/* /app/src/.[!.]*; do
    [ -e "$entry" ] || continue
    grep -qxF "$(basename "$entry")" /opt/verifier/src_toplevel.txt || { echo "$entry" >> /logs/verifier/removed.txt; rm -rf "$entry"; }
done

# 3. Run the graded files with the config pinned explicitly.
cd /app/src
python -m pytest -c /app/src/setup.cfg tests/api/test_checkinrpc.py tests/api/test_order_create.py tests/base/test_checkin.py tests/base/test_orders.py -p no:sugar -p no:cacheprovider -q -n 4 \
    --junitxml=/logs/verifier/junit.xml > /logs/verifier/pytest.log 2>&1

# 4. Grade. The reward file is always written here, after the agent has finished.
python /tests/grade.py /logs/verifier/junit.xml /tests/must_turn_green.json /tests/must_stay_green.json \
    /logs/verifier/details.json /tests/tamper_baseline.json \
    > /logs/verifier/reward.json.tmp && mv /logs/verifier/reward.json.tmp /logs/verifier/reward.json
cat /logs/verifier/reward.json
exit 0
