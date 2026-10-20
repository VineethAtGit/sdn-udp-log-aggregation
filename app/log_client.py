#!/usr/bin/env python3
"""
log_client.py - UDP log generator (runs on h1..h4).

Sends timestamped logs of mixed severity to the log server at a fixed rate.
Each severity goes to the UDP port the contract assigns it, so the SDN
controller can classify traffic by destination port. Every message actually
sent is recorded in <out>/client_sent_<hostid>.csv so the server can compute
exact per-severity loss.

Examples:
  python3 app/log_client.py --host-id h1 --server-ip 10.0.0.5 --rate 50 --duration 60 --out results/run1
  python3 app/log_client.py --host-id h1 --server-ip 127.0.0.1 --rate 20 --duration 5   # localhost test
"""
import argparse
import csv
import os
import random
import signal
import socket
import sys
import time

from common import (DEFAULT_MIX, DEFAULT_OUT, DEFAULT_SERVER_IP, SENT_FIELDS,
                    SEVERITY_PORT, encode_message, parse_mix)

MESSAGES = {
    "CRITICAL": ["Disk failure on /dev/sda", "Database connection lost",
                 "Out of memory, service terminating", "Kernel panic detected"],
    "ERROR": ["Request handler raised exception", "Failed to write to cache",
              "Upstream service returned 500", "Authentication backend timeout"],
    "WARNING": ["Disk usage above 85%", "Slow query detected (2.3s)",
                "Retrying failed connection", "Certificate expires in 7 days"],
    "INFO": ["User login successful", "Scheduled job completed",
             "Configuration reloaded", "Health check passed"],
    "DEBUG": ["Entering function process_batch()", "Cache lookup key=user:42",
              "Payload size 1024 bytes", "Loop iteration 17 complete"],
}

_stop = False


def _handle_signal(*_):
    global _stop
    _stop = True


def main():
    ap = argparse.ArgumentParser(description="UDP log client")
    ap.add_argument("--host-id", required=True, help="h1..h4")
    ap.add_argument("--server-ip", default=DEFAULT_SERVER_IP)
    ap.add_argument("--rate", type=float, default=50, help="messages per second")
    ap.add_argument("--duration", type=float, default=60, help="seconds to send")
    ap.add_argument("--mix", default=DEFAULT_MIX,
                    help="severity percentages, e.g. CRITICAL:10,ERROR:10,...")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--seed", type=int, default=None,
                    help="random seed for reproducible severity sequences")
    ap.add_argument("--dscp", type=int, default=None,
                    help="optional DSCP value (0-63) to set on outgoing packets")
    args = ap.parse_args()

    if args.rate <= 0 or args.duration <= 0:
        print("error: --rate and --duration must be positive", file=sys.stderr)
        return 2
    try:
        mix = parse_mix(args.mix)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    severities = list(mix.keys())
    weights = [mix[s] for s in severities]
    rng = random.Random(args.seed)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.dscp is not None:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, (args.dscp & 0x3F) << 2)

    os.makedirs(args.out, exist_ok=True)
    sent_path = os.path.join(args.out, f"client_sent_{args.host_id}.csv")

    seq = 0
    sent_by_sev = {s: 0 for s in severities}
    errors = 0
    interval = 1.0 / args.rate

    with open(sent_path, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(SENT_FIELDS)

        print(f"[{args.host_id}] sending {args.rate}/s for {args.duration}s "
              f"to {args.server_ip}", flush=True)
        end = time.monotonic() + args.duration
        next_t = time.monotonic()

        while not _stop and time.monotonic() < end:
            severity = rng.choices(severities, weights)[0]
            message = rng.choice(MESSAGES[severity])
            ts = time.time()
            data = encode_message(seq, ts, args.host_id, severity, message)
            try:
                sock.sendto(data, (args.server_ip, SEVERITY_PORT[severity]))
            except OSError as e:
                # e.g. network unreachable: count it, keep going, don't burn a seq
                errors += 1
                if errors == 1 or errors % 100 == 0:
                    print(f"[{args.host_id}] send error #{errors}: {e}",
                          file=sys.stderr, flush=True)
            else:
                writer.writerow([args.host_id, seq, severity, f"{ts:.6f}"])
                sent_by_sev[severity] += 1
                seq += 1
                if seq % 200 == 0:
                    f.flush()

            # absolute-schedule pacing so the rate doesn't drift
            next_t += interval
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1.0:              # fell far behind: don't burst to catch up
                next_t = time.monotonic()

    sock.close()
    print(f"[{args.host_id}] done: sent {seq} messages "
          f"{sent_by_sev}, send errors {errors}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
