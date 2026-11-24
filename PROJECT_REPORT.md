# SDN Based Distributed Log Aggregation System

## Project Report

**Course:** SDN-Socket Programming — Jackfruit Mini Project  
**Repository:** [VineethAtGit/sdn-udp-log-aggregation](https://github.com/VineethAtGit/sdn-udp-log-aggregation)

## Abstract

This project implements a distributed log aggregation system over a software-defined network. Multiple Mininet hosts generate timestamped application log messages and send them as UDP datagrams to a central server. A Ryu controller monitors a constrained Open vSwitch link and, when congestion persists, directs critical and error traffic to a higher-priority queue. A baseline controller provides a comparison without dynamic prioritization. Experiments record delivery loss and latency by severity to evaluate how prioritization changes the service received by important logs under load.

## 1. Introduction

Applications distributed across multiple hosts produce logs that are useful for monitoring and fault diagnosis. When these logs share a congested network link, critical events can be delayed or lost alongside routine messages. The project explores whether SDN control can improve delivery of important logs while maintaining a simple UDP-based logging pipeline.

The test environment is an emulated topology built with Mininet and Open vSwitch. Ryu communicates with the switches using OpenFlow 1.3. This makes it possible to generate reproducible traffic, change queue assignment at runtime, and compare the dynamic strategy against a static baseline.

## 2. Objectives

- Build a multi-client UDP logging application with a central receiving server.
- Represent severity in a network-visible field so that switches can classify log traffic.
- Monitor link use and react to sustained congestion through an SDN controller.
- Protect CRITICAL and ERROR messages using a higher-priority output queue.
- Measure packet loss and delivery delay per severity and compare dynamic and baseline modes.

## 3. System Architecture

The topology contains clients `h1` through `h4`, a central log server `h5`, and a congestion generator `h6`. The traffic crosses two Open vSwitches, `s1` and `s2`; the inter-switch path includes a 10 Mbps bottleneck. A Ryu controller manages the switches over OpenFlow 1.3.

```text
h1..h4 (log clients) ---- s1 ===== s2 ---- h5 (log server)
                           10 Mbps bottleneck
h6 (traffic generator) --/
                              ^
                       Ryu controller
```

The application sends UDP datagrams to severity-specific destination ports: 5001 for CRITICAL/ERROR, 5002 for WARNING/INFO, and 5003 for DEBUG. This allows the controller and switch rules to classify traffic without inspecting application payloads.

## 4. Design and Operation

### Logging application

Each client emits timestamped, sequenced messages at a configured rate and records the messages sent. The server receives datagrams, records receive time and calculated delay, and produces a per-severity summary. The sent and received records together support loss calculation.

### SDN congestion control

The dynamic Ryu controller polls the bottleneck port statistics every second. When utilization exceeds 80% for three consecutive intervals, it installs rules that send port 5001 traffic to the high-priority queue and other log traffic to the low-priority queue. When utilization remains below 50% for three intervals, the prioritization rules are removed. The baseline controller uses the same network setup without dynamic severity prioritization.

The bottleneck uses Open vSwitch HTB QoS with a 10 Mbps link rate, separate high- and low-priority queues, a default queue, and a 100-packet buffer. Queueing affects which traffic receives available capacity; it does not increase the link's total capacity.

### Experiment procedure

The automated runner starts a fresh controller and network for each trial. It varies offered load across no congestion, a moderate 12 Mbps flood, and a heavy 15 Mbps flood; each condition runs in baseline and dynamic modes with three repetitions. Runs last 60 seconds, with the congestion burst from 15 to 45 seconds. Aggregation and plotting scripts then produce summary tables and figures.

## 5. Implementation Components

| Component | Responsibility |
|---|---|
| `app/log_client.py` | Generates timestamped, severity-tagged UDP logs and sent-message records. |
| `app/log_server.py` | Receives messages, records delay and delivery data, and writes summaries. |
| `app/common.py` | Shared message and severity definitions used by the applications. |
| `controller/sdn_controller.py` | Monitors port utilization and dynamically applies queue priorities. |
| `controller/baseline_controller.py` | Provides the non-prioritizing comparison controller. |
| `topology/topo.py` | Builds the Mininet topology and configures the bottleneck and queues. |
| `experiments/run_experiments.py` | Executes experiment conditions and repeats. |
| `experiments/aggregate.py` | Aggregates run output into comparison tables. |
| `experiments/plot_results.py` | Generates experiment figures. |

## 6. Requirements and Reproduction

The documented environment is Ubuntu 20.04 with Python 3.8, Mininet, Open vSwitch, iperf, Ryu 4.34, `eventlet==0.30.2`, and matplotlib for plots. Mininet and Open vSwitch require Linux; macOS users can run the setup in a Linux virtual machine. The Ryu environment should use a compatible virtual environment and the pinned eventlet version.

Before running experiments, verify Mininet connectivity with `sudo mn --test pingall`. The automated workflow is:

```sh
sudo python3 experiments/run_experiments.py --runs 1 --conditions heavy
sudo python3 experiments/run_experiments.py
python3 experiments/aggregate.py
python3 experiments/plot_results.py
```

The first command is a shorter smoke run. The complete matrix takes approximately 30 minutes according to the repository documentation. A manual demo is also supported by starting one of the controllers, launching `sudo python3 topology/topo.py`, then running the server, clients, and optional iperf flood from the Mininet prompt.

## 7. Measurements and Results

Each run records server-side received messages, client-side sent messages, a JSON summary, controller decisions, and flow counters. The summary reports sent and received counts, loss percentage, and average, 95th-percentile, and maximum delay by severity. The controller log records periodic utilization and congestion actions.

The repository's documented findings are:

- In the absence of congestion, both modes deliver all messages with sub-millisecond delay, and the controller remains idle.
- Under congestion, the baseline shares loss and delay similarly across severities.
- With dynamic prioritization, CRITICAL and ERROR logs have substantially lower loss and delay, while lower-priority classes absorb more loss.
- Total loss remains broadly similar because prioritization reallocates bottleneck capacity rather than increasing it.
- The three-interval trigger introduces roughly three seconds of reaction time, during which critical traffic can still be affected at the beginning of a burst.

These are qualitative findings summarized in the repository README. Numeric tables and plots generated from the actual experiment outputs should be included when preparing a results submission; they are not reproduced here because the checkout and generated result files were not available in this workspace.

## 8. Limitations

- Severity classification relies on UDP destination ports; the switch does not inspect message payloads.
- The controller reacts to sustained utilization, so short congestion spikes may pass without intervention.
- Delay measurements use a shared emulated host clock and may not represent clock-skewed production systems.
- Port transmit counters may imply utilization slightly above 100% when packets are counted before being dropped.
- Results are from an emulated network inside a VM. Absolute throughput and latency depend on host performance; the baseline-versus-dynamic comparison is the primary result.
- The prototype's queue policy protects one severity group and does not provide durable storage, authentication, encryption, or production-grade log delivery guarantees.

## 9. Conclusion and Future Work

The project demonstrates that an SDN controller can use link measurements and Open vSwitch queues to favor critical logs during sustained congestion. Its controlled Mininet setup enables comparison with a baseline and exposes the tradeoff: improved delivery for critical events comes at the expense of lower-priority traffic, while overall link capacity and aggregate loss are not inherently improved.

Future work could evaluate adaptive thresholds, more severity levels and queue policies, larger topologies, controller reaction time, and real-world workloads. Additional repetitions and explicit numeric result tables would strengthen the statistical comparison. Production extensions could include reliable transport or retransmission, secure client authentication, persistent storage, and a searchable aggregation interface.

## References

- Project repository and README: [sdn-udp-log-aggregation](https://github.com/VineethAtGit/sdn-udp-log-aggregation)
- Ryu SDN framework: [ryu.readthedocs.io](https://ryu.readthedocs.io/)
- Mininet: [mininet.org](http://mininet.org/)
- Open vSwitch: [openvswitch.org](https://www.openvswitch.org/)
