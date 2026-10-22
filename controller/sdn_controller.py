# #!/usr/bin/env python3
# import time
# from ryu.base import app_manager
# from ryu.controller import ofp_event
# from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
# from ryu.ofproto import ofproto_v1_3
# from ryu.lib.packet import packet, ethernet, ether_types
# from ryu.lib import hub

# class SeveritySDNController(app_manager.RyuApp):
#     OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

#     def __init__(self, *args, **kwargs):
#         super(SeveritySDNController, self).__init__(*args, **kwargs)
#         self.mac_to_port = {}
#         self.datapaths = {}
#         self.prev_rx_bytes = {}
#         self.prev_time = {}
#         self.congested = False
#         self.csv_file = "controller_decisions.csv"

#         with open(self.csv_file, "w") as f:
#             f.write("time,event,utilization_mbps,action\n")

#         self.monitor_thread = hub.spawn(self._monitor)

#     @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
#     def _state_change_handler(self, ev):
#         datapath = ev.datapath
#         if ev.state == MAIN_DISPATCHER:
#             self.datapaths[datapath.id] = datapath
#             print(f"[SDN] Switch connected: DPID={datapath.id}", flush=True)
#         elif ev.state == 'DEAD':
#             if datapath.id in self.datapaths:
#                 del self.datapaths[datapath.id]

#     @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
#     def switch_features_handler(self, ev):
#         datapath = ev.msg.datapath
#         ofproto = datapath.ofproto
#         parser = datapath.ofproto_parser

#         # Table-miss flow entry
#         match = parser.OFPMatch()
#         actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
#         inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
#         mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=inst)
#         datapath.send_msg(mod)
#         print("[SDN] Table-miss flow entry installed.", flush=True)

#     def _monitor(self):
#         while True:
#             for dp in list(self.datapaths.values()):
#                 parser = dp.ofproto_parser
#                 req = parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
#                 dp.send_msg(req)
#             hub.sleep(1.0)

#     @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
#     def _port_stats_reply_handler(self, ev):
#         body = ev.msg.body
#         dp = ev.msg.datapath
#         dpid = dp.id
#         now = time.time()

#         # Calculate total ingress traffic from sending hosts (Ports 1, 2, 3, 4, 6)
#         total_ingress_bytes = 0
#         has_stats = False

#         for stat in body:
#             port_no = stat.port_no
#             if port_no > ofproto_v1_3.OFPP_MAX:
#                 continue

#             # Ingress traffic on client ports heading toward server Port 5
#             if port_no != 5:
#                 total_ingress_bytes += stat.rx_bytes
#                 has_stats = True

#         if has_stats:
#             key = dpid
#             if key in self.prev_rx_bytes:
#                 delta_bytes = total_ingress_bytes - self.prev_rx_bytes[key]
#                 delta_t = now - self.prev_time[key]
#                 if delta_t > 0:
#                     mbps = (delta_bytes * 8.0) / (delta_t * 1e6)
#                     self._process_traffic(dp, mbps, now)

#             self.prev_rx_bytes[key] = total_ingress_bytes
#             self.prev_time[key] = now

#     def _process_traffic(self, dp, mbps, now):
#         HIGH_THRESHOLD = 7.5  # Bottleneck saturation threshold
#         LOW_THRESHOLD = 3.0   # Traffic resolved threshold

#         if mbps > HIGH_THRESHOLD and not self.congested:
#             self.congested = True
#             print(f"\n>>> [SDN ALERT] Ingress Congestion detected ({mbps:.2f} Mbps)! Prioritizing CRITICAL logs.", flush=True)
#             self._install_priority_flows(dp)
#             self._log_decision(now, "CONGESTION_START", mbps, "DROP_UDP_5003_DEBUG")

#         elif mbps < LOW_THRESHOLD and self.congested:
#             self.congested = False
#             print(f"\n>>> [SDN RECOVERY] Bottleneck cleared ({mbps:.2f} Mbps). Restoring normal traffic.", flush=True)
#             self._remove_priority_flows(dp)
#             self._log_decision(now, "CONGESTION_END", mbps, "RESTORE_UDP_5003_DEBUG")

#     def _install_priority_flows(self, dp):
#         parser = dp.ofproto_parser
#         # Install flow rule dropping DEBUG logs (UDP port 5003)
#         match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=5003)
#         mod = parser.OFPFlowMod(datapath=dp, priority=200, match=match, instructions=[])
#         dp.send_msg(mod)

#     def _remove_priority_flows(self, dp):
#         ofproto = dp.ofproto
#         parser = dp.ofproto_parser
#         match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=5003)
#         mod = parser.OFPFlowMod(
#             datapath=dp, command=ofproto.OFPFC_DELETE_STRICT,
#             priority=200, match=match, out_port=ofproto.OFPP_ANY,
#             out_group=ofproto.OFPG_ANY
#         )
#         dp.send_msg(mod)

#     def _log_decision(self, timestamp, event, rate, action):
#         with open(self.csv_file, "a") as f:
#             f.write(f"{timestamp:.3f},{event},{rate:.2f},{action}\n")

