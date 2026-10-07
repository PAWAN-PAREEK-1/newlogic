"""Per-mode distribution targets: profit hit rate, volatility and win-range hit rates.

WHAT IT DOES
------------
Runs after the optimizer (Rust or Go) for every mode that has a "targets" block in
game_optimization.py (ConstructTargets). For each of the optimizer's candidate tables
(optimization_files/<mode>_0_<n>.csv) it finds the SMALLEST change to the payout
probabilities that meets every target, then publishes the candidate with the best
session score (the optimizer's own objective) as publish_files/lookUpTable_<mode>_0.csv.

"Smallest change" is the minimum relative-entropy (KL / I-) projection: of all
distributions meeting the constraints, the one closest to the optimizer's output.
It is the standard way to impose moment and probability constraints on a distribution
(Csiszar 1975; maximum-entropy / exponential-family tilting) and has a unique solution,
found exactly by Newton's method on the convex dual. The solution is
p(x) = q(x) * exp(-sum_k nu_k * a_k(x)): every payout is rescaled smoothly, no payout that
the optimizer used is dropped and none is added.

What stays EXACTLY as configured in `conditions` (hard constraints of the projection):
  * every criteria's probability (1/hr) and average win -> criteria RTPs and mode RTP
  * fixed-payout criteria (wincap, 0): untouched -> max-win rate, zero-win rate
What the targets control (as "1 in N" ranges, wins in multiples of the mode cost):
  * profit_hit_rate - rounds winning more than the cost
  * volatility      - standard deviation of win / cost
  * win_ranges      - rounds with lo <= win/cost < hi
  * rtp_ranges      - RTP paid by rounds with lo <= win/cost < hi, as an RTP range (min, max)
                      e.g. {"range": (40, 1e9), "rtp": (0, 0.8)} caps the tail liability above 40x
  * cvar            - {"alpha": 0.001, "max": 20000}: average payout of the top `alpha` share of
                      rounds, in BASE-BET multiples (not divided by cost) - the absolute risk limit.
                      Imposed exactly via CVaR <= L  <=>  some t has t + E[(win - t)+] / alpha <= L
                      (Rockafellar-Uryasev); the threshold t is searched automatically.

If the targets cannot all be met together with the conditions, nothing is published for
the mode and a TargetError explains which target is out of reach.

Usage (re-apply targets to the latest optimizer output without re-optimizing):
    python -m optimization_program.mode_targets --game expwilds --mode base,bonus
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from optimization_program.optimization_precheck import assign_books, parse_fences

TWO_POW_50 = 2.0**50


class TargetError(RuntimeError):
    """The mode's targets cannot be met together with its conditions."""


# --------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------


def _read_table(path: str) -> pd.DataFrame:
    return pd.read_csv(path, header=None, names=["id", "weight", "cents"], dtype={"id": np.int64, "weight": np.uint64})


def _read_candidate(path: str) -> pd.DataFrame:
    """id -> weight from an optimization_files/<mode>_0_<n>.csv (the part after 'Distribution')."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = lines.index("Distribution") + 1
    rows = [line.split(",") for line in lines[start:] if line.strip()]
    return pd.DataFrame({"id": [int(r[0]) for r in rows], "weight": [int(r[1]) for r in rows]})


def load_candidates(library: str, mode: str, ids: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Optimizer candidates as weight arrays aligned to `ids` (best-scored first)."""
    out = []
    opt_dir = os.path.join(library, "optimization_files")
    for n in range(1, 11):
        path = os.path.join(opt_dir, f"{mode}_0_{n}.csv")
        if os.path.exists(path):
            cand = _read_candidate(path).set_index("id")["weight"]
            out.append((f"{mode}_0_{n}.csv", cand.reindex(ids).fillna(0).to_numpy(dtype=float)))
    if not out:
        path = os.path.join(library, "publish_files", f"lookUpTable_{mode}_0.csv")
        table = _read_table(path).set_index("id")["weight"]
        out.append((os.path.basename(path), table.reindex(ids).fillna(0).to_numpy(dtype=float)))
    return out


