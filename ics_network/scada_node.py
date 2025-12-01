from __future__ import annotations

from typing import Dict, List


class ScadaServer:
    """
    Minimal in-process SCADA logic that emulates request/response handling.
    Control rules are intentionally simple and hard-coded for the mini project.
    """

    def __init__(self, plc_config: Dict) -> None:
        self.plc_config = plc_config
        self.latest_sensors: Dict[str, float] = {}  # tank_id -> level

        self.pump_commands: Dict[str, str] = {}
        self.valve_commands: Dict[str, float] = {}
        self.overrides: Dict[str, str] = {}

    def handle_plc_request(self, request: Dict) -> Dict:
        plc_id = request.get("plc_id")
        role = request.get("role")
        observations = request.get("observations", {})
        current_time = request.get("time", 0)

        # Demo override window: force PLC_PUMP_1 OFF between 10000s and 15000s.
        if 10000 < current_time < 15000:
            self.overrides["PLC_PUMP_1"] = "OFF"
        else:
            self.overrides.pop("PLC_PUMP_1", None)

        cfg = self._find_plc_cfg(plc_id)
        if cfg is None:
            return {"plc_id": plc_id, "responses": {}, "error": "unknown_plc"}

        if role == "sensor":
            self._ingest_sensor(cfg, observations)
            return {"plc_id": plc_id, "responses": {}}

        if role == "actuator":
            if cfg.get("type") == "pump":
                cmd = self._dispatch_actuator_logic(cfg, observations)
                if cmd is not None:
                    self.pump_commands[cfg["element_id"]] = cmd
                resp = {}
                if plc_id in self.overrides:
                    resp["override_action"] = self.overrides[plc_id]
                elif cmd is not None:
                    resp["pump_command"] = cmd
                return {"plc_id": plc_id, "responses": resp}

            if cfg.get("type") == "valve":
                cmd = self._dispatch_actuator_logic(cfg, observations)
                if cmd is not None:
                    self.valve_commands[cfg["element_id"]] = cmd
                resp = {}
                if plc_id in self.overrides:
                    resp["override_action"] = self.overrides[plc_id]
                elif cmd is not None:
                    resp["valve_setting"] = cmd
                return {"plc_id": plc_id, "responses": resp}

        return {"plc_id": plc_id, "responses": {}, "error": "unknown_role"}

    def get_actuator_commands(self) -> tuple[Dict[str, str], Dict[str, float]]:
        """
        Return the latest pump/valve commands. The dicts are not cleared so the
        caller can reuse them if no new messages arrive.
        """
        return self.pump_commands.copy(), self.valve_commands.copy()

    def _find_plc_cfg(self, plc_id: str) -> Dict | None:
        for plc in self.plc_config.get("plcs", []):
            if plc.get("id") == plc_id:
                return plc
        return None

    def _ingest_sensor(self, cfg: Dict, observations: Dict) -> None:
        if cfg.get("type") == "tank":
            level = observations.get("tank_level")
            if level is not None:
                self.latest_sensors[cfg["element_id"]] = float(level)

    def _dispatch_actuator_logic(self, cfg: Dict, observations: Dict):
        """
        Map INP-derived control patterns to simple modes:
        open_if_below / close_if_below / open_if_above / close_if_above.
        """
        logic = cfg.get("logic", {})
        mode = logic.get("mode")
        node_id = logic.get("node_id")
        threshold = float(logic.get("threshold", 0))

        # Use current observation; fall back to last known sensor value.
        level = observations.get("level")
        if level is None and node_id:
            level = self.latest_sensors.get(node_id)
        if level is None:
            return None

        if mode == "open_if_below":
            return "OPEN" if level < threshold else "CLOSED"
        if mode == "close_if_below":
            return "CLOSED" if level < threshold else "OPEN"
        if mode == "open_if_above":
            return "OPEN" if level > threshold else "CLOSED"
        if mode == "close_if_above":
            return "CLOSED" if level > threshold else "OPEN"
        return None
