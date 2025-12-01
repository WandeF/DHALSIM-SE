from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

try:
    from mininet.net import Mininet
    from mininet.node import Controller, OVSSwitch
    from mininet.link import TCLink
except ImportError:  # pragma: no cover - optional dependency
    Mininet = None
    Controller = None
    OVSSwitch = None
    TCLink = None


class WaterCpsTopology:
    """
    Star topology with one switch, one SCADA host, and one host per PLC.
    This is a stub that can either run Mininet (if installed) or no-op so the
    rest of the co-simulation can proceed in-process.
    """

    def __init__(self, plc_config: Dict, network_config: Dict) -> None:
        self.plc_config = plc_config
        self.network_config = network_config
        self.net = None

    def build(self) -> None:
        if Mininet is None or not self.network_config.get("use_minicps", False):
            logger.info("Skipping Mininet build (not installed or disabled).")
            return

        delay = f"{self.network_config.get('link_delay_ms', 1)}ms"
        bw = self.network_config.get("link_bandwidth_mbps", 10)
        loss = self.network_config.get("loss_rate", 0)

        self.net = Mininet(controller=Controller, switch=OVSSwitch, link=TCLink, autoSetMacs=True)
        self.net.addController("c0")
        s1 = self.net.addSwitch("s1")

        scada_cfg = self.plc_config.get("scada", {})
        h_scada = self.net.addHost("h_scada", ip=scada_cfg.get("ip"))
        self.net.addLink(h_scada, s1, bw=bw, delay=delay, loss=loss)

        for idx, plc in enumerate(self.plc_config.get("plcs", []), start=1):
            host = self.net.addHost(f"h_plc_{idx}", ip=plc.get("ip"))
            self.net.addLink(host, s1, bw=bw, delay=delay, loss=loss)

    def start(self) -> None:
        if self.net is None:
            logger.info("Topology not started (Mininet disabled).")
            return
        self.net.start()
        logger.info("Mininet topology started with %d PLC hosts.", len(self.plc_config.get("plcs", [])))

    def stop(self) -> None:
        if self.net is None:
            return
        self.net.stop()
        logger.info("Mininet topology stopped.")
