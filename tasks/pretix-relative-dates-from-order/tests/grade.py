import json
import sys
import xml.etree.ElementTree as ET


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


def main():
    junit, turn_path, stay_path, details_path = sys.argv[1:5]
    try:
        passed = outcomes(junit)
    except Exception:
        passed = {}
    must_turn = json.load(open(turn_path))
    must_stay = json.load(open(stay_path))
    turn = fraction(must_turn, passed)
    stay = fraction(must_stay, passed)
    # reward.json must hold numbers only; the lists of failing tests go to details.json.
    reward = {
        "overall": 1.0 if turn == 1.0 and stay == 1.0 else 0.0,
        "must_turn_green": turn,
        "must_stay_green": stay,
    }
    details = {
        "failed_must_turn_green": [t for t in must_turn if not passed.get(t, False)],
        "failed_must_stay_green": [t for t in must_stay if not passed.get(t, False)],
    }
    with open(details_path, "w") as f:
        json.dump(details, f, indent=2)
    print(json.dumps(reward, indent=2))


if __name__ == "__main__":
    main()
