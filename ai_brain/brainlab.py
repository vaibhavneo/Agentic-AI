"""Brain Lab — the computed surface of the AI Brain.

Three things a student of this material actually needs to *run*, not read
about:

  1. symbolic algebra — differentiate a loss, expand a series, solve for a
     parameter;
  2. a matrix lab — eigenvalues, SVD, rank, conditioning, least squares, the
     linear algebra that every model is made of;
  3. gradient descent — watch an optimiser actually descend, and see what a
     learning rate too large does.

Everything here is computed by sympy or numpy. The model never produces these
numbers; it may only talk about them. That is the same contract the Quantum
Professor's solver holds, and it is what makes a cited [T] value trustworthy.

Run `python3 brainlab.py test` for the closed-form checks.
"""
from __future__ import annotations

import re

import numpy as np
import sympy as sp

# Only these names resolve. sympify() with an open namespace will happily
# evaluate attribute access and calls, so the namespace *is* the sandbox.
_ALLOWED = {n: getattr(sp, n) for n in (
    "sin cos tan asin acos atan sinh cosh tanh exp log sqrt Abs "
    "pi I oo Symbol Function Derivative Integral Sum factorial "
    "erf gamma besselj legendre hermite laguerre conjugate re im "
    "Piecewise Heaviside Min Max sign floor ceiling Matrix eye zeros ones "
    "diag transpose det trace".split())}
_ALLOWED.update({"ln": sp.log, "Infinity": sp.oo,
                 "True": sp.true, "False": sp.false,
                 # sigmoid and relu come up constantly in this domain and are
                 # not sympy builtins; giving them real definitions beats
                 # having them silently become free symbols.
                 "sigmoid": sp.Lambda(sp.Symbol("z"), 1 / (1 + sp.exp(-sp.Symbol("z")))),
                 "relu": sp.Lambda(sp.Symbol("z"), sp.Max(0, sp.Symbol("z")))})

# E is deliberately NOT bound to Euler's number: in this domain E is far more
# often an expectation or an error term than 2.718..., and binding it silently
# turned symbolic work into nonsense. Write exp(1) for the number.

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ns(text: str, extra: dict | None = None) -> dict:
    ns = dict(_ALLOWED)
    ns.update(extra or {})
    for name in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)):
        if name not in ns and _SAFE_NAME.match(name):
            ns[name] = sp.Symbol(name, real=True)
    return ns


def _parse(text: str, extra: dict | None = None):
    if len(text) > 2000:
        raise ValueError("expression too long")
    if "__" in text or "import" in text:
        raise ValueError("disallowed token")
    return sp.sympify(text, locals=_ns(text, extra))


def _out(expr):
    return {"result": str(expr), "latex": sp.latex(expr)}


# ── 1. symbolic algebra ───────────────────────────────────────────────────

OPERATIONS = ["simplify", "expand", "factor", "differentiate", "integrate",
              "solve", "limit", "series", "gradient", "hessian", "evaluate"]


def evaluate(expression: str, operation: str = "simplify", variable: str = "x",
             at=None, order: int = 6, subs: dict | None = None,
             variables: str = "") -> dict:
    """One symbolic operation on a typed expression."""
    try:
        sub_syms = {}
        for k, v in (subs or {}).items():
            if _SAFE_NAME.match(k):
                sub_syms[sp.Symbol(k, real=True)] = sp.sympify(v)
        e = _parse(expression)
        x = sp.Symbol(variable, real=True)
        # gradient/hessian need a variable list; default to the free symbols
        # in a stable order so the answer is reproducible.
        if variables.strip():
            vs = [sp.Symbol(v.strip(), real=True)
                  for v in variables.split(",") if v.strip()]
        else:
            vs = sorted(e.free_symbols, key=lambda s: s.name) if hasattr(e, "free_symbols") else [x]

        ops = {
            "simplify":      lambda: sp.simplify(e),
            "expand":        lambda: sp.expand(e),
            "factor":        lambda: sp.factor(e),
            "differentiate": lambda: sp.diff(e, x),
            "integrate":     lambda: sp.integrate(e, x),
            "solve":         lambda: sp.solve(sp.Eq(e, 0) if not isinstance(e, sp.Eq) else e, x),
            "limit":         lambda: sp.limit(e, x, sp.sympify(at if at is not None else 0)),
            "series":        lambda: sp.series(e, x, 0, int(order)),
            "gradient":      lambda: sp.Matrix([sp.diff(e, v) for v in vs]),
            "hessian":       lambda: sp.hessian(e, vs),
            "evaluate":      lambda: (e.subs(sub_syms) if sub_syms else e).evalf(),
        }
        if operation not in ops:
            return {"ok": False, "error": f"unknown operation {operation!r}",
                    "available": OPERATIONS}
        res = ops[operation]()
        if sub_syms and operation != "evaluate":
            res = sp.simplify(res.subs(sub_syms)) if hasattr(res, "subs") else res
        payload = {"ok": True, "operation": operation, "input": str(e),
                   "input_latex": sp.latex(e), **_out(res)}
        if operation in ("gradient", "hessian"):
            payload["variables"] = [v.name for v in vs]
        if isinstance(res, (list, tuple)):
            payload["solutions"] = [sp.latex(r) for r in res]
        try:
            if hasattr(res, "free_symbols") and not res.free_symbols:
                payload["numeric"] = float(res)
        except (TypeError, TypeError):
            pass
        return payload
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── 2. the matrix lab ─────────────────────────────────────────────────────

