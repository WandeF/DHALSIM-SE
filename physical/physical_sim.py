import logging
from pathlib import Path
from typing import Dict, List, Optional

from wntr.network import WaterNetworkModel
from wntr.epanet import toolkit as enData
from wntr.epanet.util import EN


logger = logging.getLogger(__name__)


class ClosedLoopPhysicalSimulator:
    """
    Closed-loop, step-wise EPANET toolkit simulation.

    PLC/SCADA commands are applied to link status before each hydraulic step,
    then ENrunH/ENnextH advance the hydraulics. 不再手动改 tank level，
    一切由 EPANET 自己算。
    """

    def __init__(self, inp_path: str, sim_config: dict) -> None:
        """
        初始化 WNTR / EPANET 模型。
        inp_path: 水网 inp 文件路径
        sim_config: 仿真配置（步长、总时长等）
        """
        self.inp_path = Path(inp_path)
        self.sim_config = sim_config or {}
        sim_cfg = self.sim_config.get("simulation", {})
        self.duration_hours = float(sim_cfg.get("duration_hours", 0))
        self.step_minutes = float(sim_cfg.get("step_minutes", 0))
        self.step_seconds = int(self.step_minutes * 60)
        self.duration_seconds = int(self.duration_hours * 3600)

        self.current_time_s = 0.0
        self.finished = False

        self.tank_ids: List[str] = []
        self.pump_ids: List[str] = []
        self.valve_ids: List[str] = []
        self._link_names: List[str] = []
        self._node_names: List[str] = []
        self.link_name_to_index: Dict[str, int] = {}
        self.node_name_to_index: Dict[str, int] = {}

        self.pump_commands: Dict[str, str] = {}
        self.valve_commands: Dict[str, str] = {}

        # EPANET engine handle，会在 initialize 里真正打开
        self._en: Optional[enData.ENepanet] = None

    def _load_network_metadata(self) -> None:
        if self._link_names and self._node_names:
            return
        if not self.inp_path.exists():
            raise FileNotFoundError(f"Missing EPANET file: {self.inp_path}")
        wn = WaterNetworkModel(str(self.inp_path))
        self.tank_ids = wn.tank_name_list
        self.pump_ids = wn.pump_name_list
        self.valve_ids = wn.valve_name_list
        self._link_names = wn.link_name_list
        self._node_names = wn.node_name_list

    def _open_engine(self) -> None:
        if self._en is not None:
            try:
                self._en.ENcloseH()
            except Exception:
                pass
            try:
                self._en.ENclose()
            except Exception:
                pass
        self._en = enData.ENepanet()
        self._en.ENopen(str(self.inp_path), "closed_loop.rpt", "")

        self._en.ENsettimeparam(EN.DURATION, int(self.duration_seconds))
        self._en.ENsettimeparam(EN.HYDSTEP, int(self.step_seconds))
        self._en.ENsettimeparam(EN.REPORTSTEP, int(self.step_seconds))
        self._en.ENsettimeparam(EN.REPORTSTART, 0)

        self.link_name_to_index = {lid: self._en.ENgetlinkindex(lid) for lid in self._link_names}
        self.node_name_to_index = {nid: self._en.ENgetnodeindex(nid) for nid in self._node_names}

        self._en.ENopenH()
        self._en.ENinitH(0)
        logger.info("Closed-loop: opened EPANET toolkit for %s", self.inp_path)

    def reset(self) -> Dict:
        """
        重置仿真状态到初始条件。
        返回：state（dict），例如 {'pressure': ..., 'flow': ..., 'tank_level': ...}
        """
        self._load_network_metadata()
        self._open_engine()
        self.current_time_s = 0.0
        self.finished = False
        self.pump_commands = {}
        self.valve_commands = {}
        return self._read_state(time_override=0.0)

    def apply_actuator_commands(
        self, commands: Dict[str, Dict[str, str]]
    ) -> None:
        """
        在下一步 ENrunH 之前，把 PLC/SCADA 的控制命令写到 EPANET 的 link status 里。
        commands 示例：
        {
            "pumps": {"PUMP1": "OPEN" / "CLOSED"},
            "valves": {"VALVE1": "OPEN" / "CLOSED"},
        }
        """
        pumps = (commands or {}).get("pumps", {}) or {}
        valves = (commands or {}).get("valves", {}) or {}

        self.pump_commands = {pid: str(cmd) for pid, cmd in pumps.items()}
        self.valve_commands = {vid: str(cmd) for vid, cmd in valves.items()}

        if self._en is None:
            raise RuntimeError("Simulator not initialized. Call reset() before sending commands.")

        # Pumps
        for pump_id, cmd in self.pump_commands.items():
            idx = self.link_name_to_index.get(pump_id)
            if idx is None:
                continue
            status = 1.0 if str(cmd).upper() in {"ON", "OPEN", "1", "TRUE"} else 0.0
            self._en.ENsetlinkvalue(idx, EN.STATUS, status)

        # Valves
        for valve_id, cmd in self.valve_commands.items():
            idx = self.link_name_to_index.get(valve_id)
            if idx is None:
                continue
            status = 1.0 if str(cmd).upper() in {"ON", "OPEN", "1", "TRUE"} else 0.0
            self._en.ENsetlinkvalue(idx, EN.STATUS, status)

    def step(self) -> Optional[Dict]:
        """
        推进一步水力模型，并返回这一时刻的物理快照。
        """
        if self.finished:
            return None
        if self._en is None:
            raise RuntimeError("Simulator not initialized. Call reset() before stepping.")

        # 返回当前时间（秒）
        t = self._en.ENrunH()
        self.current_time_s = float(t)

        tanks: Dict[str, float] = {}
        pumps: Dict[str, str] = {}
        valves: Dict[str, str] = {}

        # 读水箱水位：head - elevation
        for tank_id in self.tank_ids:
            nidx = self.node_name_to_index.get(tank_id)
            if nidx is None:
                continue
            head = float(self._en.ENgetnodevalue(nidx, EN.HEAD))
            elev = float(self._en.ENgetnodevalue(nidx, EN.ELEVATION))
            level = head - elev
            if level < 0:
                level = 0.0  # 简单防一下数值小负数
            tanks[tank_id] = level

        # 读水泵状态
        for pump_id in self.pump_ids:
            lidx = self.link_name_to_index.get(pump_id)
            if lidx is None:
                continue
            status = float(self._en.ENgetlinkvalue(lidx, EN.STATUS))
            pumps[pump_id] = "ON" if status > 0.5 else "OFF"

        # 读阀门状态
        for valve_id in self.valve_ids:
            lidx = self.link_name_to_index.get(valve_id)
            if lidx is None:
                continue
            status = float(self._en.ENgetlinkvalue(lidx, EN.STATUS))
            valves[valve_id] = "OPEN" if status > 0.5 else "CLOSED"

        snapshot = self._build_snapshot(tanks, pumps, valves)
        # 推进到下一个时间步
        tstep = self._en.ENnextH()
        # tstep == 0 表示仿真结束
        if tstep <= 0 or self.current_time_s >= self.duration_seconds:
            self.finished = True
            self.close()

        return snapshot

    def close(self) -> None:
        if self._en is None:
            return
        try:
            self._en.ENcloseH()
        except Exception:
            pass
        try:
            self._en.ENclose()
        except Exception:
            pass
        self._en = None

    def _build_snapshot(
        self, tanks: Dict[str, float], pumps: Dict[str, str], valves: Dict[str, str]
    ) -> Dict:
        return {
            "time": self.current_time_s,
            "tanks": tanks,
            "pumps": pumps,
            "valves": valves,
        }

    def _read_state(self, time_override: Optional[float] = None) -> Dict:
        if self._en is None:
            raise RuntimeError("Simulator not initialized. Call reset() before reading state.")

        tanks: Dict[str, float] = {}
        pumps: Dict[str, str] = {}
        valves: Dict[str, str] = {}

        for tank_id in self.tank_ids:
            nidx = self.node_name_to_index.get(tank_id)
            if nidx is None:
                continue
            head = float(self._en.ENgetnodevalue(nidx, EN.HEAD))
            elev = float(self._en.ENgetnodevalue(nidx, EN.ELEVATION))
            level = head - elev
            if level < 0:
                level = 0.0
            tanks[tank_id] = level

        for pump_id in self.pump_ids:
            lidx = self.link_name_to_index.get(pump_id)
            if lidx is None:
                continue
            status = float(self._en.ENgetlinkvalue(lidx, EN.STATUS))
            pumps[pump_id] = "ON" if status > 0.5 else "OFF"

        for valve_id in self.valve_ids:
            lidx = self.link_name_to_index.get(valve_id)
            if lidx is None:
                continue
            status = float(self._en.ENgetlinkvalue(lidx, EN.STATUS))
            valves[valve_id] = "OPEN" if status > 0.5 else "CLOSED"

        self.current_time_s = float(self.current_time_s if time_override is None else time_override)
        return self._build_snapshot(tanks, pumps, valves)



def make_physical_simulator(inp_path: Path, sim_cfg: Dict) -> object:
    mode = sim_cfg["simulation"].get("mode", "closed_loop")
    # if mode == "open_loop":
    #     logger.info("Running simulation in OPEN-LOOP mode (precomputed trajectory).")
    #     return OpenLoopPhysicalSimulator(
    #         inp_path, sim_cfg["simulation"]["duration_hours"], sim_cfg["simulation"]["step_minutes"]
    #     )
    # logger.info("Running simulation in CLOSED-LOOP mode (EPANET toolkit step-wise, no network).")
    return ClosedLoopPhysicalSimulator(inp_path, sim_cfg)
