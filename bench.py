# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Benchmark /play routing: Jev (Vercel AI Gateway) vs Laya (local, MLX) on the labeled golden set.

usage: bench.py [--runs N] [--laya MODEL ...] [--out results/DATE.json]
Laya needs `laya-mlx` (Apple Silicon): uv pip install "jevals[laya]"
"""
import argparse, datetime, importlib.metadata, json, platform, statistics, subprocess, sys, time

import dj_router as d

# expected route(s) · expected modifiers · modifiers to ignore (debatable)
GOLD = {
    "/play cold play": ({"artist"}, set(), set()),
    "/play yellow from cold play": ({"track"}, set(), set()),
    "/play gym music": ({"activity_mood"}, set(), set()),
    "/play some hip hop music": ({"genre"}, set(), set()),
    "/play algo para estudiar": ({"activity_mood"}, set(), set()),
    "/play ponme la de despacito": ({"track"}, set(), set()),
    "/play something like radiohead but happier": ({"similar"}, set(), set()),
    "/play musica de los 80s para una fiesta": ({"era", "activity_mood"}, set(), set()),
    "/play the new taylor swift album": ({"album"}, {"relative_ref"}, set()),
    "/play otra vez": ({"history"}, set(), set()),
    "/play that song that goes na na na": ({"unclear", "track"}, {"is_lyrics"}, {"relative_ref"}),
    "/play reggaeton viejo": ({"genre", "era"}, set(), {"relative_ref"}),
    "/play asdf": ({"unclear"}, set(), set()),
    "/play metallica one": ({"track", "artist"}, set(), set()),
    "/play nirvana del ultimo album": ({"album"}, {"relative_ref"}, set()),
    "/play la que dice 'is this the real life, is this just fantasy'": ({"track"}, {"is_lyrics"}, set()),
    "/play rock pero nada de metal ni nada muy pesado": ({"genre"}, {"has_exclusion"}, set()),
    "/play el soundtrack de interstellar": ({"album"}, set(), set()),
    "/play la versión acústica de wonderwall": ({"track"}, {"wants_version"}, set()),
    "/play la que sonó hace rato, la segunda": ({"history"}, set(), {"relative_ref"}),
    "/play un podcast de historia": ({"out_of_scope"}, set(), set()),
    "/play algo para dedicarle a mi novia que está triste 💔": ({"activity_mood"}, set(), set()),
    "/play bad bunny, luego karol g y después algo de feid": ({"artist"}, {"is_queue"}, set()),
    "/play smells like teen spirit pero cover de otra banda": ({"track", "similar"}, {"wants_version"}, set()),
    "/play metalica enter sandman plz": ({"track"}, set(), set()),
}
assert set(GOLD) == set(d.REQUESTS)


class Jev:
    name = "jev"

    def predict(self, state):
        a = d.call(state)["answers"]
        self.last_ms = d.LAST_ATTEMPT_MS  # without retry backoff
        return a


class Laya:
    def __init__(self, model):
        import laya_mlx

        self.model = model
        self.name = model.split("/")[-1]
        t0 = time.perf_counter()
        self._agent = laya_mlx.load(model)
        self.load_s = time.perf_counter() - t0

    def predict(self, state):
        return self._agent.predict(state, d.QUESTIONS)["answers"]


def score(backend, runs):
    rows, lat = [], []
    for q, (routes, mods, ignore) in GOLD.items():
        per_run = []
        for _ in range(runs):
            t0 = time.perf_counter()
            a = backend.predict(q)
            lat.append(backend.last_ms if hasattr(backend, "last_ms") else (time.perf_counter() - t0) * 1000)
            per_run.append(a)
        a = per_run[0]
        r = a["route"]
        mod_scores = {m: a[m]["noul"] for m in d.MODIFIERS}
        rows.append({
            "raw": per_run,
            "q": q,
            "route": r["choice"],
            "conf": r.get("confidence", 0),
            "route_ok": r["choice"] in routes,
            "route_flips": len({x["route"]["choice"] for x in per_run}) > 1,
            "mods": mod_scores,
            "gold_mods": mods,
            "ignore": ignore,
        })
    return rows, lat


def mod_accuracy(rows, threshold):
    ok = n = 0
    for row in rows:
        for m, p in row["mods"].items():
            if m in row["ignore"]:
                continue
            n += 1
            ok += (p >= threshold) == (m in row["gold_mods"])
    return ok / n


def mod_pr(rows, threshold):
    """Precision / recall on modifiers: accuracy is misleading, most modifier answers are 'no'."""
    tp = fp = fn = 0
    for row in rows:
        for m, p in row["mods"].items():
            if m in row["ignore"]:
                continue
            pred, gold = p >= threshold, m in row["gold_mods"]
            tp += pred and gold
            fp += pred and not gold
            fn += gold and not pred
    return (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)


def gap(rows):
    """Lowest true-positive vs highest false-positive modifier score: is there a clean threshold?"""
    pos = [p for r in rows for m, p in r["mods"].items() if m in r["gold_mods"]]
    neg = [p for r in rows for m, p in r["mods"].items() if m not in r["gold_mods"] and m not in r["ignore"]]
    return min(pos), max(neg)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="runs per request (>1 measures route stability)")
    ap.add_argument("--laya", nargs="*", default=["convaiinnovations/laya", "convaiinnovations/laya-multilingual"])
    ap.add_argument("--no-jev", action="store_true")
    ap.add_argument("--out", default=f"results/{datetime.date.today()}.json", help="raw results + environment, for BENCHMARK.md")
    args = ap.parse_args()

    from rich.console import Console
    from rich.table import Table

    c = Console()
    backends = [] if args.no_jev else [Jev()]
    for m in args.laya:
        with c.status(f"loading {m}…"):
            backends.append(Laya(m))

    results = {}
    for b in backends:
        with c.status(f"running {b.name} ({len(GOLD)} requests × {args.runs})…"):
            b.predict("/play warmup")  # exclude first-call cost (MLX compile, TLS handshake)
            results[b.name] = score(b, args.runs)

    # summary
    t = Table(title=f"/play routing benchmark · {len(GOLD)} labeled requests × {args.runs} run(s)", header_style="bold")
    t.add_column("metric")
    for b in backends:
        t.add_column(b.name, justify="right")
    rowsof = {k: v[0] for k, v in results.items()}
    latof = {k: v[1] for k, v in results.items()}
    t.add_row("route accuracy", *[f"{sum(r['route_ok'] for r in rowsof[b.name]) }/{len(GOLD)}" for b in backends])
    t.add_row("mean route confidence", *[f"{statistics.mean(r['conf'] for r in rowsof[b.name]):.2f}" for b in backends])
    base = mod_accuracy(next(iter(rowsof.values())), 2)  # threshold 2 = always "no"
    for th in (0.5, 0.8):
        t.add_row(f"modifier acc @{th} (always-no: {base:.0%})", *[f"{mod_accuracy(rowsof[b.name], th):.0%}" for b in backends])
        t.add_row(f"modifier precision / recall @{th}", *[
            (lambda p, r: f"{p:.0%} / {r:.0%}")(*mod_pr(rowsof[b.name], th)) for b in backends])
    t.add_row("modifier gap (min TP / max FP)", *[
        (lambda lo, hi: f"[{'green' if lo > hi else 'red'}]{lo:.2f} / {hi:.2f}[/]")(*gap(rowsof[b.name])) for b in backends])
    if args.runs > 1:
        t.add_row("route flips across runs", *[str(sum(r["route_flips"] for r in rowsof[b.name])) for b in backends])
    t.add_row("latency p50", *[f"{pct(latof[b.name], 50):.0f} ms" for b in backends])
    t.add_row("latency p95", *[f"{pct(latof[b.name], 95):.0f} ms" for b in backends])
    t.add_row("HTTP retries (overload)", *[str(d.RETRIES) if b.name == "jev" else "—" for b in backends])
    t.add_row("model load", *["—" if b.name == "jev" else f"{b.load_s:.1f} s" for b in backends])
    t.add_row("cost / 1M requests", *["~$36" if b.name == "jev" else "$0 (local)" for b in backends])
    c.print(t)

    # per-request routes
    t2 = Table(title="route per request (✗ = wrong)", header_style="bold", show_lines=False)
    t2.add_column("request", max_width=46, no_wrap=True)
    t2.add_column("expected", style="dim")
    for b in backends:
        t2.add_column(b.name)
    for i, (q, (routes, _, _)) in enumerate(GOLD.items()):
        cells = []
        for b in backends:
            r = rowsof[b.name][i]
            cells.append(f"{'' if r['route_ok'] else '[red]✗ '}{r['route']} {r['conf']:.2f}{'[/]' if not r['route_ok'] else ''}")
        t2.add_row(q.removeprefix("/play "), "|".join(sorted(routes)), *cells)
    c.print(t2)

    save(args, backends, rowsof, latof)


def save(args, backends, rowsof, latof):
    def ver(pkg):
        try:
            return importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            return None

    chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0) // 2**30
    out = {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "runs": args.runs,
        "requests": len(GOLD),
        "environment": {
            "machine": f"{chip}, {mem} GB",
            "os": platform.platform(),
            "python": platform.python_version(),
            "laya-mlx": ver("laya-mlx"),
            "jev_endpoint": d.URL,
        },
        "backends": {},
    }
    for b in backends:
        rows = rowsof[b.name]
        lo, hi = gap(rows)
        out["backends"][b.name] = {
            "model": getattr(b, "model", "typesafe-ai/jev"),
            "load_s": getattr(b, "load_s", None),
            "summary": {
                "route_accuracy": sum(r["route_ok"] for r in rows),
                "mean_route_confidence": round(statistics.mean(r["conf"] for r in rows), 3),
                "modifier_acc_05": round(mod_accuracy(rows, 0.5), 3),
                "modifier_acc_08": round(mod_accuracy(rows, 0.8), 3),
                "modifier_acc_always_no": round(mod_accuracy(rows, 2), 3),
                "modifier_precision_recall_05": [round(x, 3) for x in mod_pr(rows, 0.5)],
                "modifier_precision_recall_08": [round(x, 3) for x in mod_pr(rows, 0.8)],
                "http_retries": d.RETRIES if b.name == "jev" else None,
                "modifier_min_tp": lo,
                "modifier_max_fp": hi,
                "route_flips": sum(r["route_flips"] for r in rows),
                "latency_p50_ms": round(pct(latof[b.name], 50)),
                "latency_p95_ms": round(pct(latof[b.name], 95)),
            },
            "per_request": [
                {k: (sorted(v) if isinstance(v, set) else v) for k, v in r.items()} for r in rows
            ],
        }
    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"saved {args.out}")


if __name__ == "__main__":
    sys.exit(main())
