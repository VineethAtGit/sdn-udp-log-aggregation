#!/usr/bin/env python3
"""
log_server.py - central UDP log server (runs on h5).

Listens on one UDP socket per port (5001, 5002, 5003), one thread per socket.
Every valid log is written to <out>/server_log.csv with the receive time and
one-way delay. On exit it writes <out>/summary.json with per-severity
received count, loss %, and delay statistics.

Loss is computed from the clients' <out>/client_sent_<hostid>.csv files, so
run the server and clients with the SAME --out directory (Mininet hosts share
the filesystem).

Examples:
  python3 app/log_server.py --out results/dynamic_heavy_1 --duration 70
  python3 app/log_server.py --out results/test --idle-timeout 10
  python3 app/log_server.py --out results/test --summarize-only
"""
import argparse
import csv
import glob
import json
import os
import signal
import socket
import sys
import threading
import time

from common import (DEFAULT_OUT, LOG_PORTS, SERVER_FIELDS, SEVERITIES,
                    decode_message)


class LogServer:
    def __init__(self, ports, out_dir, bind_ip="0.0.0.0"):
        self.ports = ports
        self.out_dir = out_dir
        self.bind_ip = bind_ip
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.malformed = 0
        self.received = 0
        self.last_rx = None                 # monotonic time of last valid log
        self.threads = []
        self.socks = []

        os.makedirs(out_dir, exist_ok=True)
        self.csv_file = open(os.path.join(out_dir, "server_log.csv"), "w",
                             newline="", buffering=1 << 16)
        self.writer = csv.writer(self.csv_file, lineterminator="\n")
        self.writer.writerow(SERVER_FIELDS)

    # -- socket setup -------------------------------------------------------
    def _make_socket(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:                                # big buffer: don't drop logs locally
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        except OSError:
            pass
        sock.bind((self.bind_ip, port))
        sock.settimeout(0.5)                # lets threads notice stop_event
        return sock

    # -- per-port receive loop ---------------------------------------------
    def _listen(self, sock, port):
        while not self.stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            recv_time = time.time()
            try:
                seq, send_time, host_id, severity, _msg = decode_message(data)
            except ValueError:
                with self.lock:
                    self.malformed += 1
                continue
            delay_ms = (recv_time - send_time) * 1000.0
            with self.lock:
                self.writer.writerow([f"{recv_time:.6f}", host_id, seq, severity,
                                      f"{send_time:.6f}", f"{delay_ms:.3f}"])
                self.received += 1
                self.last_rx = time.monotonic()

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        for port in self.ports:
            sock = self._make_socket(port)
            self.socks.append(sock)
            t = threading.Thread(target=self._listen, args=(sock, port), daemon=True)
            t.start()
            self.threads.append(t)
        print(f"[server] listening on UDP ports {self.ports}, writing to {self.out_dir}",
              flush=True)

    def stop(self):
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=2)
        for s in self.socks:
            s.close()
        with self.lock:
            self.csv_file.flush()
            self.csv_file.close()

    def run(self, duration=0, idle_timeout=0):
        """Block until duration elapsed, idle timeout hit, or signal received."""
        started = time.monotonic()
        while not self.stop_event.is_set():
            time.sleep(0.2)
            now = time.monotonic()
            if duration and now - started >= duration:
                print("[server] duration reached", flush=True)
                break
            if idle_timeout and self.last_rx is not None \
                    and now - self.last_rx >= idle_timeout:
                print("[server] idle timeout reached", flush=True)
                break


# --- summary ----------------------------------------------------------------
def _percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _load_sent(out_dir):
    """Return {severity: count} from client_sent_*.csv, or None if no files."""
    files = sorted(glob.glob(os.path.join(out_dir, "client_sent_*.csv")))
    if not files:
        return None
    seen = set()
    counts = {s: 0 for s in SEVERITIES}
    for path in files:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["client_id"], row["seq"])
                if key in seen:
                    continue
                seen.add(key)
                counts[row["severity"]] = counts.get(row["severity"], 0) + 1
    return counts


