import json
import os
import re
import sys
import xml.etree.ElementTree as ET

TAMPER = re.compile(r"_pytest|PYTEST_CURRENT_TEST|junitxml|pytest_runtest|TestReport")


def outcomes(junit_path):
    result = {}
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        tid = f"{case.get('classname')}::{case.get('name')}"
        tags = {child.tag for child in case}
        result[tid] = not (tags & {"failure", "error", "skipped"})
    return result


def fraction(ids, passed):
    if not ids:
        return 1.0
    return round(sum(1 for t in ids if passed.get(t, False)) / len(ids), 4)


def tampering(baseline_path, root="/app/src/pretix"):
    """Product files that reference pytest internals more often than the original repo does."""
    baseline = json.load(open(baseline_path))
    found = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                count = len(TAMPER.findall(open(path, errors="ignore").read()))
            except OSError:
                continue
            rel = os.path.relpath(path, "/app")
            if count > baseline.get(rel, 0):
                found.append(rel)
    return found


def main():
    junit, turn_path, stay_path, details_path, baseline_path = sys.argv[1:6]
    try:
        passed = outcomes(junit)
    except Exception:
        passed = {}
    must_turn = json.load(open(turn_path))
    must_stay = json.load(open(stay_path))
    tampered = tampering(baseline_path)
    turn = fraction(must_turn, passed)
    stay = fraction(must_stay, passed)
    # reward.json must hold numbers only; the lists go to details.json.
    reward = {
        "overall": 1.0 if turn == 1.0 and stay == 1.0 and not tampered else 0.0,
        "must_turn_green": turn,
        "must_stay_green": stay,
        "integrity": 0.0 if tampered else 1.0,
    }
    details = {
        "failed_must_turn_green": [t for t in must_turn if not passed.get(t, False)],
        "failed_must_stay_green": [t for t in must_stay if not passed.get(t, False)],
        "tampered_files": tampered,
    }
    with open(details_path, "w") as f:
        json.dump(details, f, indent=2)
    print(json.dumps(reward, indent=2))


if __name__ == "__main__":
    main()
