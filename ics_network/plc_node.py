from __future__ import annotations

from typing import Dict


class PlcLogic:
    """
    Light-weight PLC logic wrapper. It builds a SCADA request from the current
    physical snapshot, then stores SCADA responses for later actuator updates.
    """

    def __init__(self, plc_cfg: Dict) -> None:
        self.cfg = plc_cfg
        self.last_reply: Dict = {}
        self.cached_request: Dict = {}

    def build_request(self, physical_state: Dict) -> Dict:
        plc_id = self.cfg.get("id")
        role = self.cfg.get("role")
        element_id = self.cfg.get("element_id")

        observations: Dict = {}
        if role == "sensor" and self.cfg.get("type") == "tank":
            level = physical_state.get("tanks", {}).get(element_id)
            if level is not None:
                observations["tank_level"] = float(level)

        if role == "actuator":
            if self.cfg.get("type") == "pump":
                tank_id = self.cfg.get("logic", {}).get("tank_id")
                if tank_id:
                    level = physical_state.get("tanks", {}).get(tank_id)
                    if level is not None:
                        observations["tank_level"] = float(level)
                observations["current_status"] = physical_state.get("pumps", {}).get(
                    element_id
                )
            if self.cfg.get("type") == "valve":
                observations["pressures"] = physical_state.get("pressures", {})
                observations["current_setting"] = physical_state.get("valves", {}).get(
                    element_id
                )

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
            cmd = responses.get("pump_command")
            if cmd is not None:
                return {element_id: str(cmd)}

        if self.cfg.get("type") == "valve":
            setting = responses.get("valve_setting")
            if setting is not None:
                return {element_id: float(setting)}

        return {}