@dataclass
class ModeData:
    ids: np.ndarray
    cents: np.ndarray
    x: np.ndarray  # payout per book (base-bet multiples)
    cost: float
    fences: list
    group: np.ndarray  # per book: index into the payout groups, -1 for fixed-payout criteria books
    gx: np.ndarray  # payout of each group
    gcount: np.ndarray  # books per group
    gfence: np.ndarray  # regular-fence index of each group
    fixed_mask: np.ndarray  # books in fixed-payout criteria
    regular: list  # regular fences in order
    m2m_bounds: list  # (min, max) mean-to-median per regular fence


def load_mode(library: str, mode: str) -> ModeData:
    with open(os.path.join(library, "configs", "math_config.json"), encoding="utf-8") as f:
        math_config = json.load(f)
    fences, cost, _ = parse_fences(math_config, mode)
    table = _read_table(os.path.join(library, "lookup_tables", f"lookUpTable_{mode}.csv"))
    ids, cents = table["id"].to_numpy(), table["cents"].to_numpy(dtype=np.int64)
    with open(os.path.join(library, "forces", f"force_record_{mode}.json"), encoding="utf-8") as f:
        forces = json.load(f)
    assign_books(fences, ids, cents, forces, mode)

    fence_json = {fj["name"]: fj for fj in next(f for f in math_config["fences"] if f["bet_mode"] == mode)["fences"]}
    group = np.full(len(ids), -1, dtype=np.int64)
    fixed_mask = np.zeros(len(ids), dtype=bool)
    gx, gcount, gfence, regular, m2m = [], [], [], [], []
    for fence in fences:
        if fence.win_type:
            fixed_mask[fence.book_idx] = True
            continue
        uniq, inverse, counts = np.unique(cents[fence.book_idx], return_inverse=True, return_counts=True)
        group[fence.book_idx] = len(gx) + inverse
        gx.extend(uniq / 100.0)
        gcount.extend(counts)
        gfence.extend([len(regular)] * len(uniq))
        fj = fence_json.get(fence.name, {})
        m2m.append((float(fj.get("min_mean_to_median") or 0.0), float(fj.get("max_mean_to_median") or 10.0)))
        regular.append(fence)
    return ModeData(ids, cents, cents / 100.0, cost, fences, group, np.asarray(gx), np.asarray(gcount, dtype=float),
                    np.asarray(gfence), fixed_mask, regular, m2m)


# --------------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------------


def metrics(x: np.ndarray, w: np.ndarray, cost: float, targets: dict | None = None) -> dict:
    """Distribution metrics of one mode (win amounts / cost, rates as '1 in N')."""
    p = w / w.sum()
    mean = float(p @ x)

    def one_in(prob):
        return float("inf") if prob <= 0 else 1.0 / prob

    out = {
        "rtp": mean / cost,
        "hit_rate": one_in(p[x > 0].sum()),
        "profit_hit_rate": one_in(p[x > cost].sum()),
        "volatility": float(np.sqrt(max(p @ (x - mean) ** 2, 0.0))) / cost,
        "max_win_rate": one_in(p[x == x.max()].sum()),
        "win_ranges": [],
    }
    for rng in (targets or {}).get("win_ranges", []):
        lo, hi = rng["range"]
        mask = (x >= lo * cost) & (x < hi * cost)
        out["win_ranges"].append({"range": [lo, hi], "one_in": one_in(p[mask].sum())})
    if (targets or {}).get("cvar"):
        out["cvar"] = cvar(x, p, targets["cvar"]["alpha"])
    out["rtp_ranges"] = []
    for rng in (targets or {}).get("rtp_ranges", []):
        lo, hi = rng["range"]
        mask = (x >= lo * cost) & (x < hi * cost)
        out["rtp_ranges"].append({"range": [lo, hi], "rtp": float(p[mask] @ x[mask]) / cost})
    return out


def cvar(x: np.ndarray, p: np.ndarray, alpha: float) -> float:
    """Average payout (base-bet multiples) of the top `alpha` probability share of rounds."""
    order = np.argsort(-x, kind="stable")
    xs, ps = x[order], p[order] / p.sum()
    cum = np.cumsum(ps)
    k = min(int(np.searchsorted(cum, alpha)), len(xs) - 1)
    take = ps[: k + 1].copy()
    take[-1] -= max(cum[k] - alpha, 0.0)
    return float(take @ xs[: k + 1]) / alpha


