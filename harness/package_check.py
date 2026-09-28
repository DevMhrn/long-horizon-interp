#!/usr/bin/env python3
"""Package check: is a task folder complete, clean and leak-free?

Static checks only (nothing is built or run). Each check is pass/fail with details;
the folder passes only if every check passes.

    files            required files exist; solve.sh and test.sh are executable
    task_toml        parses; metadata, timeouts, resources and network policy present;
                     no DRAFT placeholders
    dockerfile       base pinned by digest; no :latest; apt update + list cleanup;
                     never copies tests/ or solution/; no `curl | sh`, no `ADD http`
    gold_no_tests    the solution patch touches no test files
    secrets          no API keys or private keys anywhere in the folder
    size             folder under 50 MB
    instruction      not a draft; no PR number, commit sha, upstream PR/commit URL,
                     existing product file path, graded test name, or "the fix/patch"
    mechanism_leak   no identifier that exists only in the gold patch and that no graded
                     test uses (that would be telling the agent HOW, not WHAT)
    contract         every new identifier/literal a must_turn_green test relies on is
                     stated in the instruction (otherwise the agent is asked to guess)

Writes <task>/.package_report.json (never shipped inside the image).

Usage:
    python3 harness/package_check.py tasks/<slug>
"""
import ast
import io
import json
import pathlib
import re
import subprocess
import sys
import tarfile
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT / "output" / "repos" / "pretix"
REQUIRED = ["instruction.md", "task.toml", "environment/Dockerfile", "solution/solve.sh", "tests/test.sh"]
METADATA_KEYS = ["author_name", "author_email", "category", "tags", "difficulty_explanation",
                 "solution_explanation", "verification_explanation", "expert_time_estimate_hours"]
SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
                       r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]{10,}")
BANNED_PHRASES = re.compile(r"\bthe (fix|patch|bug fix)\b|\bgold\b|\bupstream (pr|commit)\b|pull request #?\d+", re.I)
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
COMMON = set("self none true false return assert data json status_code response resp client organizer event "
             "order item items position positions content objects create filter first count list dict test".split())


def check(name, ok, **details):
    return {"check": name, "ok": bool(ok), **({"details": details} if details else {})}


def gold_added_removed(gold):
    added, removed, files = [], [], []
    for line in gold.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return "\n".join(added), "\n".join(removed), files


_BASE_CACHE = {}


def base_corpus(base):
    """All product source text at the base commit, read once with `git archive`."""
    if base not in _BASE_CACHE:
        raw = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", base, "src/pretix"],
                             capture_output=True, check=True).stdout
        chunks = []
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.endswith((".py", ".html", ".js", ".txt")) and "/locale/" not in m.name:
                    chunks.append(tar.extractfile(m).read().decode("utf-8", "ignore"))
        text = "\n".join(chunks)
        _BASE_CACHE[base] = (text, set(re.findall(r"\w+", text)))
    return _BASE_CACHE[base]


def existing_at(base, tokens):
    """Which tokens already occur in the product code at the base commit (whole words for identifiers)."""
    text, words = base_corpus(base)
    return {t for t in tokens if (t in words if re.fullmatch(r"\w+", t) else t in text)}


def test_function_sources(task):
    """name -> source of every test function in the graded files, and literal strings per test."""
    sources, literals = {}, {}
    with tarfile.open(task / "tests" / "pristine.tar.gz") as tar:
        members = [(m.name, tar.extractfile(m).read().decode("utf-8", "ignore")) for m in tar.getmembers()
                   if m.isfile() and pathlib.PurePath(m.name).name.startswith("test_") and m.name.endswith(".py")]
    for name, text in members:
        module = ".".join(pathlib.PurePath(name).relative_to("src").with_suffix("").parts)
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                key = f"{module}::{node.name}"
                sources[key] = ast.get_source_segment(text, node) or ""
                literals[key] = {n.value for n in ast.walk(node)
                                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and 3 <= len(n.value) <= 60}
    return sources, literals


