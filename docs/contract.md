# Interface Contract & System Specification

## 1. Overview & Ownership
This document specifies the shared interfaces, boundaries, and technical contracts across modules in the **SDN-Based UDP Log Aggregation System**.

| Module Directory | Primary Responsibility | Key Files |
|---|---|---|
| `app/` | Client log generator, collector server, serialization/packet framing | Log generator, log receiver, protocol parser |
| `controller/` | OpenFlow / SDN flow controller rules and dynamic QoS | `baseline_controller.py`, `sdn_controller.py` |
| `topology/` | Mininet topology scripts and link bandwidth limits | Network definitions, topology configurations |
| `experiments/` | Traffic injection benchmarks and congestion tests | Automated test scripts |
| `results/` | Output logs, PCAP traces, and throughput/drop plots | Raw metrics and graphs |
| `docs/` | System documentation and technical specs | `contract.md` |

---

## 2. Network & Transport Contract
- **Transport Protocol:** UDP
- **Default Collector Port:** `9999` (unless overridden via command-line arguments)
- **Default Host Addressing:** Standard Mininet IP subnet (e.g., `10.0.0.0/24`)

---

## 3. Log Message & Packet Framing Specification
Log messages transmitted over UDP must follow the standardized packet structure agreed upon by `app/` and inspected by `controller/`:

- **Header Format:** Fixed-size or delimited header containing:
  - `Severity Level`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (or corresponding integer codes `0` to `4`)
  - `Source Node ID`: Identifier for the client producing logs (e.g., `h1`, `h2`)
  - `Sequence Number`: Integer tracking sent packets to detect packet drop and reordering
  - `Timestamp`: Epoch millisecond timestamp of log generation
- **Payload:** Raw UTF-8 log body text.

---

## 4. SDN Controller Behavior & QoS Policy
- **Baseline Controller (`baseline_controller.py`):**
  - Acts as a standard L2/L3 learning switch.
  - Treats all UDP traffic uniformly (Best Effort FIFO) without inspect-and-prioritize rules.
- **SDN Priority Controller (`sdn_controller.py`):**
  - Monitors link congestion.
  - Dynamically installs flow rules or maps DSCP/ToS/port priority queues to prioritize `ERROR` and `CRITICAL` packets over `DEBUG` and `INFO` under congested link conditions.

---

## 5. Development & Git Rules
- Do not commit directly to `main` after initial initialization.
- Every collaborator works on their designated branch (e.g., `member-b`, `member-c`) and opens a Pull Request against `main`.
- All temporary artifacts, `.pcap` files, and virtual environments must remain untracked via `.gitignore`.