def session_score(x: np.ndarray, w: np.ndarray, cost: float, params: dict, seed: int = 0) -> float:
    """The optimizer's objective: weighted share of test_spins sessions ending at >= pmb_rtp x stake."""
    g = pd.Series(w).groupby(x).sum()
    vals, prob = g.index.to_numpy(), g.to_numpy() / g.sum()
    spins = [int(s) for s in params["test_spins"]]
    rng = np.random.default_rng(seed)
    u = rng.random((int(params["simulation_trials"]), max(spins)))
    idx = np.minimum(np.searchsorted(np.cumsum(prob), u, side="right"), len(vals) - 1)
    banks = np.cumsum(vals[idx], axis=1)
    return float(sum(wt * np.mean(banks[:, n - 1] / (n * cost) >= params["pmb_rtp"])
                     for n, wt in zip(spins, params["test_spins_weights"])))


# --------------------------------------------------------------------------------------------
# Minimum relative-entropy projection
# --------------------------------------------------------------------------------------------


def kl_projection(q: np.ndarray, A: np.ndarray, d: np.ndarray, max_iter: int = 300):
    """argmin_p sum p log(p/q) - p + q  s.t.  A p = d   (solution p = q * exp(-A^T nu)).

    Newton's method on the (smooth, convex) dual. Returns (p, nu, converged); nu has one
    multiplier per row of A, in the units of the original rows.
    """
    n_rows = len(d)
    scale = np.abs(A).max(axis=1)
    keep = scale > 0
    if np.any(np.abs(d[~keep]) > 1e-15):  # a target on payouts this mode never pays
        return q, np.zeros(n_rows), False
    A, d, scale = A[keep] / scale[keep, None], d[keep] / scale[keep], scale[keep]
    tol = 1e-10 * np.abs(d) + 1e-15

    def dual(nu):
        z = -(A.T @ nu)
        if z.max() > 700:
            return np.inf, None
        p = q * np.exp(z)
        return p.sum() + nu @ d, p

    def result(p, nu, ok):
        full = np.zeros(n_rows)
        full[keep] = nu / scale
        return p, full, ok

    nu = np.zeros(len(d))
    f, p = dual(nu)
    for _ in range(max_iter):
        grad = d - A @ p
        if np.all(np.abs(grad) <= tol):
            return result(p, nu, True)
        H = (A * p) @ A.T
        H += np.eye(len(d)) * (1e-14 * np.trace(H) + 1e-300)
        try:
            step = -np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            return result(p, nu, False)
        t = 1.0
        while t > 1e-12:
            f_new, p_new = dual(nu + t * step)
            if f_new <= f + 1e-4 * t * (grad @ step):
                break
            t *= 0.5
        else:
            return result(p, nu, False)
        nu, f, p = nu + t * step, f_new, p_new
    return result(p, nu, bool(np.all(np.abs(d - A @ p) <= tol)))


@dataclass
class Constraint:
    name: str
    row: np.ndarray  # coefficients over payout groups
    fixed: float  # contribution of the fixed-payout criteria (constant)
    lo: float
    hi: float

    def value(self, p):
        return float(self.row @ p) + self.fixed


