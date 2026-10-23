#!/usr/bin/env python3
"""
topo.py - Mininet topology, written to docs/contract.md (section 3).

   h1 --\
   h2 ---+-- s1 ======== s2 -- h5 (log server)
   h3 ---|    (s1-eth6, 10 Mbps bottleneck)
   h4 ---|
   h6 --/    (congestion generator)

s1 (dpid 1): h1-h4 on ports 1-4, h6 on port 5, uplink to s2 on port 6 (s1-eth6)
s2 (dpid 2): h5 on port 1, uplink to s1 on port 2

The 10 Mbps limit is enforced in ONE place: an OVS HTB QoS on s1-eth6 with
queue 1 (high priority), queue 2 (low priority) and queue 0 (default). In
baseline mode everything uses queue 0, so the link is simply shared.

Run (needs root):   sudo python3 topology/topo.py
Start the Ryu controller in another terminal first (see controller docstrings).
"""
import subprocess
import sys

from mininet.cli import CLI
from mininet.link import Link
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo

BOTTLENECK_IFACE = "s1-eth6"
BOTTLENECK_BPS = 10_000_000
TX_QUEUE_LEN = 100        # short buffer: congestion shows up as loss, not seconds of delay


class LogAggregationTopo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13")

        for i in range(1, 5):                                   # h1..h4: log clients
            h = self.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
            self.addLink(h, s1, port2=i)
        h6 = self.addHost("h6", ip="10.0.0.6/24")               # congestion generator
        self.addLink(h6, s1, port2=5)

        h5 = self.addHost("h5", ip="10.0.0.5/24")               # log server
        self.addLink(h5, s2, port2=1)

        self.addLink(s1, s2, port1=6, port2=2)                  # bottleneck link


topos = {"log_topo": (lambda: LogAggregationTopo())}


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


def clear_qos():
    _run(["ovs-vsctl", "--all", "destroy", "QoS"])
    _run(["ovs-vsctl", "--all", "destroy", "Queue"])


def setup_bottleneck_qos(net):
    """10 Mbps HTB with queue 1 (high priority) and queue 2 (low) on s1-eth6."""
    clear_qos()
    net.get("s1").cmd(f"ip link set {BOTTLENECK_IFACE} txqueuelen {TX_QUEUE_LEN}")
    cmd = [
        "ovs-vsctl", "--", "set", "port", BOTTLENECK_IFACE, "qos=@newqos",
        "--", "--id=@newqos", "create", "qos", "type=linux-htb",
        f"other-config:max-rate={BOTTLENECK_BPS}",
        "queues:1=@q1", "queues:2=@q2",
        "--", "--id=@q1", "create", "queue",
        "other-config:min-rate=7000000", f"other-config:max-rate={BOTTLENECK_BPS}",
        "other-config:priority=0",
        "--", "--id=@q2", "create", "queue",
        "other-config:min-rate=1000000", f"other-config:max-rate={BOTTLENECK_BPS}",
        "other-config:priority=1",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        info(f"*** WARNING: QoS setup failed:\n{result.stdout}\n")
    else:
        info(f"*** 10 Mbps QoS, queues 1 (high) and 2 (low), set on {BOTTLENECK_IFACE}\n")


def build_network(with_qos=True):
    """Create and start the network. Reusable from experiment scripts."""
    net = Mininet(topo=LogAggregationTopo(), controller=None, link=Link,
                  switch=OVSSwitch, autoSetMacs=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    net.start()
    if with_qos:
        setup_bottleneck_qos(net)
    return net


def run():
    setLogLevel("info")
    net = build_network(with_qos="--no-qos" not in sys.argv)
    try:
        CLI(net)
    finally:
        net.stop()
        clear_qos()


if __name__ == "__main__":
    run()