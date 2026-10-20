"""
common.py - shared constants and helpers for the log aggregation app.
Everything here follows docs/contract.md (v1.0). If you change anything,
update the contract and tell the team.
"""

# --- Severities and ports (contract section 2) ------------------------------
SEVERITIES = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]

SEVERITY_PORT = {
    "CRITICAL": 5001,
    "ERROR": 5001,
    "WARNING": 5002,
    "INFO": 5002,
    "DEBUG": 5003,
}

LOG_PORTS = [5001, 5002, 5003]
CONGESTION_PORT = 5004          # used only by the iperf flood, never by the app

# --- Message format (contract section 1) ------------------------------------
MAX_DATAGRAM = 512              # bytes
DELIMITER = "|"

# --- Defaults (contract section 5) ------------------------------------------
DEFAULT_SERVER_IP = "10.0.0.5"
DEFAULT_MIX = "CRITICAL:10,ERROR:10,WARNING:20,INFO:40,DEBUG:20"
DEFAULT_OUT = "results/tmp"

# --- CSV columns (contract section 6) ---------------------------------------
SERVER_FIELDS = ["recv_time", "client_id", "seq", "severity", "send_time", "delay_ms"]
SENT_FIELDS = ["client_id", "seq", "severity", "send_time"]


def encode_message(seq, timestamp, host_id, severity, message):
    """Build one datagram: seq|timestamp|host_id|severity|message (UTF-8, <=512 B)."""
    message = str(message).replace("\r", " ").replace("\n", " ")
    text = DELIMITER.join(
        [str(seq), f"{timestamp:.6f}", host_id, severity, message]
    )
    data = text.encode("utf-8")
    if len(data) > MAX_DATAGRAM:
        # truncate the tail; 'ignore' drops a multi-byte char cut in half
        data = data[:MAX_DATAGRAM].decode("utf-8", "ignore").encode("utf-8")
    return data


def decode_message(data):
    """
    Parse a datagram. Returns (seq, timestamp, host_id, severity, message).
    Raises ValueError for anything malformed (wrong field count, bad numbers,
    unknown severity, bad UTF-8). The message field may itself contain '|',
    so we split on the first 4 delimiters only.
    """
    text = data.decode("utf-8")                      # UnicodeDecodeError is a ValueError
    parts = text.split(DELIMITER, 4)
    if len(parts) != 5:
        raise ValueError("wrong number of fields")
    seq_s, ts_s, host_id, severity, message = parts
    seq = int(seq_s)
    timestamp = float(ts_s)
    if seq < 0:
        raise ValueError("negative seq")
    if not host_id:
        raise ValueError("empty host_id")
    if severity not in SEVERITY_PORT:
        raise ValueError("unknown severity")
    return seq, timestamp, host_id, severity, message


def parse_mix(mix_string):
    """'CRITICAL:10,ERROR:10,...' -> {'CRITICAL': 10.0, ...}. Validates names."""
    mix = {}
    for item in mix_string.split(","):
        name, _, pct = item.partition(":")
        name = name.strip().upper()
        if name not in SEVERITY_PORT:
            raise ValueError(f"unknown severity in --mix: {name!r}")
        weight = float(pct)
        if weight < 0:
            raise ValueError("--mix weights must be >= 0")
        mix[name] = weight
    if sum(mix.values()) <= 0:
        raise ValueError("--mix weights must not all be zero")
    return mix