def summarize(out_dir, malformed=None):
    """Build summary.json content from server_log.csv + client_sent_*.csv."""
    delays = {s: [] for s in SEVERITIES}
    seen = set()
    path = os.path.join(out_dir, "server_log.csv")
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["client_id"], row["seq"])
                if key in seen:                 # UDP can duplicate; count once
                    continue
                seen.add(key)
                delays[row["severity"]].append(float(row["delay_ms"]))

    sent = _load_sent(out_dir)

    if malformed is None:                       # --summarize-only: reuse old value
        old = os.path.join(out_dir, "summary.json")
        malformed = 0
        if os.path.exists(old):
            try:
                with open(old) as f:
                    malformed = json.load(f).get("malformed", 0)
            except (OSError, ValueError):
                pass

    def stats(sent_n, vals):
        recv_n = len(vals)
        loss = None
        if sent_n:
            loss = round(max(0.0, (sent_n - recv_n) / sent_n * 100.0), 3)
        vs = sorted(vals)
        return {
            "sent": sent_n,
            "received": recv_n,
            "loss_pct": loss,
            "avg_delay_ms": round(sum(vs) / recv_n, 3) if recv_n else None,
            "p95_delay_ms": round(_percentile(vs, 95), 3) if recv_n else None,
            "max_delay_ms": round(vs[-1], 3) if recv_n else None,
        }

    per_sev = {s: stats(sent[s] if sent else None, delays[s]) for s in SEVERITIES}
    all_vals = [v for s in SEVERITIES for v in delays[s]]
    overall = stats(sum(sent.values()) if sent else None, all_vals)
    return {"malformed": malformed, "per_severity": per_sev, "overall": overall}


def print_summary(summary):
    print("\n=== Summary ===")
    print(f"{'severity':<10}{'sent':>8}{'recv':>8}{'loss%':>9}"
          f"{'avg ms':>10}{'p95 ms':>10}{'max ms':>10}")
    rows = list(summary["per_severity"].items()) + [("OVERALL", summary["overall"])]
    for name, s in rows:
        fmt = lambda v: "-" if v is None else v
        print(f"{name:<10}{fmt(s['sent']):>8}{s['received']:>8}{fmt(s['loss_pct']):>9}"
              f"{fmt(s['avg_delay_ms']):>10}{fmt(s['p95_delay_ms']):>10}"
              f"{fmt(s['max_delay_ms']):>10}")
    print(f"malformed datagrams discarded: {summary['malformed']}", flush=True)


def write_summary(out_dir, summary):
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)


def main():
    ap = argparse.ArgumentParser(description="UDP log aggregation server")
    ap.add_argument("--ports", default=",".join(map(str, LOG_PORTS)),
                    help="comma-separated UDP ports (default 5001,5002,5003)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--duration", type=float, default=0,
                    help="stop after N seconds (0 = until Ctrl+C / SIGTERM)")
    ap.add_argument("--idle-timeout", type=float, default=0,
                    help="stop N seconds after the last log arrives (0 = off)")
    ap.add_argument("--bind", default="0.0.0.0", help="address to bind")
    ap.add_argument("--summarize-only", action="store_true",
                    help="don't listen; just rebuild summary.json from CSVs in --out")
    args = ap.parse_args()

    if args.summarize_only:
        summary = summarize(args.out)
        write_summary(args.out, summary)
        print_summary(summary)
        return 0

    try:
        ports = [int(p) for p in args.ports.split(",")]
    except ValueError:
        print("error: --ports must be comma-separated integers", file=sys.stderr)
        return 2

    server = LogServer(ports, args.out, args.bind)
    signal.signal(signal.SIGINT, lambda *_: server.stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: server.stop_event.set())

    try:
        server.start()
    except OSError as e:
        print(f"error: could not bind sockets: {e}", file=sys.stderr)
        return 1

    server.run(args.duration, args.idle_timeout)
    server.stop()

    summary = summarize(args.out, malformed=server.malformed)
    write_summary(args.out, summary)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
