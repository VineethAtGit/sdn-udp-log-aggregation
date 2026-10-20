#!/usr/bin/env python3
import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub

class SeveritySDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SeveritySDNController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.prev_rx_bytes = {}
        self.prev_time = {}
        self.congested = False
        self.csv_file = "controller_decisions.csv"

        with open(self.csv_file, "w") as f:
            f.write("time,event,utilization_mbps,action\n")

        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            print(f"[SDN] Switch connected: DPID={datapath.id}", flush=True)
        elif ev.state == 'DEAD':
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=inst)
        datapath.send_msg(mod)
        print("[SDN] Table-miss flow entry installed.", flush=True)

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                req = parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
                dp.send_msg(req)
            hub.sleep(1.0)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dp = ev.msg.datapath
        dpid = dp.id
        now = time.time()

        # Calculate total ingress traffic from sending hosts (Ports 1, 2, 3, 4, 6)
        total_ingress_bytes = 0
        has_stats = False

        for stat in body:
            port_no = stat.port_no
            if port_no > ofproto_v1_3.OFPP_MAX:
                continue

            # Ingress traffic on client ports heading toward server Port 5
            if port_no != 5:
                total_ingress_bytes += stat.rx_bytes
                has_stats = True

        if has_stats:
            key = dpid
            if key in self.prev_rx_bytes:
                delta_bytes = total_ingress_bytes - self.prev_rx_bytes[key]
                delta_t = now - self.prev_time[key]
                if delta_t > 0:
                    mbps = (delta_bytes * 8.0) / (delta_t * 1e6)
                    self._process_traffic(dp, mbps, now)

            self.prev_rx_bytes[key] = total_ingress_bytes
            self.prev_time[key] = now

    def _process_traffic(self, dp, mbps, now):
        HIGH_THRESHOLD = 7.5  # Bottleneck saturation threshold
        LOW_THRESHOLD = 3.0   # Traffic resolved threshold

        if mbps > HIGH_THRESHOLD and not self.congested:
            self.congested = True
            print(f"\n>>> [SDN ALERT] Ingress Congestion detected ({mbps:.2f} Mbps)! Prioritizing CRITICAL logs.", flush=True)
            self._install_priority_flows(dp)
            self._log_decision(now, "CONGESTION_START", mbps, "DROP_UDP_5003_DEBUG")

        elif mbps < LOW_THRESHOLD and self.congested:
            self.congested = False
            print(f"\n>>> [SDN RECOVERY] Bottleneck cleared ({mbps:.2f} Mbps). Restoring normal traffic.", flush=True)
            self._remove_priority_flows(dp)
            self._log_decision(now, "CONGESTION_END", mbps, "RESTORE_UDP_5003_DEBUG")

    def _install_priority_flows(self, dp):
        parser = dp.ofproto_parser
        # Install flow rule dropping DEBUG logs (UDP port 5003)
        match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=5003)
        mod = parser.OFPFlowMod(datapath=dp, priority=200, match=match, instructions=[])
        dp.send_msg(mod)

    def _remove_priority_flows(self, dp):
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=5003)
        mod = parser.OFPFlowMod(
            datapath=dp, command=ofproto.OFPFC_DELETE_STRICT,
            priority=200, match=match, out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY
        )
        dp.send_msg(mod)

    def _log_decision(self, timestamp, event, rate, action):
        with open(self.csv_file, "a") as f:
            f.write(f"{timestamp:.3f},{event},{rate:.2f},{action}\n")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = dp.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = parser.OFPFlowMod(datapath=dp, priority=1, match=match, instructions=inst)
            dp.send_msg(mod)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data
        )
        dp.send_msg(out)
