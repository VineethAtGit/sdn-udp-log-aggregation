#!/usr/bin/env python3
"""
run_experiments.py - runs the whole experiment matrix automatically.

For every (mode, condition, run) it: starts a FRESH controller, builds the
Mininet network, runs the log server, 4 clients and (optionally) the UDP flood,
saves everything to results/<mode>_<condition>_<run>/, then tears it all down.

  sudo python3 experiments/run_experiments.py --runs 1 --conditions heavy   # smoke test (~3 min)
  sudo python3 experiments/run_experiments.py                               # full matrix (3 runs)

Conditions (flood rate toward the 10 Mbps bottleneck):
  none = no flood, moderate = 12 Mbps, heavy = 15 Mbps
Timeline of each run (default --duration 60): clients send for 60 s; the flood
starts at 25 % (15 s) and lasts 50 % (30 s) of the run, i.e. a congestion BURST.
Resumable: runs that already have summary.json are skipped (use --force to redo).
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "topology"))

FLOOD_MBPS = {"none": 0, "moderate": 12, "heavy": 15}
CLIENTS = ["h1", "h2", "h3", "h4"]
SERVER_IP = "10.0.0.5"
APP = os.path.join(REPO, "app")


def sh(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


def chown_tree(path):
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid is None:
        return
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chown(os.path.join(root, name), int(uid), int(gid))
            except OSError:
                pass
    try:
        os.chown(path, int(uid), int(gid))
    except OSError:
        pass


def start_controller(ryu, mode, run_id, results_dir, log_path):
    script = "baseline_controller.py" if mode == "baseline" else "sdn_controller.py"
    env = dict(os.environ, RUN_ID=run_id, RESULTS_DIR=results_dir)
    logf = open(log_path, "w")
    proc = subprocess.Popen([ryu, os.path.join(REPO, "controller", script)],
                            cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)
    deadline = time.time() + 25
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"controller exited early, see {log_path}")
        try:
            socket.create_connection(("127.0.0.1", 6653), timeout=1).close()
            return proc, logf
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("controller never opened port 6653")


def wait_for_switches(log_path, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with open(log_path) as f:
            text = f.read()
        if "switch connected: dpid=1" in text and "switch connected: dpid=2" in text:
            return
        time.sleep(0.5)
    raise RuntimeError("switches did not connect to the controller")


def run_one(args, mode, cond, n):
    from topo import build_network, clear_qos

    run_id = f"{mode}_{cond}_{n}"
    results_root = os.path.join(REPO, "results")
    out = os.path.join(results_root, run_id)
    if os.path.exists(os.path.join(out, "summary.json")) and not args.force:
        print(f"[skip] {run_id} already done")
        return
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)

    sh(["pkill", "-f", "ryu-manager"])
    sh(["mn", "-c"])
    clear_qos()

    ctrl = ctrl_log = net = None
    procs = []
    files = []
    try:
        ctrl_stdout = os.path.join(out, "controller_stdout.txt")
        ctrl, ctrl_log = start_controller(args.ryu, mode, run_id, results_root, ctrl_stdout)
        net = build_network()
        if hasattr(net, "waitConnected"):
            try:
                net.waitConnected(timeout=15)
            except Exception:
                pass
        wait_for_switches(ctrl_stdout)
        time.sleep(1)
        for name in CLIENTS + ["h6"]:               # warm-up: ARP + learning-switch flows
            net.get(name).cmd(f"ping -c 1 -W 2 {SERVER_IP}")

        h5, h6 = net.get("h5"), net.get("h6")
        rate = FLOOD_MBPS[cond]
        flood_start = int(args.duration * 0.25)
        flood_len = int(args.duration * 0.5)

        def logfile(name):
            f = open(os.path.join(out, name), "w")
            files.append(f)
            return f

        if rate > 0:
            procs.append(h5.popen(["iperf", "-s", "-u", "-p", "5004"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        server = h5.popen(["python3", os.path.join(APP, "log_server.py"), "--out", out,
                           "--idle-timeout", "8", "--duration", str(args.duration + 40)],
                          stdout=logfile("server_stdout.txt"), stderr=subprocess.STDOUT)
        time.sleep(1)

        t_start = time.time()
        clients = []
        for i, name in enumerate(CLIENTS, 1):
            clients.append(net.get(name).popen(
                ["python3", os.path.join(APP, "log_client.py"), "--host-id", name,
                 "--server-ip", SERVER_IP, "--rate", str(args.rate),
                 "--duration", str(args.duration), "--out", out,
                 "--seed", str(100 * n + i)],
                stdout=logfile(f"client_{name}_stdout.txt"), stderr=subprocess.STDOUT))
        flood = None
        if rate > 0:
            flood = h6.popen(["bash", "-c",
                              f"sleep {flood_start}; iperf -u -c {SERVER_IP} -p 5004 "
                              f"-b {rate}M -t {flood_len}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(flood)

        print(f"[run ] {run_id}: sending for {args.duration}s "
              f"(flood {rate} Mbps from t={flood_start}s for {flood_len}s)", flush=True)
        for c in clients:
            c.wait(timeout=args.duration + 30)
        if flood is not None:
            flood.wait(timeout=flood_len + 30)
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=10)
        if not os.path.exists(os.path.join(out, "summary.json")):
            sh(["python3", os.path.join(APP, "log_server.py"), "--out", out,
                "--summarize-only"])

        with open(os.path.join(out, "flows_s1.txt"), "w") as f:
            f.write(sh(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", "s1"]).stdout)
        with open(os.path.join(out, "queue_stats_s1.txt"), "w") as f:
            f.write(sh(["ovs-ofctl", "-O", "OpenFlow13", "queue-stats", "s1"]).stdout)

        info = {"run_id": run_id, "mode": mode, "condition": cond, "run": n,
                "duration_s": args.duration, "rate_per_client": args.rate,
                "flood_mbps": rate, "t_clients_start": t_start,
                "t_flood_start": t_start + flood_start if rate else None,
                "t_flood_end": t_start + flood_start + flood_len if rate else None}
        with open(os.path.join(out, "run_info.json"), "w") as f:
            json.dump(info, f, indent=2)
        print(f"[done] {run_id}", flush=True)
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if net is not None:
            try:
                net.stop()
            except Exception:
                pass
        if ctrl is not None:
            ctrl.terminate()
            try:
                ctrl.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ctrl.kill()
        for f in files + ([ctrl_log] if ctrl_log else []):
            try:
                f.close()
            except Exception:
                pass
        clear_qos()
        chown_tree(out)


def main():
    ap = argparse.ArgumentParser(description="Run the SDN log aggregation experiment matrix")
    ap.add_argument("--runs", type=int, default=3, help="repeats per mode and condition")
    ap.add_argument("--conditions", default="none,moderate,heavy")
    ap.add_argument("--modes", default="baseline,dynamic")
    ap.add_argument("--duration", type=int, default=60, help="seconds each client sends")
    ap.add_argument("--rate", type=float, default=50, help="messages/s per client")
    ap.add_argument("--force", action="store_true", help="redo runs that already exist")
    home = os.path.expanduser("~" + os.environ.get("SUDO_USER", ""))
    ap.add_argument("--ryu", default=os.path.join(home, "ryu-env", "bin", "ryu-manager"),
                    help="path to ryu-manager inside the venv")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("Run with sudo:  sudo python3 experiments/run_experiments.py")
    if not os.path.exists(args.ryu):
        sys.exit(f"ryu-manager not found at {args.ryu} (use --ryu /path/to/ryu-manager)")
    for c in args.conditions.split(","):
        if c not in FLOOD_MBPS:
            sys.exit(f"unknown condition {c!r}; choose from {list(FLOOD_MBPS)}")
    os.chdir(REPO)

    plan = [(m, c, n) for n in range(1, args.runs + 1)
            for c in args.conditions.split(",") for m in args.modes.split(",")]
    print(f"{len(plan)} runs planned, about {len(plan) * (args.duration + 30) // 60} minutes",
          flush=True)
    t0 = time.time()
    for i, (m, c, n) in enumerate(plan, 1):
        print(f"\n=== {i}/{len(plan)}: {m} / {c} / run {n} ===", flush=True)
        try:
            run_one(args, m, c, n)
        except Exception as e:
            print(f"[FAIL] {m}_{c}_{n}: {e}", flush=True)
    sh(["mn", "-c"])
    chown_tree(os.path.join(REPO, "results"))
    print(f"\nAll done in {(time.time() - t0) / 60:.1f} minutes. Next: python3 experiments/aggregate.py")


if __name__ == "__main__":
    main()
