from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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
            if level is None:
                level = observations.get("level")
            if level is not None:
                self.latest_sensors[cfg["element_id"]] = float(level)

    @staticmethod
    def _normalize_status(status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        s = str(status).upper()
        if s in {"OPEN", "ON", "1", "TRUE"}:
            return "OPEN"
        if s in {"CLOSED", "OFF", "0", "FALSE"}:
            return "CLOSED"
        return None

    def _last_command_for_element(self, element_id: str, elem_type: str) -> Optional[str]:
        if elem_type == "pump":
            return self._normalize_status(self.pump_commands.get(element_id))
        if elem_type == "valve":
            return self._normalize_status(self.valve_commands.get(element_id))
        return None

    def _select_rule_action(self, rules: List[Dict], level: float, default_action: Optional[str]) -> Optional[str]:
        matching = []
        for rule in rules:
            comparator = str(rule.get("comparator", "")).upper()
            action = str(rule.get("action", "")).upper()
            threshold = float(rule.get("threshold", 0))
            priority = int(rule.get("priority", 0))
            rule_index = int(rule.get("rule_index", 0))

            condition_met = False
            if comparator == "BELOW":
                condition_met = level < threshold
            elif comparator == "ABOVE":
                condition_met = level > threshold

            if condition_met:
                matching.append((priority, rule_index, action))

        if not matching:
            return default_action

        # Higher priority wins; tie-breaker is later rule_index.
        _, _, chosen_action = max(matching, key=lambda x: (x[0], x[1]))
        return chosen_action

    def _dispatch_actuator_logic(self, cfg: Dict, observations: Dict):
        """
        Evaluate EPANET-style rules per element. When no rule matches, keep the
        previous state (last command if any, else the current physical status).
        """
        logic = cfg.get("logic", {})
        node_id = logic.get("node_id")
        element_id = cfg.get("element_id")
        elem_type = cfg.get("type")

        # Latest measured level.
        level = observations.get("level")
        if level is None and node_id:
            level = self.latest_sensors.get(node_id)

        # Normalized current status and last command.
        current_status = self._normalize_status(observations.get("current_status"))
        last_command = self._last_command_for_element(element_id, elem_type)
        fallback = last_command or current_status

        rules = logic.get("rules") or []
        if rules:
            if level is None:
                return fallback
            action = self._select_rule_action(rules, float(level), fallback)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "SCADA rule eval element=%s level=%s -> %s (fallback=%s)",
                    element_id,
                    level,
                    action,
                    fallback,
                )
            return action

        # Legacy simple modes (kept for compatibility).
        mode = logic.get("mode")
        threshold = float(logic.get("threshold", 0))
        if level is None and node_id:
            level = self.latest_sensors.get(node_id)
        if level is None:
            return fallback

        if mode == "open_if_below":
            return "OPEN" if level < threshold else fallback
        if mode == "close_if_below":
            return "CLOSED" if level < threshold else fallback
        if mode == "open_if_above":
            return "OPEN" if level > threshold else fallback
        if mode == "close_if_above":
            return "CLOSED" if level > threshold else fallback
        return fallback
