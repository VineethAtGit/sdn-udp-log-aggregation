#!/usr/bin/env python3
"""
plot_results.py - makes the figures for the report (saved to docs/figures/).

  sudo apt install -y python3-matplotlib      # once
  python3 experiments/plot_results.py                  # uses run 1 for timelines
  python3 experiments/plot_results.py --timeline-run 2

Figures:
  fig_loss.png            loss % per severity, baseline vs dynamic, per condition
  fig_delay.png           average delay per severity, baseline vs dynamic
  fig_burst_timeline.png  the congestion burst over time: utilization with controller
                          decisions, and per-second loss of HIGH vs LOW priority logs
"""
import argparse
import csv
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS = os.path.join(REPO, "results")
AGG = os.path.join(REPO, "docs", "results", "aggregate.csv")
FIGS = os.path.join(REPO, "docs", "figures")
SEVERITIES = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
CONDITIONS = ["none", "moderate", "heavy"]
HIGH = ("CRITICAL", "ERROR")
COLORS = {"baseline": "#8a8a8a", "dynamic": "#1f77b4"}


def num(x):
    return None if x in ("", "None", None) else float(x)


def load_aggregate():
    with open(AGG, newline="") as f:
        return list(csv.DictReader(f))


def grouped_bars(rows, value, err, ylabel, title, filename):
    present = [c for c in CONDITIONS if any(r["condition"] == c for r in rows)]
    fig, axes = plt.subplots(1, len(present), figsize=(5 * len(present), 4), squeeze=False)
    for ax, cond in zip(axes[0], present):
        width = 0.38
        for k, mode in enumerate(["baseline", "dynamic"]):
            ys, es = [], []
            for s in SEVERITIES:
                r = next((r for r in rows if r["condition"] == cond and r["mode"] == mode
                          and r["group"] == s), None)
                ys.append(num(r[value]) if r and num(r[value]) is not None else 0)
                es.append(num(r[err]) if r and num(r[err]) is not None else 0)
            xs = [i + (k - 0.5) * width for i in range(len(SEVERITIES))]
            ax.bar(xs, ys, width, yerr=es, capsize=3, label=mode, color=COLORS[mode])
        ax.set_xticks(range(len(SEVERITIES)))
        ax.set_xticklabels(SEVERITIES, rotation=30)
        ax.set_title(f"{cond} congestion")
        ax.set_ylabel(ylabel)
        ax.legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, filename), dpi=150)
    plt.close(fig)
    print("wrote", filename)


# ---- burst timeline ---------------------------------------------------------
def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def per_second_loss(run_dir, t0):
    sent = {}
    for p in glob.glob(os.path.join(run_dir, "client_sent_*.csv")):
        for r in read_csv(p):
            sent[(r["client_id"], r["seq"])] = (r["severity"], float(r["send_time"]))
    recv = {(r["client_id"], r["seq"]) for r in read_csv(os.path.join(run_dir, "server_log.csv"))}
    tot = {"high": {}, "low": {}}
    got = {"high": {}, "low": {}}
    for key, (sev, ts) in sent.items():
        cls = "high" if sev in HIGH else "low"
        sec = int(ts - t0)
        tot[cls][sec] = tot[cls].get(sec, 0) + 1
        if key in recv:
            got[cls][sec] = got[cls].get(sec, 0) + 1
    xs = sorted(set(tot["high"]) | set(tot["low"]))
    series = {}
    for cls in ("high", "low"):
        series[cls] = [(100.0 * (tot[cls].get(s, 0) - got[cls].get(s, 0)) / tot[cls][s])
                       if tot[cls].get(s) else None for s in xs]
    return xs, series


def burst_timeline(run_no):
    base = os.path.join(RESULTS, f"baseline_heavy_{run_no}")
    dyn = os.path.join(RESULTS, f"dynamic_heavy_{run_no}")
    if not (os.path.exists(os.path.join(base, "run_info.json"))
            and os.path.exists(os.path.join(dyn, "run_info.json"))):
        print("skipping timeline: need baseline_heavy_N and dynamic_heavy_N runs")
        return
    with open(os.path.join(dyn, "run_info.json")) as f:
        info = json.load(f)
    t0 = info["t_clients_start"]
    fs, fe = info["t_flood_start"] - t0, info["t_flood_end"] - t0

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    ctrl = read_csv(os.path.join(dyn, "controller_log.csv"))
    stats = [(float(r["time"]) - t0, float(r["utilization"])) for r in ctrl if r["event"] == "STATS"]
    axes[0].plot([x for x, _ in stats], [y for _, y in stats], color="#1f77b4")
    axes[0].axhline(80, ls="--", color="red", lw=0.8)
    axes[0].axhline(50, ls="--", color="green", lw=0.8)
    for r in ctrl:
        if r["event"] in ("CONGESTION_ON", "CONGESTION_OFF"):
            axes[0].axvline(float(r["time"]) - t0, color="black", lw=1.2)
            axes[0].text(float(r["time"]) - t0 + 0.3, 105, r["event"].replace("CONGESTION_", ""),
                         fontsize=8)
    axes[0].set_ylabel("bottleneck utilization %")
    axes[0].set_title("Dynamic run: link utilization and controller decisions (lines = ON/OFF)")

    for ax, d, name in ((axes[1], base, "Baseline"), (axes[2], dyn, "Dynamic")):
        xs, series = per_second_loss(d, t0)
        ax.plot(xs, series["high"], label="HIGH priority (CRITICAL+ERROR)", color="#d62728")
        ax.plot(xs, series["low"], label="LOW priority (WARNING/INFO/DEBUG)", color="#7f7f7f")
        ax.set_ylabel("loss % per second")
        ax.set_title(f"{name}: per-second loss of logs")
        ax.legend(loc="upper right", fontsize=8)
    for ax in axes:
        ax.axvspan(fs, fe, color="orange", alpha=0.15)
    axes[2].set_xlabel("seconds since clients started (orange = flood)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_burst_timeline.png"), dpi=150)
    plt.close(fig)
    print("wrote fig_burst_timeline.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline-run", type=int, default=1)
    args = ap.parse_args()
    os.makedirs(FIGS, exist_ok=True)
    if not os.path.exists(AGG):
        raise SystemExit("run experiments/aggregate.py first")
    rows = load_aggregate()
    grouped_bars(rows, "loss_pct_mean", "loss_pct_std", "loss %",
                 "Packet loss per severity: baseline vs dynamic SDN", "fig_loss.png")
    grouped_bars(rows, "avg_delay_ms_mean", "avg_delay_ms_std", "average delay (ms)",
                 "Delivery delay per severity: baseline vs dynamic SDN", "fig_delay.png")
    burst_timeline(args.timeline_run)


if __name__ == "__main__":
    main()