MATRIX_OPS = ["summary", "eigenvalues", "svd", "inverse", "pseudoinverse",
              "least_squares", "rank", "determinant", "condition", "power_iteration"]


def _parse_matrix(text: str) -> np.ndarray:
    """Accept '1,2; 3,4' or '[[1,2],[3,4]]' — both are how people write one."""
    text = text.strip()
    if not text:
        raise ValueError("empty matrix")
    if text.startswith("["):
        rows = sp.sympify(text, locals={})
        arr = np.array(sp.Matrix(rows).tolist(), dtype=float)
    else:
        rows = [r for r in re.split(r"[;\n]", text) if r.strip()]
        arr = np.array([[float(sp.sympify(c, locals={}))
                         for c in re.split(r"[,\s]+", r.strip()) if c]
                        for r in rows], dtype=float)
    if arr.ndim != 2 or arr.size == 0:
        raise ValueError("could not read a 2-D matrix")
    if arr.size > 10000:
        raise ValueError("matrix too large (max 10000 entries)")
    return arr


def matrix_lab(matrix: str, operation: str = "summary",
               rhs: str = "", n_iter: int = 50) -> dict:
    """Linear algebra on a typed matrix, computed by numpy."""
    try:
        A = _parse_matrix(matrix)
        m, n = A.shape
        out = {"ok": True, "operation": operation, "shape": [m, n],
               "matrix": A.round(6).tolist(),
               "matrix_latex": sp.latex(sp.Matrix(A.round(6).tolist()))}

        if operation in ("summary", "rank", "determinant", "condition"):
            s = np.linalg.svd(A, compute_uv=False)
            out["singular_values"] = [round(float(v), 6) for v in s]
            out["rank"] = int(np.linalg.matrix_rank(A))
            # cond = sigma_max/sigma_min, and infinite for a singular matrix —
            # reporting a huge finite number there would be a lie about a
            # matrix that simply has no inverse.
            out["condition_number"] = (float(s[0] / s[-1]) if s[-1] > 1e-15 else float("inf"))
            out["frobenius_norm"] = round(float(np.linalg.norm(A, "fro")), 6)
            if m == n:
                out["determinant"] = round(float(np.linalg.det(A)), 10)
                out["trace"] = round(float(np.trace(A)), 10)
                out["symmetric"] = bool(np.allclose(A, A.T))
            if not np.isfinite(out["condition_number"]):
                out["note"] = ("singular: smallest singular value is zero, so the "
                               "matrix has no inverse and the condition number is "
                               "infinite")
            return out

        if operation == "eigenvalues":
            if m != n:
                return {"ok": False, "error": "eigenvalues need a square matrix"}
            sym = np.allclose(A, A.T)
            w, v = (np.linalg.eigh(A) if sym else np.linalg.eig(A))
            out["symmetric"] = bool(sym)
            out["method"] = "eigh (symmetric)" if sym else "eig (general)"
            out["eigenvalues"] = [
                (round(float(x), 8) if np.isreal(x) else
                 {"re": round(float(np.real(x)), 8), "im": round(float(np.imag(x)), 8)})
                for x in w]
            out["eigenvectors"] = np.real_if_close(v).round(6).tolist()
            return out

        if operation == "svd":
            U, s, Vt = np.linalg.svd(A, full_matrices=False)
            out["U"] = U.round(6).tolist()
            out["singular_values"] = [round(float(x), 8) for x in s]
            out["Vt"] = Vt.round(6).tolist()
            tot = float(s.sum()) or 1.0
            out["energy_fraction"] = [round(float(x / tot), 6) for x in s]
            return out

        if operation in ("inverse", "pseudoinverse"):
            if operation == "inverse":
                if m != n:
                    return {"ok": False, "error": "inverse needs a square matrix"}
                if abs(np.linalg.det(A)) < 1e-14:
                    return {"ok": False,
                            "error": "matrix is singular — no inverse exists",
                            "hint": "use pseudoinverse for the least-squares sense"}
                M = np.linalg.inv(A)
            else:
                M = np.linalg.pinv(A)
            out["result"] = M.round(8).tolist()
            out["result_latex"] = sp.latex(sp.Matrix(M.round(6).tolist()))
            return out

        if operation == "least_squares":
            b = _parse_matrix(rhs).reshape(-1) if rhs.strip() else None
            if b is None:
                return {"ok": False, "error": "least_squares needs rhs (the b vector)"}
            if b.shape[0] != m:
                return {"ok": False,
                        "error": f"b has {b.shape[0]} entries but A has {m} rows"}
            x, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
            out["solution"] = [round(float(v), 8) for v in x]
            out["rank"] = int(rank)
            out["residual_norm"] = round(float(np.linalg.norm(A @ x - b)), 10)
            out["note"] = ("solved in the least-squares sense: x minimises "
                           "||Ax - b||, which is the normal equations without "
                           "ever forming A^T A")
            return out

        if operation == "power_iteration":
            if m != n:
                return {"ok": False, "error": "power iteration needs a square matrix"}
            v = np.ones(n) / np.sqrt(n)
            trace = []
            for _ in range(max(1, min(int(n_iter), 500))):
                w = A @ v
                nrm = np.linalg.norm(w)
                if nrm < 1e-300:
                    break
                v = w / nrm
                trace.append(round(float(v @ (A @ v)), 8))   # Rayleigh quotient
            out["rayleigh_trace"] = trace
            out["dominant_eigenvalue"] = trace[-1] if trace else None
            out["dominant_eigenvector"] = [round(float(x), 6) for x in v]
            out["note"] = ("power iteration converges to the eigenvector of largest "
                           "|eigenvalue|; the Rayleigh quotient trace shows how fast, "
                           "which is governed by the ratio of the top two eigenvalues")
            return out

        return {"ok": False, "error": f"unknown operation {operation!r}",
                "available": MATRIX_OPS}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── 3. gradient descent you can watch ─────────────────────────────────────

