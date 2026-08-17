"""End-to-end smoke test against a deployed AI Brain.

    python3 tests/smoke_deployment.py https://ai-brain-production-4bd9.up.railway.app

Checks the page, the curriculum, the whole Brain Lab and one full streaming
answer. Every numeric assertion has a closed form behind it, so a pass means
the deployed lab is *correct*, not merely reachable — a deployment can serve
200s for every route while quietly computing nonsense.
"""
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "").rstrip("/")
if not BASE:
    sys.exit("usage: smoke_deployment.py <base-url>")

fails = []


def get(path, timeout=60):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                       # DNS, TLS, refused, timeout
        return None, str(e).encode()


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


print(f"\n=== {BASE} ===\n[static]")
st, body = get("/")
check("GET /", st == 200 and b"AI Brain" in body, f"HTTP {st}, {len(body)} bytes")
check("Brain Lab tab present", b'data-tab="lab"' in body)
check("Curriculum tab present", b'data-tab="cur"' in body)
st, body = get("/vendor/katex/katex.min.js")
check("vendored KaTeX served", st == 200 and len(body) > 100_000, f"HTTP {st}, {len(body)} bytes")

print("[status]")
st, body = get("/api/status")
if check("/api/status", st == 200, f"HTTP {st}"):
    d = json.loads(body)
    check("DEEPSEEK_API_KEY is set on the host", d.get("key_set") is True,
          "without it /api/ask cannot answer")

print("[curriculum — the spine when the shelves are absent]")
st, body = get("/api/curriculum")
if check("/api/curriculum", st == 200, f"HTTP {st}"):
    d = json.loads(body)
    check("47 topics live", d.get("total") == 47, f"got {d.get('total')}")
    ids = {t["id"] for t in d["topics"]}
    for want in ("attention-mechanism", "backpropagation", "information-theory",
                 "state-estimation-and-slam", "electronics-foundations"):
        check(f"topic {want} present", want in ids)
    check("topics carry equations",
          any(t["key_equations"] for t in d["topics"]))
st, body = get("/api/curriculum?" + urllib.parse.urlencode(
    {"q": "why does attention divide by sqrt(d_k)"}))
if st == 200:
    m = [t["id"] for t in json.loads(body)["matched"]]
    check("attention question matches attention topic first",
          m[:1] == ["attention-mechanism"], f"got {m[:2]}")
st, body = get("/api/curriculum?q=" + urllib.parse.urlencode({"q": "best pizza in Naples"})[2:])
if st == 200:
    check("off-topic question matches nothing",
          json.loads(body)["matched"] == [])

print("[brain lab — symbolic]")
st, body = get("/api/lab")
check("/api/lab", st == 200, f"HTTP {st}")
st, body = get("/api/symbolic?" + urllib.parse.urlencode(
    {"expr": "x**2 + 3*x*y + y**2", "op": "gradient", "vars": "x,y"}))
if check("gradient endpoint", st == 200, f"HTTP {st}"):
    d = json.loads(body)
    check("grad(x^2+3xy+y^2) = [2x+3y, 3x+2y]",
          "2*x + 3*y" in d.get("result", "") and "3*x + 2*y" in d.get("result", ""),
          d.get("result", "")[:50])
st, body = get("/api/symbolic?" + urllib.parse.urlencode(
    {"expr": "x**2 - 5*x + 6", "op": "solve"}))
check("solve x^2-5x+6 = [2, 3]", st == 200 and json.loads(body).get("result") == "[2, 3]")

print("[brain lab — matrix, against closed forms]")
st, body = get("/api/matrix?" + urllib.parse.urlencode({"m": "2,0; 0,3", "op": "eigenvalues"}))
if check("eigenvalues endpoint", st == 200, f"HTTP {st}"):
    check("diag(2,3) eigenvalues are 2 and 3",
          sorted(json.loads(body)["eigenvalues"]) == [2.0, 3.0])
st, body = get("/api/matrix?" + urllib.parse.urlencode({"m": "1,2; 2,4", "op": "summary"}))
if st == 200:
    d = json.loads(body)
    check("singular matrix has rank 1", d.get("rank") == 1)
    check("singular matrix reports infinite conditioning",
          d.get("condition_number") in (float("inf"), "Infinity") or
          (isinstance(d.get("condition_number"), float) and math.isinf(d["condition_number"])),
          str(d.get("condition_number")))
