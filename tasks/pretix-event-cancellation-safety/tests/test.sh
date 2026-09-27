#!/bin/bash
# No `set -e`: a crashing test run must still end in a reward file.
mkdir -p /logs/verifier
echo '{"overall": 0.0, "must_turn_green": 0.0, "must_stay_green": 0.0}' > /logs/verifier/reward.json

cp -r /tests/files/. /app/
xargs -r rm -f < /tests/deleted_files.txt

cd /app/src
python -m pytest tests/base/test_cancelevent.py -p no:sugar -p no:cacheprovider -q -n 4 \
    --junitxml=/logs/verifier/junit.xml > /logs/verifier/pytest.log 2>&1

python /tests/grade.py /logs/verifier/junit.xml /tests/must_turn_green.json /tests/must_stay_green.json /logs/verifier/details.json \
    > /logs/verifier/reward.json.tmp && mv /logs/verifier/reward.json.tmp /logs/verifier/reward.json
cat /logs/verifier/reward.json
exit 0