def target_constraints(md: ModeData, w_fixed_prob: np.ndarray, mean: float, targets: dict) -> list[Constraint]:
    """Targets as linear constraints on the group probabilities (fixed criteria as constants)."""
    c, gx, x_fixed = md.cost, md.gx, md.x[md.fixed_mask]
    out = []

    def prob_range(one_in):
        n_lo, n_hi = one_in
        return 1.0 / n_hi, 1.0 / n_lo

    if targets.get("profit_hit_rate"):
        lo, hi = prob_range(targets["profit_hit_rate"])
        out.append(Constraint("profit_hit_rate", (gx > c).astype(float), float(w_fixed_prob[x_fixed > c].sum()), lo, hi))
    if targets.get("volatility"):
        v_lo, v_hi = targets["volatility"]
        out.append(Constraint("volatility", gx**2, float(w_fixed_prob @ x_fixed**2),
                              (v_lo * c) ** 2 + mean**2, (v_hi * c) ** 2 + mean**2))
    for rng in targets.get("win_ranges", []):
        a, b = rng["range"]
        lo, hi = prob_range(rng["one_in"])
        out.append(Constraint(f"win_range {a:g}-{b:g}x", ((gx >= a * c) & (gx < b * c)).astype(float),
                              float(w_fixed_prob[(x_fixed >= a * c) & (x_fixed < b * c)].sum()), lo, hi))
    if targets.get("cvar") and targets["cvar"].get("threshold") is not None:
        cv = targets["cvar"]
        t, alpha, limit = cv["threshold"], cv["alpha"], cv["max"]
        out.append(Constraint(f"cvar (t={t:g})", np.maximum(gx - t, 0.0),
                              float(w_fixed_prob @ np.maximum(x_fixed - t, 0.0)), 0.0, alpha * (limit - t)))
    for rng in targets.get("rtp_ranges", []):
        a, b = rng["range"]
        lo, hi = rng["rtp"]
        fixed = (x_fixed >= a * c) & (x_fixed < b * c)
        out.append(Constraint(f"rtp_range {a:g}-{b:g}x", gx / c * ((gx >= a * c) & (gx < b * c)),
                              float(w_fixed_prob[fixed] @ x_fixed[fixed]) / c, lo, hi))
    return out


def _hull_value(x: np.ndarray, a: np.ndarray, m: float, upper: bool) -> float:
    """max (upper) / min of sum a_j p_j over distributions p on payouts x with mean m.

    The optimum of this 2-constraint LP sits on two payouts bracketing m: the value of the
    upper (lower) convex hull of the points (x_j, a_j) at m.
    """
    order = np.argsort(x)
    x, a = x[order], a[order]
    if len(x) == 1 or m <= x[0]:
        return float(a[0])
    if m >= x[-1]:
        return float(a[-1])
    sign = 1.0 if upper else -1.0
    hull: list[int] = []
    for i in range(len(x)):
        while len(hull) >= 2:
            i0, i1 = hull[-2], hull[-1]
            cross = (x[i1] - x[i0]) * (sign * a[i] - sign * a[i0]) - (sign * a[i1] - sign * a[i0]) * (x[i] - x[i0])
            if cross >= 0:  # i1 is not on the upper envelope
                hull.pop()
            else:
                break
        hull.append(i)
    hx, ha = x[hull], a[hull]
    k = int(np.searchsorted(hx, m))
    if hx[k] == m:
        return float(ha[k])
    t = (m - hx[k - 1]) / (hx[k] - hx[k - 1])
    return float(ha[k - 1] + t * (ha[k] - ha[k - 1]))


def reachable(md: ModeData, q: np.ndarray, con: "Constraint") -> tuple[float, float]:
    """Exact range of a target's value over every distribution that keeps the conditions
    (each criteria's probability and average win) and the optimizer's payout support."""
    lo = hi = con.fixed
    for k in range(len(md.regular)):
        member = (md.gfence == k) & (q > 0)
        mass = float(q[md.gfence == k].sum())
        if mass <= 0:
            continue
        x, a = md.gx[member], con.row[member]
        m = float(q[member] @ x) / mass
        lo += mass * _hull_value(x, a, m, upper=False)
        hi += mass * _hull_value(x, a, m, upper=True)
    return lo, hi


def describe_reachable(md: ModeData, w: np.ndarray, targets: dict) -> list[str]:
    """Each target's reachable range (alone) under the mode's conditions, in target units."""
    prob = w / w.sum()
    q = np.bincount(md.group[~md.fixed_mask], weights=prob[~md.fixed_mask], minlength=len(md.gx))
    mean = float(prob @ md.x)
    out = []
    if targets.get("cvar") and targets["cvar"].get("threshold") is None:
        targets = {**targets, "cvar": {**targets["cvar"], "threshold": 0.8 * targets["cvar"]["max"]}}
    for con in target_constraints(md, prob[md.fixed_mask], mean, targets):
        lo, hi = reachable(md, q, con)
        if con.name == "volatility":
            to_std = lambda v: np.sqrt(max(v - mean**2, 0.0)) / md.cost  # noqa: E731
            out.append(f"volatility reachable {to_std(lo):.4g}..{to_std(hi):.4g}")
        elif con.name.startswith("cvar"):
            out.append(f"{con.name} reachable excess {lo:.4g}..{hi:.4g} (needs <= {con.hi:.4g})")
        elif con.name.startswith("rtp_range"):
            out.append(f"{con.name} reachable rtp {lo:.4f}..{hi:.4f}")
        else:
            one_in = lambda v: "never" if v <= 0 else f"1 in {1 / v:,.2f}"  # noqa: E731
            out.append(f"{con.name} reachable {one_in(hi)} (most often) .. {one_in(lo)} (least often)")
    return out


