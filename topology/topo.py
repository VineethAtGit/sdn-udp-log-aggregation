from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel

class LogAggregationTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1', protocols='OpenFlow13')

        # h1-h4: Log clients
        for i in range(1, 5):
            self.addHost(f'h{i}', ip=f'10.0.0.{i}/24')
            self.addLink(f'h{i}', s1, bw=100)

        # h5: Log Server on switch port 5 with 10 Mbps bottleneck
        self.addHost('h5', ip='10.0.0.5/24')
        self.addLink('h5', s1, port2=5, bw=10, delay='2ms')

        # h6: Congestion generator
        self.addHost('h6', ip='10.0.0.6/24')
        self.addLink('h6', s1, bw=100)

topos = {'log_topo': (lambda: LogAggregationTopo())}
