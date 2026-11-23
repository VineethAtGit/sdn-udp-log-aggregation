#!/usr/bin/env python3
"""
log_server.py - central UDP log server (runs on h5).

Listens on one UDP socket per port (5001, 5002, 5003), one thread per socket.
Every valid log is written to <out>/server_log.csv with the receive time and
one-way delay and size. On exit it writes <out>/summary.json (per-severity loss %, delay
and throughput) and <out>/throughput.csv (delivered throughput per second per severity).

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
                    THROUGHPUT_FIELDS, decode_message)


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
                                      f"{send_time:.6f}", f"{delay_ms:.3f}", len(data)])
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
    """Return (counts, bytes, (t_min, t_max)) from client_sent_*.csv, or None if no files."""
    files = sorted(glob.glob(os.path.join(out_dir, "client_sent_*.csv")))
    if not files:
        return None
    seen = set()
    counts = {s: 0 for s in SEVERITIES}
    sizes = {s: 0 for s in SEVERITIES}
    times = []
    for path in files:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["client_id"], row["seq"])
                if key in seen:
                    continue
                seen.add(key)
                counts[row["severity"]] = counts.get(row["severity"], 0) + 1
                sizes[row["severity"]] = sizes.get(row["severity"], 0) + int(row.get("size_bytes") or 0)
                times.append(float(row["send_time"]))
    window = (min(times), max(times)) if times else None
    return counts, sizes, window


def _load_received(out_dir):
    """Return deduplicated received rows as dicts with float/int fields."""
    rows, seen = [], set()
    path = os.path.join(out_dir, "server_log.csv")
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["client_id"], row["seq"])
            if key in seen:                     # UDP can duplicate; count once
                continue
            seen.add(key)
            rows.append({"sev": row["severity"], "recv": float(row["recv_time"]),
                         "delay": float(row["delay_ms"]),
                         "size": int(row.get("size_bytes") or 0)})
    return rows


def summarize(out_dir, malformed=None):
    """Build summary.json content from server_log.csv + client_sent_*.csv."""
    received = _load_received(out_dir)
    delays = {s: [] for s in SEVERITIES}
    rbytes = {s: 0 for s in SEVERITIES}
    for r in received:
        delays[r["sev"]].append(r["delay"])
        rbytes[r["sev"]] += r["size"]

    loaded = _load_sent(out_dir)
    sent, sent_bytes, window = (loaded if loaded else (None, None, None))

    # throughput window: the clients' sending period (same window for offered and delivered)
    if window and window[1] - window[0] > 0:
        span = window[1] - window[0]
    elif received:
        span = max(r["recv"] for r in received) - min(r["recv"] for r in received)
    else:
        span = 0
    span = max(span, 1.0)

    if malformed is None:                       # --summarize-only: reuse old value
        old = os.path.join(out_dir, "summary.json")
        malformed = 0
        if os.path.exists(old):
            try:
                with open(old) as f:
                    malformed = json.load(f).get("malformed", 0)
            except (OSError, ValueError):
                pass

    def kbps(nbytes):
        return round(nbytes * 8.0 / 1000.0 / span, 2)

    def stats(sent_n, sent_b, vals, recv_b):
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
            "offered_kbps": kbps(sent_b) if sent_b else None,
            "goodput_kbps": kbps(recv_b),
        }

    per_sev = {s: stats(sent[s] if sent else None, sent_bytes[s] if sent else None,
                        delays[s], rbytes[s]) for s in SEVERITIES}
    all_vals = [v for s in SEVERITIES for v in delays[s]]
    overall = stats(sum(sent.values()) if sent else None,
                    sum(sent_bytes.values()) if sent else None,
                    all_vals, sum(rbytes.values()))
    return {"malformed": malformed, "throughput_window_s": round(span, 2),
            "per_severity": per_sev, "overall": overall}


def write_throughput(out_dir):
    """Per-second delivered throughput per severity -> throughput.csv (1 s buckets)."""
    buckets = {}
    for r in _load_received(out_dir):
        key = (int(r["recv"]), r["sev"])
        n, b = buckets.get(key, (0, 0))
        buckets[key] = (n + 1, b + r["size"])
    with open(os.path.join(out_dir, "throughput.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(THROUGHPUT_FIELDS)
        for (sec, sev) in sorted(buckets):
            n, b = buckets[(sec, sev)]
            w.writerow([sec, sev, n, b, round(b * 8.0 / 1000.0, 2)])


def print_summary(summary):
    print("\n=== Summary ===")
    print(f"{'severity':<10}{'sent':>7}{'recv':>7}{'loss%':>8}{'avg ms':>9}{'p95 ms':>9}"
          f"{'max ms':>9}{'offer kbps':>12}{'good kbps':>11}")
    rows = list(summary["per_severity"].items()) + [("OVERALL", summary["overall"])]
    fmt = lambda v: "-" if v is None else v
    for name, s in rows:
        print(f"{name:<10}{fmt(s['sent']):>7}{s['received']:>7}{fmt(s['loss_pct']):>8}"
              f"{fmt(s['avg_delay_ms']):>9}{fmt(s['p95_delay_ms']):>9}{fmt(s['max_delay_ms']):>9}"
              f"{fmt(s.get('offered_kbps')):>12}{fmt(s.get('goodput_kbps')):>11}")
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
        write_throughput(args.out)
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
    write_throughput(args.out)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