def adjust(md: ModeData, w: np.ndarray, targets: dict):
    """Closest distribution to candidate weights `w` that meets the targets.

    Returns (new per-book weights as float probabilities, total variation moved).
    Raises TargetError when no distribution meets the conditions and the targets together.
    """
    cv = targets.get("cvar")
    if cv and cv.get("threshold") is None:
        # CVaR <= L holds if ANY threshold t meets the linear excess constraint: try a grid of
        # thresholds below L and keep the solution that moves the least probability.
        best, last_err = None, None
        for frac in (0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5, 0.4, 0.3):
            try:
                res = adjust(md, w, {**targets, "cvar": {**cv, "threshold": frac * cv["max"]}})
            except TargetError as err:
                last_err = err
                continue
            if best is None or res[1] < best[1]:
                best = res
        if best is None:
            raise TargetError(f"cannot meet cvar <= {cv['max']:g} ({last_err})")
        return best
    prob = w / w.sum()
    q = np.bincount(md.group[~md.fixed_mask], weights=prob[~md.fixed_mask], minlength=len(md.gx))
    mean = float(prob @ md.x)
    fixed_prob = prob[md.fixed_mask]

    # hard: every regular criteria keeps its probability and average win
    eq_rows, eq_rhs = [], []
    for k in range(len(md.regular)):
        member = (md.gfence == k).astype(float)
        eq_rows += [member, member * md.gx]
        eq_rhs += [float(member @ q), float((member * md.gx) @ q)]

    cons = target_constraints(md, fixed_prob, mean, targets)
    active: dict[int, str] = {}  # constraint index -> "lo" | "hi"
    p = q
    for _ in range(4 * len(cons) + 10):
        rows, rhs = list(eq_rows), list(eq_rhs)
        order = list(active)
        for k in order:
            rows.append(cons[k].row)
            rhs.append((cons[k].lo if active[k] == "lo" else cons[k].hi) - cons[k].fixed)
        p, nu, ok = kl_projection(q, np.vstack(rows), np.asarray(rhs))
        if not ok:
            names = ", ".join(f"{cons[k].name} ({active[k]})" for k in order)
            raise TargetError(f"cannot meet {names} together with the criteria conditions")
        # drop an active bound whose multiplier says the solution wants to move inside the range
        mult = nu[len(eq_rows):]
        wrong = [i for i, k in enumerate(order) if cons[k].lo < cons[k].hi and
                 ((active[k] == "hi" and mult[i] < -1e-12) or (active[k] == "lo" and mult[i] > 1e-12))]
        if wrong:
            del active[order[max(wrong, key=lambda i: abs(mult[i]))]]
            continue
        # add the most violated target
        worst, worst_k, side = 0.0, None, None
        for k, con in enumerate(cons):
            if k in active:
                continue
            v = con.value(p)
            for bound, s in ((con.lo, "lo"), (con.hi, "hi")):
                gap = (bound - v) if s == "lo" else (v - bound)
                rel = gap / max(abs(bound), 1e-300)
                if rel > 1e-9 and rel > worst:
                    worst, worst_k, side = rel, k, s
        if worst_k is None:
            break
        active[worst_k] = side
    else:
        raise TargetError("target search did not settle (targets may be contradictory)")

    new_prob = prob.copy()
    reg = ~md.fixed_mask
    new_prob[reg] = (p / md.gcount)[md.group[reg]]
    moved = 0.5 * float(np.abs(p - q).sum())
    return new_prob, moved


