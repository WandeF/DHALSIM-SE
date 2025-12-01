import logging
from pathlib import Path
from typing import Dict, Tuple

from wntr.network import WaterNetworkModel
from wntr.sim import WNTRSimulator

logger = logging.getLogger(__name__)


class PhysicalSimulator:
    """
    Thin wrapper around WNTR that exposes a per-step API.

    Note: This mini version runs a short hydraulic horizon every step using the
    current actuator settings. It does not yet preserve full hydraulic state
    between steps; for control design that is usually sufficient and keeps the
    code small. Swap in a more advanced scheme later if you need warm-starting.
    """

    def __init__(self, inp_path: str, duration_hours: float, step_minutes: float) -> None:
        self.inp_path = Path(inp_path)
        self.duration_hours = duration_hours
        self.step_minutes = step_minutes
        self.step_seconds = int(step_minutes * 60)
        self.duration_seconds = int(duration_hours * 3600)

        self.current_time = 0

        # Most recent actuator commands that will be applied to the model.
        self.pump_commands: Dict[str, str] = {}
        self.valve_commands: Dict[str, float] = {}
        self.initial_tank_levels: Dict[str, float] = {}
        self.last_tank_levels: Dict[str, float] = {}

    def initialize(self) -> None:
        if not self.inp_path.exists():
            raise FileNotFoundError(f"Missing EPANET file: {self.inp_path}")
        self.current_time = 0
        # Capture initial tank levels from the template network.
        model = WaterNetworkModel(str(self.inp_path))
        self.initial_tank_levels = {
            tank_id: model.get_node(tank_id).init_level for tank_id in model.tank_name_list
        }
        self.last_tank_levels = self.initial_tank_levels.copy()
        logger.info(
            "Loaded network %s (duration=%ss, step=%ss)",
            self.inp_path,
            self.duration_seconds,
            self.step_seconds,
        )

    def apply_actuator_commands(
        self, pump_commands: Dict[str, str], valve_commands: Dict[str, float]
    ) -> None:
        """Update the actuator commands to use for the next step."""
        self.pump_commands = pump_commands.copy()
        self.valve_commands = valve_commands.copy()

    def step(self) -> Dict:
        """
        Advance the physical model by one coarse step.

        Returns a snapshot dictionary with key measurements and actuator status.
        """
        # Stop if we've exceeded the configured duration.
        if self.current_time >= self.duration_seconds:
            return {
                "time": self.current_time,
                "tanks": {},
                "pumps": {},
                "valves": {},
                "pressures": {},
            }

        model = WaterNetworkModel(str(self.inp_path))
        model.options.time.duration = self.step_seconds
        model.options.time.hydraulic_timestep = self.step_seconds

        self._apply_commands_to_model(model)
        self._apply_tank_levels(model)

        sim = WNTRSimulator(model)
        results = sim.run_sim()

        if not getattr(results, "time", []):
            logger.warning("Simulation returned no timesteps; skipping step at t=%s", self.current_time)
            self.current_time += self.step_seconds
            return {
                "time": self.current_time,
                "tanks": {},
                "pressures": {},
                "pumps": self.pump_commands.copy(),
                "valves": self.valve_commands.copy(),
            }

        # Extract the last timestep (should equal step_seconds).
        ts = results.time[-1]
        tank_levels = results.node["pressure"].loc[ts, model.tank_name_list].to_dict()
        pressures = results.node["pressure"].loc[ts].to_dict()
        # Track tank levels for the next step's initial conditions.
        if tank_levels:
            self.last_tank_levels.update(tank_levels)

        # Pump/valve states from the results frames; fall back to commands if missing.
        pump_states = self._extract_status(results, ts, model.pump_name_list, self.pump_commands)
        valve_states = self._extract_setting(results, ts, model.valve_name_list, self.valve_commands)

        self.current_time += self.step_seconds
        return {
            "time": self.current_time,
            "tanks": tank_levels,
            "pressures": pressures,
            "pumps": pump_states,
            "valves": valve_states,
        }

    def _apply_commands_to_model(self, model: WaterNetworkModel) -> None:
        for pump_id, status in self.pump_commands.items():
            link = model.get_link(pump_id)
            state = 1 if str(status).upper() in {"OPEN", "ON", "1"} else 0
            link.initial_status = state

        for valve_id, setting in self.valve_commands.items():
            link = model.get_link(valve_id)
            link.initial_setting = float(setting)
            try:
                link.setting = float(setting)
            except AttributeError:
                pass

    def _apply_tank_levels(self, model: WaterNetworkModel) -> None:
        for tank_id, level in self.last_tank_levels.items():
            try:
                tank = model.get_node(tank_id)
                tank.init_level = float(level)
            except Exception:
                continue

    @staticmethod
    def _extract_status(results, ts, ids, fallback: Dict[str, str]) -> Dict[str, str]:
        if not ids:
            return {}
        status_frame = results.link.get("status")
        if status_frame is None:
            return fallback
        data = status_frame.loc[ts, ids].to_dict()
        return {k: ("ON" if int(v) else "OFF") for k, v in data.items()}

    @staticmethod
    def _extract_setting(results, ts, ids, fallback: Dict[str, float]) -> Dict[str, float]:
        if not ids:
            return {}
        setting_frame = results.link.get("setting")
        if setting_frame is None:
            return fallback
        return setting_frame.loc[ts, ids].to_dict()
