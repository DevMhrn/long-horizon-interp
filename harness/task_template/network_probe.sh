#!/bin/bash
mkdir -p /logs/agent
python3 - > /logs/agent/netprobe.txt 2>&1 <<'PY'
import getpass, socket, subprocess, urllib.request, ssl
print("user =", getpass.getuser())
for url in ["https://github.com", "https://api.github.com/repos/pretix/pretix/pulls/6115",
            "https://codeload.github.com/pretix/pretix/zip/refs/heads/master", "https://pypi.org/simple/six/",
            "https://example.com", "https://www.google.com", "https://api.anthropic.com/v1/messages", "https://api.openai.com/v1/models", "https://openrouter.ai/api/v1/models"]:
    try:
        r = urllib.request.urlopen(url, timeout=15)
        print(f"{url} -> REACHABLE (HTTP {r.status})")
    except urllib.error.HTTPError as e:
        print(f"{url} -> REACHABLE (HTTP {e.code})")
    except Exception as e:
        print(f"{url} -> BLOCKED ({type(e).__name__}: {str(e)[:100]})")
for host in ["github.com", "pypi.org", "api.anthropic.com"]:
    try:
        print(f"dns {host} -> {socket.gethostbyname(host)}")
    except Exception as e:
        print(f"dns {host} -> FAILED ({e})")
r = subprocess.run(["git", "ls-remote", "https://github.com/pretix/pretix.git", "HEAD"], capture_output=True, text=True, timeout=30)
print("git ls-remote github ->", "REACHABLE" if r.returncode == 0 else f"BLOCKED ({r.stderr.strip()[:120]})")
PY
cat /logs/agent/netprobe.txt