def mean_to_median_warnings(md: ModeData, prob: np.ndarray) -> list[str]:
    out = []
    for k, fence in enumerate(md.regular):
        idx = fence.book_idx
        x, w = md.x[idx], prob[idx]
        order = np.argsort(x, kind="stable")
        cum = np.cumsum(w[order]) / w.sum()
        median = float(x[order][min(np.searchsorted(cum, 0.5), len(x) - 1)])
        mean = float(w @ x / w.sum())
        lo, hi = md.m2m_bounds[k]
        if median > 0 and not (lo < mean / median < hi):
            out.append(f"criteria '{fence.name}': mean/median {mean / median:.2f} is outside the optimizer's "
                       f"{lo:g}..{hi:g} rule after the adjustment")
    return out


# --------------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------------


def _fmt_rate(v):
    return "never" if v == float("inf") else f"1 in {v:,.2f}"


def _fmt_target(r):
    if r is None:
        return "-"
    lo, hi = r
    return f"1 in {lo:,.2f}" if lo == hi else f"1 in {lo:,.2f}..{hi:,.2f}"


def apply_mode_targets(library: str, mode: str, targets: dict, params: dict, verbose: bool = True) -> dict:
    """Adjust the optimizer output of `mode` to meet `targets` and publish the best candidate."""
    md = load_mode(library, mode)
    candidates = load_candidates(library, mode, md.ids)
    results, errors = [], []
    for name, w in candidates:
        try:
            prob, moved = adjust(md, w, targets)
        except TargetError as err:
            errors.append(f"{name}: {err}")
            continue
        results.append((session_score(md.x, prob, md.cost, params), name, w, prob, moved))
    if not results:
        ranges = "; ".join(describe_reachable(md, candidates[0][1], targets))
        raise TargetError(
            f"[{mode}] targets cannot be met by any optimizer candidate ({errors[0]}). With this mode's "
            f"conditions (hr/rtp per criteria): {ranges}. Pick targets inside these ranges (the closer to the "
            f"edge, the more extreme the curve), or change the criteria hr/rtp in `conditions`."
        )
    score, name, w, prob, moved = max(results, key=lambda r: r[0])

    weights = np.floor(prob * TWO_POW_50).astype(np.uint64)
    order = np.argsort(md.ids, kind="stable")
    publish = os.path.join(library, "publish_files", f"lookUpTable_{mode}_0.csv")
    with open(publish, "w", encoding="utf-8", newline="") as f:
        f.write("".join(f"{i},{wt},{c}\n" for i, wt, c in
                        zip(md.ids[order].tolist(), weights[order].tolist(), md.cents[order].tolist())))

    before = metrics(md.x, w, md.cost, targets)
    after = metrics(md.x, weights.astype(float), md.cost, targets)
    warnings = mean_to_median_warnings(md, prob)
    reach = describe_reachable(md, w, targets)
    report = {"mode": mode, "candidate": name, "score": score, "score_before": session_score(md.x, w, md.cost, params),
              "probability_moved": moved, "targets": targets, "before": before, "after": after,
              "reachable": reach, "warnings": warnings, "infeasible_candidates": errors}
    with open(os.path.join(library, "optimization_files", f"{mode}_targets_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=lambda v: None if v == float("inf") else v)

    if verbose:
        print(f"\nDistribution targets: {mode} (cost {md.cost:g}) - using {name}, "
              f"{moved * 100:.3f}% of probability moved, session score {report['score_before']:.4f} -> {score:.4f}")
        print(f"  {'metric':<22}{'target':>28}{'optimizer':>18}{'published':>18}")
        rows = [("rtp", "-", f"{before['rtp']:.6f}", f"{after['rtp']:.6f}"),
                ("hit rate (any win)", "set by conditions", _fmt_rate(before["hit_rate"]), _fmt_rate(after["hit_rate"])),
                ("max-win rate", "set by conditions", _fmt_rate(before["max_win_rate"]), _fmt_rate(after["max_win_rate"])),
                ("profit hit rate", _fmt_target(targets.get("profit_hit_rate")),
                 _fmt_rate(before["profit_hit_rate"]), _fmt_rate(after["profit_hit_rate"]))]
        vol = targets.get("volatility")
        rows.append(("volatility (std/cost)", "-" if vol is None else (f"{vol[0]:g}" if vol[0] == vol[1] else f"{vol[0]:g}..{vol[1]:g}"),
                     f"{before['volatility']:.4f}", f"{after['volatility']:.4f}"))
        for t, b, a in zip(targets.get("win_ranges", []), before["win_ranges"], after["win_ranges"]):
            lo, hi = t["range"]
            rows.append((f"win {lo:g}-{hi:g}x cost", _fmt_target(t["one_in"]), _fmt_rate(b["one_in"]), _fmt_rate(a["one_in"])))
        if targets.get("cvar"):
            cv = targets["cvar"]
            rows.append((f"cvar top {cv['alpha'] * 100:g}% (base)", f"<= {cv['max']:g}", f"{before['cvar']:,.1f}", f"{after['cvar']:,.1f}"))
        for t, b, a in zip(targets.get("rtp_ranges", []), before["rtp_ranges"], after["rtp_ranges"]):
            lo, hi = t["range"]
            rows.append((f"rtp {lo:g}-{hi:g}x cost", f"{t['rtp'][0]:g}..{t['rtp'][1]:g}", f"{b['rtp']:.4f}", f"{a['rtp']:.4f}"))
        for r in rows:
            print(f"  {r[0]:<22}{r[1]:>28}{r[2]:>18}{r[3]:>18}")
        print("  reachable with these conditions: " + "; ".join(reach))
        for msg in warnings:
            print(f"  WARNING {msg}")
        if errors:
            print(f"  ({len(errors)} of {len(candidates)} candidates could not meet the targets)")
    return report


EXPLORE_RANGES = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, 500),
                  (500, 1000), (1000, float("inf"))]


