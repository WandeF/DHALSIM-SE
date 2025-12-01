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
                cmd = self._dispatch_pump_logic(cfg, observations)
                self.pump_commands[cfg["element_id"]] = cmd if cmd is not None else self.pump_commands.get(
                    cfg["element_id"]
                )
                resp = {}
                if plc_id in self.overrides:
                    resp["override_action"] = self.overrides[plc_id]
                elif cmd is not None:
                    resp["pump_command"] = cmd
                return {"plc_id": plc_id, "responses": resp}

            if cfg.get("type") == "valve":
                setting = self._dispatch_valve_logic(cfg, observations)
                self.valve_commands[cfg["element_id"]] = setting if setting is not None else self.valve_commands.get(
                    cfg["element_id"]
                )
                resp = {}
                if plc_id in self.overrides:
                    resp["override_action"] = self.overrides[plc_id]
                elif setting is not None:
                    resp["valve_setting"] = setting
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

    def _dispatch_pump_logic(self, cfg: Dict, observations: Dict) -> str:
        logic = cfg.get("logic", {})
        mode = logic.get("mode")
        if mode == "native_inp":
            return None
        if mode != "on_if_tank_low":
            return "ON"

        tank_id = logic.get("tank_id")
        low = float(logic.get("low_level", 0))
        high = float(logic.get("high_level", low))

        # Prefer local observation; fall back to last SCADA view.
        level = observations.get("tank_level")
        if level is None and tank_id:
            level = self.latest_sensors.get(tank_id)

        if level is None:
            return "ON"

        level = float(level)
        if level < low:
            return "ON"
        if level > high:
            return "OFF"
        # Keep last command to avoid chatter.
        return self.pump_commands.get(cfg["element_id"], "ON")

    def _dispatch_valve_logic(self, cfg: Dict, observations: Dict) -> float:
        logic = cfg.get("logic", {})
        mode = logic.get("mode")
        if mode == "native_inp":
            return None
        if mode != "open_if_pressure_high":
            return 1.0

        threshold = float(logic.get("pressure_threshold", 0))
        junction_id = logic.get("junction_id")

        pressure_map = observations.get("pressures") or {}
        local_pressure = pressure_map.get(junction_id)
        if local_pressure is None:
            return 1.0 if threshold <= 0 else 0.0

        return 1.0 if float(local_pressure) > threshold else 0.0