#     @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
#     def _packet_in_handler(self, ev):
#         msg = ev.msg
#         dp = msg.datapath
#         ofproto = dp.ofproto
#         parser = dp.ofproto_parser
#         in_port = msg.match['in_port']

#         pkt = packet.Packet(msg.data)
#         eth = pkt.get_protocols(ethernet.ethernet)[0]

#         if eth.ethertype == ether_types.ETH_TYPE_LLDP:
#             return

#         dst = eth.dst
#         src = eth.src
#         dpid = dp.id
#         self.mac_to_port.setdefault(dpid, {})
#         self.mac_to_port[dpid][src] = in_port

#         if dst in self.mac_to_port[dpid]:
#             out_port = self.mac_to_port[dpid][dst]
#         else:
#             out_port = ofproto.OFPP_FLOOD

#         actions = [parser.OFPActionOutput(out_port)]

#         if out_port != ofproto.OFPP_FLOOD:
#             match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
#             inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
#             mod = parser.OFPFlowMod(datapath=dp, priority=1, match=match, instructions=inst)
#             dp.send_msg(mod)

#         data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
#         out = parser.OFPPacketOut(
#             datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
#             actions=actions, data=data
#         )
#         dp.send_msg(out)

#!/usr/bin/env python3
"""
sdn_controller.py - Ryu (OpenFlow 1.3) controller, written to docs/contract.md.

Topology (contract section 3): s1 (dpid 1) has h1-h4 on ports 1-4, h6 on port 5
and the bottleneck uplink to s2 on port 6 (s1-eth6, 10 Mbps). s2 (dpid 2) has
h5 (log server) on port 1 and the uplink to s1 on port 2.

Run from the repo root:
  RUN_ID=dynamic_heavy_1 ryu-manager controller/sdn_controller.py     # dynamic
  RUN_ID=baseline_heavy_1 ryu-manager controller/baseline_controller.py  # baseline

Behaviour (contract section 4):
  * flow priorities: table-miss 0, normal forwarding 10 (learning switch is 1,
    per-severity forwarding 100), queue rules 200
  * polls port stats every 1 s; utilization = TX rate of s1-eth6 / 10 Mbps
  * congestion ON  : utilization > 80 % for 3 consecutive intervals
  * congestion OFF : utilization < 50 % for 3 consecutive intervals
  * on ON : port 5001 -> queue 1 (high); 5002, 5003, 5004 -> queue 2 (low)
  * on OFF: queue rules removed
  * baseline mode never installs queue rules (but logs identically)

Outputs in results/<RUN_ID>/:
  controller_log.csv : time,event,utilization,action   (utilization in %)
  flow_stats.csv     : time,dpid,udp_dst,priority,packets,bytes  (extra, per-severity counters)
"""
import os
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,
                                    MAIN_DISPATCHER, set_ev_cls)
from ryu.lib import hub
from ryu.lib.packet import ether_types, ethernet, packet
from ryu.ofproto import ofproto_v1_3

# ---- constants (contract sections 2-4); tune here ---------------------------
RUN_ID = os.environ.get("RUN_ID", "tmp")
RESULTS_DIR = os.environ.get("RESULTS_DIR", "results")

SERVER_IP = "10.0.0.5"
SERVER_PORT_BY_DPID = {1: 6, 2: 1}      # port toward the server on each switch
BOTTLENECK_DPID = 1                     # s1
BOTTLENECK_PORT = 6                     # s1-eth6 (toward s2)
BOTTLENECK_MBPS = 10.0

POLL_INTERVAL = 1.0
ON_THRESHOLD = 80.0                     # percent
OFF_THRESHOLD = 50.0                    # percent
CONSECUTIVE = 3

HIGH_QUEUE = 1
LOW_QUEUE = 2
LOG_PORTS = [5001, 5002, 5003]
CONGESTION_PORT = 5004
QUEUE_BY_PORT = {5001: HIGH_QUEUE, 5002: LOW_QUEUE,
                 5003: LOW_QUEUE, CONGESTION_PORT: LOW_QUEUE}

PRIO_STATIC = 100
PRIO_DYNAMIC = 200


class SeveritySDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    MODE = os.environ.get("MODE", "dynamic").lower()     # overridden in baseline_controller.py

    def __init__(self, *args, **kwargs):
        super(SeveritySDNController, self).__init__(*args, **kwargs)
        if self.MODE not in ("baseline", "dynamic"):
            raise ValueError("MODE must be 'baseline' or 'dynamic'")
        self.mac_to_port = {}
        self.datapaths = {}
        self.prev_tx = None
        self.prev_time = None
        self.congested = False
        self.on_count = 0
        self.off_count = 0

        out_dir = os.path.join(RESULTS_DIR, RUN_ID)
        os.makedirs(out_dir, exist_ok=True)
        self.log_path = os.path.join(out_dir, "controller_log.csv")
        self.flow_path = os.path.join(out_dir, "flow_stats.csv")
        with open(self.log_path, "w") as f:
            f.write("time,event,utilization,action\n")
        with open(self.flow_path, "w") as f:
            f.write("time,dpid,udp_dst,priority,packets,bytes\n")

        print(f"[SDN] mode={self.MODE} run_id={RUN_ID} -> {out_dir}", flush=True)
        self.monitor_thread = hub.spawn(self._monitor)

    def _log(self, event, utilization, action="-"):
        with open(self.log_path, "a") as f:
            f.write(f"{time.time():.3f},{event},{utilization:.1f},{action}\n")

    # ---- switch lifecycle ---------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            print(f"[SDN] switch connected: dpid={dp.id}", flush=True)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)
            print(f"[SDN] switch disconnected: dpid={dp.id}", flush=True)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser

        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, parser.OFPMatch(), actions)           # table-miss

        out_port = SERVER_PORT_BY_DPID.get(dp.id)
        if out_port is not None:                                     # per-severity flows
            for port in LOG_PORTS:
                self._add_flow(dp, PRIO_STATIC, self._server_match(parser, port),
                               [parser.OFPActionOutput(out_port)])
        print(f"[SDN] flows installed on dpid={dp.id}", flush=True)

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _server_match(parser, udp_dst):
        return parser.OFPMatch(eth_type=0x0800, ip_proto=17,
                               ipv4_dst=SERVER_IP, udp_dst=udp_dst)

    def _add_flow(self, dp, priority, match, actions):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority,
                                      match=match, instructions=inst))

    # ---- monitoring ---------------------------------------------------------
    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
                dp.send_msg(parser.OFPFlowStatsRequest(dp))
            hub.sleep(POLL_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        if dp.id != BOTTLENECK_DPID:
            return
        now = time.time()
        tx = None
        for stat in ev.msg.body:
            if stat.port_no == BOTTLENECK_PORT:
                tx = stat.tx_bytes
        if tx is None:
            return

        if self.prev_tx is not None:
            dt = now - self.prev_time
            if dt > 0:
                mbps = (tx - self.prev_tx) * 8.0 / (dt * 1e6)
                util = mbps / BOTTLENECK_MBPS * 100.0
                self._log("STATS", util, f"tx_mbps={mbps:.2f}")
                if self.MODE == "dynamic":
                    self._evaluate(util)
        self.prev_tx, self.prev_time = tx, now

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        now = time.time()
        rows = []
        for stat in ev.msg.body:
            if stat.priority not in (PRIO_STATIC, PRIO_DYNAMIC):
                continue
            try:
                udp_dst = stat.match.get("udp_dst")
            except Exception:
                udp_dst = None
            if udp_dst is None:
                continue
            rows.append(f"{now:.3f},{dp.id},{udp_dst},{stat.priority},"
                        f"{stat.packet_count},{stat.byte_count}\n")
        if rows:
            with open(self.flow_path, "a") as f:
                f.writelines(rows)

    # ---- congestion logic (dynamic mode only) -------------------------------
    def _evaluate(self, util):
        dp = self.datapaths.get(BOTTLENECK_DPID)
        if dp is None:
            return
        if not self.congested:
            self.on_count = self.on_count + 1 if util > ON_THRESHOLD else 0
            if self.on_count >= CONSECUTIVE:
                self.congested, self.on_count = True, 0
                print(f">>> [SDN] congestion ON ({util:.0f}%): prioritizing CRITICAL",
                      flush=True)
                self._log("CONGESTION_ON", util, "install_queue_rules")
                self._install_priority_flows(dp)
                self._log("FLOW_INSTALL", util, "5001->queue1;5002,5003,5004->queue2")
        else:
            self.off_count = self.off_count + 1 if util < OFF_THRESHOLD else 0
            if self.off_count >= CONSECUTIVE:
                self.congested, self.off_count = False, 0
                print(f">>> [SDN] congestion OFF ({util:.0f}%): back to normal",
                      flush=True)
                self._log("CONGESTION_OFF", util, "remove_queue_rules")
                self._remove_priority_flows(dp)
                self._log("FLOW_REMOVE", util, "queue_rules_removed")

    def _install_priority_flows(self, dp):
        parser = dp.ofproto_parser
        for port, queue in QUEUE_BY_PORT.items():
            actions = [parser.OFPActionSetQueue(queue),
                       parser.OFPActionOutput(BOTTLENECK_PORT)]
            self._add_flow(dp, PRIO_DYNAMIC, self._server_match(parser, port), actions)

    def _remove_priority_flows(self, dp):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        for port in QUEUE_BY_PORT:
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp, command=ofp.OFPFC_DELETE_STRICT,
                priority=PRIO_DYNAMIC, match=self._server_match(parser, port),
                out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))

    # ---- learning switch (ARP and anything not matched above) ---------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]

        eth = packet.Packet(msg.data).get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.mac_to_port.setdefault(dp.id, {})[eth.src] = in_port
        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            self._add_flow(dp, 1, parser.OFPMatch(in_port=in_port, eth_dst=eth.dst),
                           actions)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions, data=data))