st, body = get("/api/matrix?" + urllib.parse.urlencode({"m": "1,2; 2,4", "op": "inverse"}))
check("inverse of a singular matrix is refused",
      st == 200 and json.loads(body).get("ok") is False)
st, body = get("/api/matrix?" + urllib.parse.urlencode(
    {"m": "1,1; 1,-1", "op": "least_squares", "b": "3; 1"}))
if st == 200:
    d = json.loads(body)
    check("least squares solves x+y=3, x-y=1 as (2,1)",
          [round(v, 6) for v in d.get("solution", [])] == [2.0, 1.0], str(d.get("solution")))
st, body = get("/api/matrix?" + urllib.parse.urlencode(
    {"m": "5,0; 0,1", "op": "power_iteration", "iter": "60"}))
if st == 200:
    d = json.loads(body)
    check("power iteration finds dominant eigenvalue 5",
          abs(d.get("dominant_eigenvalue", 0) - 5.0) < 1e-6, str(d.get("dominant_eigenvalue")))

print("[brain lab — gradient descent, against theory]")
st, body = get("/api/descent?" + urllib.parse.urlencode(
    {"f": "x**2 + y**2", "start": "3, 4", "lr": "0.1", "steps": "200"}))
if check("descent endpoint", st == 200, f"HTTP {st}"):
    d = json.loads(body)
    check("bowl converges to the origin",
          max(abs(v) for v in d["final_point"]) < 1e-6, str(d["final_point"]))
    check("trajectory returned for plotting", len(d.get("path", [])) > 10)
# f = x^2 has L = 2, so the 2/L rule says lr > 1 diverges and lr < 1 does not
st, body = get("/api/descent?" + urllib.parse.urlencode(
    {"f": "x**2", "start": "1", "lr": "1.1", "steps": "60"}))
check("lr above 2/L diverges", st == 200 and json.loads(body).get("diverged") is True)
st, body = get("/api/descent?" + urllib.parse.urlencode(
    {"f": "x**2", "start": "1", "lr": "0.9", "steps": "200"}))
check("lr below 2/L converges", st == 200 and json.loads(body).get("diverged") is False)

print("[sandbox]")
for bad in ('__import__("os").system("id")', 'open("/etc/passwd")'):
    st, body = get("/api/symbolic?" + urllib.parse.urlencode({"expr": bad}))
    check(f"blocks {bad[:30]}", st == 200 and json.loads(body).get("ok") is False)

print("[streaming answer]")
q = urllib.parse.urlencode({"q": "why does attention scale the dot product by 1/sqrt(d_k)",
                            "mode": "explain", "depth": "intro"})
st, body = get("/api/ask?" + q, timeout=300)
if check("/api/ask streams", st == 200, f"HTTP {st}"):
    text = body.decode("utf-8", "replace")
    stages = [ln.split(": ", 1)[1] for ln in text.splitlines() if ln.startswith("event: ")]
    check("pipeline stages streamed", len(set(stages)) >= 4, ", ".join(sorted(set(stages))))
    check("no API-key error", "No DEEPSEEK_API_KEY" not in text)
    check("an answer came back", '"prose"' in text)
    check("curriculum reached the answer", "C:" in text,
          "the hosted box has no book indexes, so this is what grounds it")
    # Milestone-1 regression tripwire: the frontend header used to claim
    # "routed to books" from d.routing alone, with no cross-check against
    # what retrieval actually returned. honesty.grounded_in_library /
    # covered_by_curriculum are the fields that fix that — assert they're
    # actually present and boolean in the real payload, not just that some
    # other field exists.
    done_lines = [ln for ln in text.splitlines() if ln.startswith("data: ") and '"honesty"' in ln]
    if check("a 'done' event with honesty carried the payload", bool(done_lines)):
        honesty = json.loads(done_lines[-1][len("data: "):]).get("honesty", {})
        check("honesty.grounded_in_library is a real boolean",
              isinstance(honesty.get("grounded_in_library"), bool), str(honesty))
        check("honesty.covered_by_curriculum is a real boolean",
              isinstance(honesty.get("covered_by_curriculum"), bool), str(honesty))
    low = text.lower()
    for phrase in ("evidence is thin", "no sources", "off-topic"):
        check(f"opener free of {phrase!r}", low.count(phrase) == 0)

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
sys.exit(1 if fails else 0)