PRESET_SURFACES = {
    "quadratic-bowl": {
        "f": "x**2 + y**2", "start": "3, 4", "lr": 0.1,
        "label": "Isotropic bowl — the easy case",
        "note": "Condition number 1: every direction curves the same, so descent "
                "goes straight to the minimum at the origin."},
    "ill-conditioned": {
        "f": "x**2 + 20*y**2", "start": "10, 1", "lr": 0.04,
        "label": "Ill-conditioned valley",
        "note": "Curvatures differ 20:1. The step size is capped by the steep "
                "direction while progress is set by the shallow one — this is the "
                "zig-zag that momentum exists to fix."},
    "rosenbrock": {
        "f": "(1 - x)**2 + 100*(y - x**2)**2", "start": "-1.2, 1", "lr": 0.0005,
        "label": "Rosenbrock banana",
        "note": "The classic optimiser torture test: a curved narrow valley with "
                "the minimum at (1, 1)."},
    "saddle": {
        "f": "x**2 - y**2", "start": "0.001, 0.001", "lr": 0.05,
        "label": "Saddle point",
        "note": "Starting near the origin, descent crawls then escapes along the "
                "negative-curvature direction. Unbounded below — there is no minimum."},
    "logistic-loss": {
        "f": "log(1 + exp(-y*x))", "start": "0.5, 1", "lr": 0.5,
        "label": "Logistic loss in one margin variable",
        "note": "Convex and flat far out — the gradient vanishes as the margin grows, "
                "which is why logistic regression separates but never 'finishes'."},
}