def run(task):
    task = pathlib.Path(task).resolve()
    pack = json.loads((task / ".pack.json").read_text()) if (task / ".pack.json").exists() else {}
    results = []

    missing = [p for p in REQUIRED if not (task / p).exists()]
    not_exec = [p for p in ("solution/solve.sh", "tests/test.sh") if (task / p).exists()
                and not (task / p).stat().st_mode & 0o111]
    results.append(check("files", not missing and not not_exec, missing=missing, not_executable=not_exec))

    problems = []
    try:
        cfg = tomllib.loads((task / "task.toml").read_text())
        md = cfg.get("metadata", {})
        problems += [f"metadata.{k} missing" for k in METADATA_KEYS if md.get(k) in (None, "", [])]
        problems += [f"metadata.{k} is DRAFT" for k in METADATA_KEYS if isinstance(md.get(k), str) and "DRAFT" in md[k]]
        if not md.get("expert_time_estimate_hours"):
            problems.append("metadata.expert_time_estimate_hours is 0")
        for sect, key in (("verifier", "timeout_sec"), ("agent", "timeout_sec"), ("environment", "build_timeout_sec"),
                          ("environment", "cpus"), ("environment", "memory_mb")):
            if key not in cfg.get(sect, {}):
                problems.append(f"{sect}.{key} missing")
        env = cfg.get("environment", {})
        if "allow_internet" not in env and "network_mode" not in env:
            problems.append("no network policy (allow_internet / network_mode)")
    except Exception as e:
        problems.append(f"does not parse: {e}")
    results.append(check("task_toml", not problems, problems=problems))

    df = (task / "environment" / "Dockerfile").read_text() if (task / "environment" / "Dockerfile").exists() else ""
    problems = []
    froms = re.findall(r"^FROM\s+(\S+)", df, re.M)
    if not froms or any("@sha256:" not in f for f in froms):
        problems.append("FROM not pinned by digest")
    if re.search(r":latest\b", df):
        problems.append(":latest tag")
    if "apt-get install" in df and ("apt-get update" not in df or "rm -rf /var/lib/apt/lists" not in df):
        problems.append("apt-get install without update + list cleanup")
    if re.search(r"^(COPY|ADD)\s+.*\b(tests|solution)\b", df, re.M | re.I):
        problems.append("copies tests/ or solution/ into the image")
    if re.search(r"curl[^\n|]*\|\s*(ba)?sh", df) or re.search(r"^ADD\s+https?://", df, re.M):
        problems.append("remote script piped to shell or ADD from URL")
    results.append(check("dockerfile", not problems, problems=problems))

    gold = (task / "solution" / "gold.patch").read_text() if (task / "solution" / "gold.patch").exists() else ""
    added, _removed, gold_files = gold_added_removed(gold)
    touched_tests = [f for f in gold_files if "/tests/" in f or pathlib.PurePath(f).name.startswith("test_")]
    results.append(check("gold_no_tests", not touched_tests, files=touched_tests))

    hits = []
    for f in task.rglob("*"):
        if f.is_file() and f.stat().st_size < 5_000_000 and not f.name.startswith(".package_report"):
            m = SECRET_RE.search(f.read_text(errors="ignore"))
            if m:
                hits.append(f"{f.relative_to(task)}: {m.group(0)[:12]}…")
    results.append(check("secrets", not hits, hits=hits))

    size_mb = sum(f.stat().st_size for f in task.rglob("*") if f.is_file()) / 1e6
    results.append(check("size", size_mb < 50, mb=round(size_mb, 1)))

    instr = (task / "instruction.md").read_text() if (task / "instruction.md").exists() else ""
    problems = []
    if "DRAFT" in instr:
        problems.append("instruction is still a DRAFT")
    for number in pack.get("prs") or ([pack["pr"]] if pack.get("pr") else []):
        if re.search(rf"#?\b{number}\b", instr):
            problems.append(f"mentions PR number {number}")
    for sha in (pack.get("sha", ""), pack.get("base", "")):
        if sha and re.search(rf"\b{sha[:7]}", instr):
            problems.append(f"mentions commit {sha[:7]}")
    if re.search(r"github\.com/[^\s)]+/(pull|commit)/", instr):
        problems.append("links an upstream PR or commit")
    for f in pack.get("gold_src_files", []):
        if f in instr or f.removeprefix("src/") in instr:
            problems.append(f"names product file {f}")
    sources, literals = test_function_sources(task)
    graded = json.loads((task / "tests" / "must_turn_green.json").read_text()) + \
        json.loads((task / "tests" / "must_stay_green.json").read_text())
    for tid in graded:
        name = tid.split("::")[-1].split("[")[0]
        if re.search(rf"\b{re.escape(name)}\b", instr):
            problems.append(f"names graded test {name}")
    m = BANNED_PHRASES.search(instr)
    if m:
        problems.append(f"phrase '{m.group(0)}'")
    results.append(check("instruction", not problems, problems=sorted(set(problems))))

    must_turn = json.loads((task / "tests" / "must_turn_green.json").read_text())
    test_words = set()
    for tid in must_turn:
        src = sources.get(tid.split("[")[0], "")
        test_words |= set(WORD.findall(src))
        test_words |= literals.get(tid.split("[")[0], set())
    gold_words = set(WORD.findall(added))
    all_graded_words = set()
    for src in sources.values():
        all_graded_words |= set(WORD.findall(src))
    with tarfile.open(task / "tests" / "pristine.tar.gz") as tar:
        graded_modules = {".".join(t.split("::")[0].split(".")[:3]) for t in graded}
        for m in tar.getmembers():
            mod = ".".join(pathlib.PurePath(m.name).relative_to("src").with_suffix("").parts) if m.name.startswith("src/") else ""
            if m.isfile() and m.name.endswith(".py") and any(g.startswith(mod) for g in graded_modules if mod):
                all_graded_words |= set(WORD.findall(tar.extractfile(m).read().decode("utf-8", "ignore")))
    base = pack.get("base")
    new_in_gold = gold_words - existing_at(base, gold_words) if base else set()
    instr_words = set(WORD.findall(instr)) | {s for s in re.findall(r"`([^`]+)`", instr)}

    # Names the PR documents for users (its doc/ changes) are public contract, not implementation detail.
    public = set()
    if base and pack.get("sha"):
        doc_diff = subprocess.run(["git", "-C", str(REPO), "diff", base, pack["sha"], "--", "doc"],
                                  capture_output=True, text=True).stdout
        public = set(WORD.findall("\n".join(l for l in doc_diff.splitlines() if l.startswith("+"))))
    def is_public(w):
        return w in public or w.lower() in public or any(w.endswith("_" + p.upper()) for p in public if len(p) > 3)
    leaked = sorted(w for w in new_in_gold if w in instr_words and w not in all_graded_words
                    and w.lower() not in COMMON and not is_public(w))
    results.append(check("mechanism_leak", not leaked, identifiers=leaked))

    # A test relies on something "new" if it appears in the gold patch's added lines and nowhere in the
    # product code at the base commit: an identifier, a field name, or a literal such as an error text.
    # Short all-lowercase fragments ("ness", "able") are tokenizer noise, not contract names.
    added_words = set(re.findall(r"\w+", added))
    in_gold = {w for w in test_words if w.lower() not in COMMON
               and (w in added_words if re.fullmatch(r"\w+", w) else w in added)
               and not (len(w) < 5 and w.isalpha() and w.islower())}
    contract_needed = sorted(in_gold - existing_at(base, in_gold)) if base else []
    unstated = [w for w in contract_needed if w not in instr]
    results.append(check("contract", not unstated, needed=len(contract_needed), unstated=unstated))

    report = {"task": str(task.relative_to(ROOT)), "ok": all(r["ok"] for r in results), "checks": results}
    (task / ".package_report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    report = run(sys.argv[1])
    for r in report["checks"]:
        print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['check']:<15} {'' if r['ok'] else json.dumps(r.get('details', {}))[:300]}")
    print("PACKAGE CHECK:", "PASS" if report["ok"] else "FAIL")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
