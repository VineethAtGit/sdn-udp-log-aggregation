# sdn-udp-log-aggregation
This is our Computer Networks Project - Distributed Log Aggregation System

A distributed logging pipeline comparing standard baseline network forwarding against an SDN controller dynamically prioritizing critical logs during network congestion.

## Repository Layout
- `app/`: Log generator, collector server, and packet framing logic.
- `controller/`: Baseline and SDN priority controllers (`baseline_controller.py`, `sdn_controller.py`).
- `topology/`: Mininet network topologies and link configurations.
- `experiments/`: Traffic injection benchmarks and congestion scenarios.
- `results/`: Metric dumps, PCAP traces, and performance evaluation plots.
- `docs/`: Technical specifications, interface contracts (`docs/contract.md`), and architecture notes.

## Workflow & Contribution
- `main` branch holds verified, integrated code.
- Feature work and member deliverables are developed on designated branches and merged via Pull Requests.
- Refer to `docs/contract.md` for shared packet formats, port allocations, and interface boundaries.