def gradient_descent(function: str, start: str, lr: float = 0.1,
                     steps: int = 60, variables: str = "",
                     momentum: float = 0.0) -> dict:
    """Differentiate f symbolically, then descend numerically and keep the path.

    The gradient is exact — sympy differentiates it — so a wrong answer here is
    a wrong function, not a wrong derivative.
    """
    try:
        if not (0 < steps <= 2000):
            return {"ok": False, "error": "steps must be between 1 and 2000"}
        f = _parse(function)
        if variables.strip():
            vs = [sp.Symbol(v.strip(), real=True)
                  for v in variables.split(",") if v.strip()]
        else:
            vs = sorted(f.free_symbols, key=lambda s: s.name)
        if not vs:
            return {"ok": False, "error": "function has no variables to descend in"}
        if len(vs) > 4:
            return {"ok": False, "error": f"at most 4 variables (got {len(vs)})"}

        x0 = [float(sp.sympify(p, locals={}))
              for p in re.split(r"[,\s]+", start.strip()) if p]
        if len(x0) != len(vs):
            return {"ok": False,
                    "error": f"start has {len(x0)} values but f has {len(vs)} "
                             f"variables {[v.name for v in vs]}"}

        grad = [sp.diff(f, v) for v in vs]
        f_fn = sp.lambdify(vs, f, "numpy")
        g_fn = sp.lambdify(vs, grad, "numpy")

        x = np.array(x0, dtype=float)
        vel = np.zeros_like(x)
        path, losses, gnorms = [x.round(8).tolist()], [], []
        blew_up = False
        for _ in range(int(steps)):
            fx = float(f_fn(*x))
            g = np.array(g_fn(*x), dtype=float).reshape(-1)
            losses.append(round(fx, 10))
            gnorms.append(round(float(np.linalg.norm(g)), 10))
            if not np.all(np.isfinite(g)) or not np.isfinite(fx) or abs(fx) > 1e12:
                blew_up = True
                break
            vel = momentum * vel - lr * g
            x = x + vel
            path.append(x.round(8).tolist())
        final = float(f_fn(*x)) if np.all(np.isfinite(x)) else float("inf")

        # Divergence is a trend, not a magnitude. Flagging it only when the
        # loss passes 1e12 made the verdict depend on the step budget: with
        # lr=1.1 on x^2 the iterate grows 1.2x per step, so 80 steps tripped
        # the threshold and reported "diverged" while 50 steps reported "still
        # descending" — about the same, unmistakably divergent, run.
        rising = len(losses) > 1 and losses[-1] > losses[0]
        diverged = blew_up or rising

        out = {"ok": True, "function": str(f), "function_latex": sp.latex(f),
               "variables": [v.name for v in vs],
               "gradient": [str(g) for g in grad],
               "gradient_latex": [sp.latex(g) for g in grad],
               "learning_rate": lr, "momentum": momentum, "steps_run": len(losses),
               "start": x0, "final_point": [round(float(v), 8) for v in x],
               "final_value": round(final, 10) if np.isfinite(final) else None,
               "loss_trace": losses, "grad_norm_trace": gnorms, "path": path,
               "diverged": diverged}
        if diverged:
            out["note"] = ("diverged — the loss is higher than where it started"
                           + (" and overflowed" if blew_up else "") +
                           ". For a quadratic the step size must stay below 2/L, "
                           "where L is the largest curvature (the top Hessian "
                           "eigenvalue).")
        elif gnorms and gnorms[-1] < 1e-6:
            out["note"] = "converged: the gradient norm reached ~0"
        else:
            out["note"] = ("still descending after the step budget — the gradient "
                           "norm has not reached zero")
        return out
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ── self-test against answers known before it runs ────────────────────────