def explore(library: str, mode: str) -> None:
    """Print a mode's current metrics and what each metric could be under its conditions."""
    md = load_mode(library, mode)
    name, w = load_candidates(library, mode, md.ids)[0]
    probe = {"profit_hit_rate": (1.0, 1.0), "volatility": (1.0, 1.0),
             "win_ranges": [{"range": r, "one_in": (1.0, 1.0)} for r in EXPLORE_RANGES]}
    now = metrics(md.x, w, md.cost, probe)
    reach = describe_reachable(md, w, probe)
    print(f"\n{mode} (cost {md.cost:g}) - from {name}; wins in multiples of the cost")
    print(f"  rtp {now['rtp']:.4f} | hit rate {_fmt_rate(now['hit_rate'])} | max-win {_fmt_rate(now['max_win_rate'])}"
          f"   (set by conditions)")
    print(f"  {'metric':<22}{'now':>18}   reachable (each alone)")
    print(f"  {'profit hit rate':<22}{_fmt_rate(now['profit_hit_rate']):>18}   {reach[0].split('reachable ')[1]}")
    print(f"  {'volatility':<22}{now['volatility']:>18.4f}   {reach[1].split('reachable ')[1]}")
    for r, text in zip(now["win_ranges"], reach[2:]):
        lo, hi = r["range"]
        print(f"  {f'win {lo:g}-{hi:g}x':<22}{_fmt_rate(r['one_in']):>18}   {text.split('reachable ')[1]}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply per-mode distribution targets to the optimizer output")
    parser.add_argument("--game", required=True)
    parser.add_argument("--mode", required=True, help="comma-separated bet modes")
    parser.add_argument("--library", default=None, help="override games/<game>/library")
    parser.add_argument("--explore", action="store_true",
                        help="only print current values and reachable ranges (writes nothing)")
    args = parser.parse_args(argv)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)
    config = importlib.import_module(f"games.{args.game}.game_config").GameConfig()
    importlib.import_module(f"games.{args.game}.game_optimization").OptimizationSetup(config)
    library = args.library or os.path.join(root, "games", args.game, "library")
    failed = 0
    for mode in [m.strip() for m in args.mode.split(",")]:
        if args.explore:
            explore(library, mode)
            continue
        targets = config.opt_params[mode].get("targets")
        if not targets:
            print(f"{mode}: no targets block in game_optimization.py - nothing to do")
            continue
        try:
            apply_mode_targets(library, mode, targets, config.opt_params[mode]["parameters"])
        except TargetError as err:
            failed += 1
            print(f"ERROR {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
