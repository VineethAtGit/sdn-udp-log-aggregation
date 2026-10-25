#!/usr/bin/env python3
"""
aggregate.py - combine all runs into tables (mean and standard deviation).

  python3 experiments/aggregate.py

Reads results/<mode>_<condition>_<run>/summary.json and writes
  docs/results/all_runs.csv   one row per run and severity
  docs/results/aggregate.csv  mean/std per mode, condition and severity (plus HIGH/LOW classes)
and prints a markdown table you can paste into the report.
"""
import csv
import json
import os
import re
import statistics

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS = os.path.join(REPO, "results")
OUT = os.path.join(REPO, "docs", "results")
RUN_RE = re.compile(r"^(baseline|dynamic)_(none|moderate|heavy)_(\d+)$")
SEVERITIES = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
HIGH = ("CRITICAL", "ERROR")
CONDITIONS = ["none", "moderate", "heavy"]
MODES = ["baseline", "dynamic"]


def mean_std(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    return statistics.mean(vals), (statistics.pstdev(vals) if len(vals) > 1 else 0.0)


def load_runs():
    runs = []
    for name in sorted(os.listdir(RESULTS)):
        m = RUN_RE.match(name)
        path = os.path.join(RESULTS, name, "summary.json")
        if not m or not os.path.exists(path):
            continue
        with open(path) as f:
            summary = json.load(f)
        runs.append({"mode": m.group(1), "cond": m.group(2), "run": int(m.group(3)),
                     "per_sev": summary["per_severity"]})
    return runs


def class_stats(per_sev, members):
    sent = sum(per_sev[s]["sent"] or 0 for s in members)
    recv = sum(per_sev[s]["received"] or 0 for s in members)
    loss = (sent - recv) / sent * 100.0 if sent else None
    weights = [(per_sev[s]["avg_delay_ms"], per_sev[s]["received"]) for s in members
               if per_sev[s]["avg_delay_ms"] is not None and per_sev[s]["received"]]
    tot = sum(w for _, w in weights)
    delay = sum(d * w for d, w in weights) / tot if tot else None
    return {"sent": sent, "received": recv, "loss_pct": loss, "avg_delay_ms": delay}


def main():
    os.makedirs(OUT, exist_ok=True)
    runs = load_runs()
    if not runs:
        raise SystemExit("no completed runs found in results/")

    with open(os.path.join(OUT, "all_runs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "condition", "run", "severity", "sent", "received",
                    "loss_pct", "avg_delay_ms", "p95_delay_ms", "max_delay_ms"])
        for r in runs:
            for s in SEVERITIES:
                d = r["per_sev"][s]
                w.writerow([r["mode"], r["cond"], r["run"], s, d["sent"], d["received"],
                            d["loss_pct"], d["avg_delay_ms"], d["p95_delay_ms"], d["max_delay_ms"]])

    rows = []
    for cond in CONDITIONS:
        for mode in MODES:
            sel = [r for r in runs if r["cond"] == cond and r["mode"] == mode]
            if not sel:
                continue
            groups = [(s, (s,)) for s in SEVERITIES] + [("HIGH(CRIT+ERR)", HIGH),
                      ("LOW(WARN+INFO+DEBUG)", tuple(x for x in SEVERITIES if x not in HIGH))]
            for label, members in groups:
                stats = [class_stats(r["per_sev"], members) for r in sel]
                lm, ls = mean_std([x["loss_pct"] for x in stats])
                dm, ds = mean_std([x["avg_delay_ms"] for x in stats])
                rows.append({"condition": cond, "mode": mode, "group": label, "runs": len(sel),
                             "loss_mean": lm, "loss_std": ls, "delay_mean": dm, "delay_std": ds})

    with open(os.path.join(OUT, "aggregate.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["condition", "mode", "group", "runs", "loss_pct_mean", "loss_pct_std",
                    "avg_delay_ms_mean", "avg_delay_ms_std"])
        for r in rows:
            w.writerow([r["condition"], r["mode"], r["group"], r["runs"],
                        None if r["loss_mean"] is None else round(r["loss_mean"], 3),
                        None if r["loss_std"] is None else round(r["loss_std"], 3),
                        None if r["delay_mean"] is None else round(r["delay_mean"], 3),
                        None if r["delay_std"] is None else round(r["delay_std"], 3)])

    fmt = lambda m, s: "-" if m is None else f"{m:.1f} ± {s:.1f}"
    print("\n| Condition | Group | Baseline loss % | Dynamic loss % | Baseline delay ms | Dynamic delay ms |")
    print("|---|---|---|---|---|---|")
    for cond in CONDITIONS:
        for label in SEVERITIES + ["HIGH(CRITICAL+ERROR)".replace("CRITICAL+ERROR", "CRIT+ERR"),
                                   "LOW(WARN+INFO+DEBUG)"]:
            b = next((r for r in rows if r["condition"] == cond and r["mode"] == "baseline"
                      and r["group"] == label), None)
            d = next((r for r in rows if r["condition"] == cond and r["mode"] == "dynamic"
                      and r["group"] == label), None)
            if not b and not d:
                continue
            print(f"| {cond} | {label} | "
                  f"{fmt(b['loss_mean'], b['loss_std']) if b else '-'} | "
                  f"{fmt(d['loss_mean'], d['loss_std']) if d else '-'} | "
                  f"{fmt(b['delay_mean'], b['delay_std']) if b else '-'} | "
                  f"{fmt(d['delay_mean'], d['delay_std']) if d else '-'} |")
    print(f"\nWrote {OUT}/all_runs.csv and aggregate.csv ({len(runs)} runs)")


if __name__ == "__main__":
    main()