def self_test() -> int:
    fails = []

    def check(label, got, want, tol):
        ok = abs(got - want) <= tol
        print(f"  {'ok  ' if ok else 'FAIL'} {label:52s} {got:.6f} vs {want:.6f}")
        if not ok:
            fails.append(label)

    def yes(label, cond):
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            fails.append(label)

    print("[symbolic]")
    r = evaluate("x**2 - 5*x + 6", "solve")
    yes("solve x^2-5x+6 = {2,3}", r["ok"] and r["result"] == "[2, 3]")
    r = evaluate("log(1 + exp(-z))", "differentiate", variable="z")
    yes("d/dz softplus differentiates", r["ok"])
    r = evaluate("x**2 + 3*x*y + y**2", "gradient", variables="x,y")
    yes("gradient = [2x+3y, 3x+2y]",
        r["ok"] and "2*x + 3*y" in r["result"] and "3*x + 2*y" in r["result"])
    r = evaluate("x**2 + 3*x*y + y**2", "hessian", variables="x,y")
    yes("hessian = [[2,3],[3,2]]", r["ok"] and r["result"] == "Matrix([[2, 3], [3, 2]])")

    print("[matrix — closed forms]")
    # [[2,0],[0,3]] has eigenvalues 2 and 3, det 6, and is symmetric
    r = matrix_lab("2,0; 0,3", "eigenvalues")
    yes("diag(2,3) eigenvalues are 2 and 3",
        r["ok"] and sorted(r["eigenvalues"]) == [2.0, 3.0])
    r = matrix_lab("2,0; 0,3", "summary")
    check("det diag(2,3)", r["determinant"], 6.0, 1e-9)
    check("condition number diag(2,3)", r["condition_number"], 1.5, 1e-9)
    # A singular matrix must report infinite conditioning, not a big number
    r = matrix_lab("1,2; 2,4", "summary")
    yes("singular matrix -> rank 1", r["rank"] == 1)
    yes("singular matrix -> infinite condition number",
        r["condition_number"] == float("inf"))
    r = matrix_lab("1,2; 2,4", "inverse")
    yes("inverse of a singular matrix is refused", r["ok"] is False)
    # SVD of diag(3,4): singular values 4 and 3
    r = matrix_lab("3,0; 0,4", "svd")
    yes("svd diag(3,4) singular values [4,3]", r["singular_values"] == [4.0, 3.0])
    # Least squares on an exactly-solvable system: x + y = 3, x - y = 1 -> (2,1)
    r = matrix_lab("1,1; 1,-1", "least_squares", rhs="3; 1")
    yes("least squares exact solution (2,1)",
        r["ok"] and [round(v, 6) for v in r["solution"]] == [2.0, 1.0])
    check("residual is zero for a consistent system", r["residual_norm"], 0.0, 1e-9)
    # Power iteration on diag(5,1) must find 5
    r = matrix_lab("5,0; 0,1", "power_iteration", n_iter=60)
    check("power iteration finds dominant eigenvalue 5",
          r["dominant_eigenvalue"], 5.0, 1e-6)

    print("[gradient descent — analytic optima]")
    r = gradient_descent("x**2 + y**2", "3, 4", lr=0.1, steps=200)
    yes("bowl converges to the origin",
        r["ok"] and max(abs(v) for v in r["final_point"]) < 1e-6)
    yes("loss decreases monotonically on the bowl",
        all(b <= a + 1e-12 for a, b in zip(r["loss_trace"], r["loss_trace"][1:])))
    # 2/L rule: f = x^2 has L = 2, so lr > 1 must diverge and lr < 1 must not
    r = gradient_descent("x**2", "1", lr=1.1, steps=80)
    yes("lr above 2/L diverges as theory says", r["diverged"] is True)
    r = gradient_descent("x**2", "1", lr=0.9, steps=200)
    yes("lr below 2/L converges", r["diverged"] is False and abs(r["final_point"][0]) < 1e-6)
    # Rosenbrock minimum is exactly (1,1)
    r = gradient_descent("(1 - x)**2 + 100*(y - x**2)**2", "-1.2, 1",
                         lr=0.0005, steps=2000)
    yes("rosenbrock moves toward (1,1)",
        r["ok"] and r["final_value"] < 4.0)
    r = gradient_descent("x**2 + 20*y**2", "10, 1", lr=0.04, steps=300, momentum=0.9)
    yes("momentum helps the ill-conditioned valley", r["ok"] and r["final_value"] < 1e-3)
    yes("path returned for plotting", len(r["path"]) == r["steps_run"] + 1)

    print("[presets all evaluate]")
    for name, p in PRESET_SURFACES.items():
        r = gradient_descent(p["f"], p["start"], p["lr"], steps=50)
        yes(f"preset {name}", r["ok"])

    print("[sandbox]")
    for bad in ('__import__("os").system("id")', 'open("/etc/passwd")',
                '(1).__class__', 'True.__class__.__base__'):
        yes(f"blocks {bad[:36]}", not evaluate(bad).get("ok"))
    yes("matrix parser rejects code",
        not matrix_lab('__import__("os")', "summary").get("ok"))

    print("\nall checks passed" if not fails else f"\n{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    import json
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "test"
    if arg == "test":
        raise SystemExit(self_test())
    print(json.dumps(evaluate("x**2 + 3*x*y", "gradient", variables="x,y"), indent=1))
