import logging
from pathlib import Path
from typing import Dict, List

from wntr.network import WaterNetworkModel
from wntr.sim import WNTRSimulator

logger = logging.getLogger(__name__)


class PhysicalSimulator:
    """
    Step-based wrapper around a precomputed WNTR simulation.

    We run a full EPANET simulation once in initialize() using the configured
    duration/step, then each step() simply reads the current timestep from the
    stored WNTR results. Tank levels are derived from node head minus elevation
    (never from static init_level).
    """

    def __init__(self, inp_path: str, duration_hours: float, step_minutes: float) -> None:
        self.inp_path = Path(inp_path)
        self.duration_hours = duration_hours
        self.step_minutes = step_minutes
        self.step_seconds = int(step_minutes * 60)
        self.duration_seconds = int(duration_hours * 3600)

        self.current_time = 0
        self.step_idx = 0

        self.results = None
        self.time_index: List[int] = []

        # Cached lists for convenience.
        self.tank_ids: List[str] = []
        self.pump_ids: List[str] = []
        self.valve_ids: List[str] = []

        # Commands are cached for logging only; hydraulics are open-loop.
        self.pump_commands: Dict[str, str] = {}
        self.valve_commands: Dict[str, float] = {}

        # Last known physical states for reference/logging.
        self.last_tank_levels: Dict[str, float] = {}
        self.last_pump_states: Dict[str, str] = {}
        self.last_valve_settings: Dict[str, float] = {}

        # Base model used for elevations and element metadata.
        self._base_model: WaterNetworkModel | None = None

    def initialize(self) -> None:
        if not self.inp_path.exists():
            raise FileNotFoundError(f"Missing EPANET file: {self.inp_path}")

        model = WaterNetworkModel(str(self.inp_path))
        model.options.time.duration = self.duration_seconds
        model.options.time.hydraulic_timestep = self.step_seconds
        model.options.time.report_timestep = self.step_seconds

        sim = WNTRSimulator(model)
        self.results = sim.run_sim()
        self.time_index = list(getattr(self.results, "time", []))

        self.tank_ids = model.tank_name_list
        self.pump_ids = model.pump_name_list
        self.valve_ids = model.valve_name_list
        self._base_model = model

        # Initialize last-known states from the first timestep of results.
        if self.time_index:
            t0 = self.time_index[0]
            self.last_tank_levels = self._read_tank_levels(t0)
            self.last_pump_states = self._extract_status(self.results, t0, self.pump_ids, {})
            self.last_valve_settings = self._extract_setting(self.results, t0, self.valve_ids, {})

        logger.info(
            "Loaded network %s (duration=%ss, step=%ss, timesteps=%d)",
            self.inp_path,
            self.duration_seconds,
            self.step_seconds,
            len(self.time_index),
        )

    def apply_actuator_commands(
        self, pump_commands: Dict[str, str], valve_commands: Dict[str, float]
    ) -> None:
        """
        Open-loop note: physical hydraulics are precomputed from the INP controls.
        We cache commands for logging/analysis only; they do NOT alter the stored
        WNTR results. To close the loop, rerun hydraulics each step with commands.
        """
        self.pump_commands = pump_commands.copy()
        self.valve_commands = valve_commands.copy()

    def step(self) -> Dict:
        """
        Return the snapshot at the current timestep from precomputed results.
        """
        if self.results is None or not self.time_index:
            raise RuntimeError("Call initialize() before stepping the simulator.")

        if self.step_idx >= len(self.time_index):
            return {
                "time": self.current_time,
                "tanks": {},
                "pumps": {},
                "valves": {},
                "pressures": {},
            }

        t = self.time_index[self.step_idx]
        tanks = self._read_tank_levels(t)
        pumps = self._extract_status(self.results, t, self.pump_ids, {})
        valves = self._extract_setting(self.results, t, self.valve_ids, {})

        self.last_tank_levels = tanks
        self.last_pump_states = pumps
        self.last_valve_settings = valves

        snapshot = {
            "time": t,
            "tanks": tanks,
            "pressures": {},  # extend if needed
            "pumps": pumps,
            "valves": valves,
        }

        self.step_idx += 1
        self.current_time = t
        return snapshot

    def _read_tank_levels(self, t) -> Dict[str, float]:
        levels: Dict[str, float] = {}
        if self.results is None or self._base_model is None:
            return levels
        heads = self.results.node["head"]
        for tank_id in self.tank_ids:
            if tank_id not in heads.columns:
                continue
            head = heads.loc[t, tank_id]
            elevation = float(self._base_model.get_node(tank_id).elevation)
            levels[tank_id] = float(head - elevation)
        return levels

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
