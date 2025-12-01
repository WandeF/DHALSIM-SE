from __future__ import annotations

import logging
from typing import Dict, Any

from wntr.network import WaterNetworkModel

logger = logging.getLogger(__name__)


class PlcLogic:
    """
    Light-weight PLC logic wrapper. It builds a SCADA request from the current
    physical snapshot, then stores SCADA responses for later actuator updates.
    """

    def __init__(self, plc_cfg: Dict, inp_path: str | None = None) -> None:
        self.cfg = plc_cfg
        self.last_reply: Dict = {}
        self.cached_request: Dict = {}
        self.native_logic: Dict[str, Any] = {}

        if inp_path:
            try:
                model = WaterNetworkModel(str(inp_path))
                target_id = plc_cfg.get("element_id")
                # Collect controls and rules that involve this actuator.
                controls = []
                for ctl_name in getattr(model, "control_name_list", []) or []:
                    ctl = model.get_control(ctl_name)
                    ctl_str = str(ctl)
                    if target_id and target_id in ctl_str:
                        controls.append(ctl_str)
                rules = []
                for rule in getattr(model, "rules", []) or []:
                    rule_str = str(rule)
                    if target_id and target_id in rule_str:
                        rules.append(rule_str)
                self.native_logic = {"controls": controls, "rules": rules}
                if controls or rules:
                    logger.info(
                        "PLC %s initialized with native logic targeting %s: %s",
                        plc_cfg.get("id"),
                        target_id,
                        self.native_logic,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load native logic for %s: %s", plc_cfg.get("id"), exc)

    def build_request(self, physical_state: Dict) -> Dict:
        plc_id = self.cfg.get("id")
        role = self.cfg.get("role")
        element_id = self.cfg.get("element_id")

        observations: Dict = {}
        logic = self.cfg.get("logic", {})

        # Sensor PLC: report its node value.
        if role == "sensor":
            node_id = logic.get("node_id") or element_id
            level = physical_state.get("tanks", {}).get(node_id)
            if level is not None:
                observations["level"] = float(level)

        if role == "actuator":
            if logic:
                node_id = logic.get("node_id")
                if node_id:
                    level = physical_state.get("tanks", {}).get(node_id)
                    if level is not None:
                        observations["level"] = float(level)
                observations["current_status"] = physical_state.get("pumps", {}).get(
                    element_id
                ) or physical_state.get("valves", {}).get(element_id)

        request = {
            "plc_id": plc_id,
            "role": role,
            "time": physical_state.get("time"),
            "observations": observations,
        }
        self.cached_request = request
        return request

    def update_from_scada_reply(self, reply: Dict) -> None:
        self.last_reply = reply or {}

    def get_actuator_effect(self) -> Dict:
        """
        Return actuator commands for the controlled element. The key matches the
        EPANET element ID for pumps/valves.
        """
        if self.cfg.get("role") != "actuator":
            return {}

        element_id = self.cfg.get("element_id")
        responses = self.last_reply.get("responses", {})

        if self.cfg.get("type") == "pump":
            if "override_action" in responses:
                return {element_id: responses["override_action"]}
            if "pump_command" in responses:
                return {element_id: responses["pump_command"]}

        if self.cfg.get("type") == "valve":
            if "override_action" in responses:
                return {element_id: responses["override_action"]}
            if "valve_setting" in responses:
                return {element_id: responses["valve_setting"]}

        return {}
