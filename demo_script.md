# Demo script

Total time: about 10 to 12 minutes. Terminal 1 = **T1** (controller, Ryu virtualenv active),
Terminal 2 = **T2** (Mininet). Run everything from the repo root.

## Before the demo (checklist)

- [ ] VM running; VS Code connected; both terminals open in the repo folder
- [ ] `source ~/ryu-env/bin/activate` in T1
- [ ] `pkill -f ryu-manager; sudo mn -c` (clean start)
- [ ] `git status` clean and latest code pulled
- [ ] Final figures open or ready: `docs/figures/fig_loss.png`, `fig_delay.png`, `fig_burst_timeline.png`
- [ ] A backup: results of an earlier heavy run (`results/baseline_heavy_1`, `results/dynamic_heavy_1`) in case a live run fails

## Part 1: Architecture (1 min)

Show the diagram in `docs/architecture.md`. Say:
"Four clients send severity-tagged UDP logs through two switches to one server. The link between the switches is
a 10 Mbps bottleneck. A Ryu controller watches that link and, when it is congested, gives CRITICAL logs a fast queue."

## Part 2: Network and flows (2 min)

```bash
# T1
mkdir -p results/demo1
RUN_ID=demo1 ryu-manager controller/sdn_controller.py
```
Wait for `switch connected: dpid=1` and `dpid=2`.
```bash
# T2
sudo python3 topology/topo.py
```
At `mininet>`:
```
pingall
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh ovs-ofctl -O OpenFlow13 queue-stats s1
```
Say: "Zero percent dropped, so all hosts reach each other through the SDN network. These priority-100 rules match UDP
ports 5001, 5002 and 5003, one per severity class. The queue statistics show three queues on the bottleneck port."

## Part 3: The application without congestion (1.5 min)

```
h5 python3 app/log_server.py --out results/demo1 --idle-timeout 5 > /tmp/srv.out 2>&1 &
h1 python3 app/log_client.py --host-id h1 --server-ip 10.0.0.5 --rate 50 --duration 20 --out results/demo1 > /tmp/h1.out 2>&1 &
h2 python3 app/log_client.py --host-id h2 --server-ip 10.0.0.5 --rate 50 --duration 20 --out results/demo1 > /tmp/h2.out 2>&1 &
h3 python3 app/log_client.py --host-id h3 --server-ip 10.0.0.5 --rate 50 --duration 20 --out results/demo1 > /tmp/h3.out 2>&1 &
h4 python3 app/log_client.py --host-id h4 --server-ip 10.0.0.5 --rate 50 --duration 20 --out results/demo1 > /tmp/h4.out 2>&1 &
```
After about 30 s:
```
sh cat /tmp/srv.out
sh ovs-ofctl -O OpenFlow13 dump-flows s1
sh head -5 results/demo1/server_log.csv
```
Say: "About 4000 logs sent, all received, zero loss, delay a fraction of a millisecond. The flow counters now count
packets per severity, and each log is timestamped."

Then `exit` in T2, Ctrl+C in T1, `sudo mn -c`.

## Part 4: Congestion, baseline versus dynamic (5 min)

Use the automated runner to run both modes live under the heavy flood (about 3 minutes):
```bash
sudo python3 experiments/run_experiments.py --runs 1 --conditions heavy --force
```
While it runs, explain: "It starts a fresh controller for each mode. After 15 seconds a 15 Mbps UDP flood hits the
10 Mbps link for 30 seconds."

When it finishes:
```bash
cat results/baseline_heavy_1/server_stdout.txt
cat results/dynamic_heavy_1/server_stdout.txt
grep -v STATS results/dynamic_heavy_1/controller_log.csv
cat results/dynamic_heavy_1/queue_stats_s1.txt
```
Say: "Baseline: every severity loses about the same. Dynamic: the controller declared congestion, installed queue
rules, and CRITICAL and ERROR loss and delay fell sharply while the low-priority classes absorbed the loss. Queue 1
dropped nothing. When the flood ended the controller removed the rules."

(If time is short, skip the live run and show the same files from the earlier `baseline_heavy_1` / `dynamic_heavy_1`.)

## Part 5: Evaluation results (2 min)

Open the figures:
- `fig_loss.png` and `fig_delay.png`: baseline versus dynamic per severity, three congestion levels, mean over 3 runs
- `fig_burst_timeline.png`: utilization with the controller ON/OFF decisions, and per-second loss

Say: "Without congestion both modes are identical. Under congestion the controller protects the critical logs.
Overall loss stays about the same because the link is the same size; the controller changes who loses.
There is about a 3 second reaction time before protection starts."

## After the demo

```bash
# T2: exit   T1: Ctrl+C
sudo mn -c
sudo ovs-vsctl --all destroy QoS; sudo ovs-vsctl --all destroy Queue
```

## If something goes wrong

| Problem | Fix |
|---|---|
| Permission denied writing results | `sudo chown -R $USER:$USER results` |
| Leftover network or odd errors | `sudo mn -c` |
| Not sure which controller is running | Check its first line for `mode=dynamic` or `mode=baseline`; `pkill -f ryu-manager` |
| A live run fails | Show the saved `baseline_heavy_1` / `dynamic_heavy_1` results instead |
| Server printed nothing | `sh cat /tmp/srv.out` and the client output files `/tmp/h1.out` |

## Viva questions to prepare

1. Why UDP, and why does the port depend on severity?
2. What does the controller measure, and how does it decide congestion starts and ends? Why two thresholds?
3. How do the queues give priority? What are queues 0, 1 and 2?
4. Why not just drop DEBUG logs during congestion?
5. How is loss measured? How is delay measured, and why is it valid?
6. Why does CRITICAL still lose a little in dynamic mode? (Reaction time.)
7. What does the baseline show, and why is it the same code with prioritization off?
8. What do the flow-table lines mean? What are priorities 0, 1, 100 and 200?
9. What would you change for a larger or real network?
10. What did each team member build, and how does their part connect to the others?
