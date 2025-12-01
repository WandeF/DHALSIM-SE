import logging
from pathlib import Path
from typing import Dict, List, Optional

from wntr.network import WaterNetworkModel
from wntr.sim import WNTRSimulator
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

    def __init__(self, inp_path: str, duration_hours: float, step_minutes: float) -> None:
        self.inp_path = Path(inp_path)
        self.duration_hours = duration_hours
        self.step_minutes = step_minutes
        self.step_seconds = int(step_minutes * 60)
        self.duration_seconds = int(duration_hours * 3600)

        self.current_time_s = 0.0
        self.finished = False

        self.tank_ids: List[str] = []
        self.pump_ids: List[str] = []
        self.valve_ids: List[str] = []
        self.link_name_to_index: Dict[str, int] = {}
        self.node_name_to_index: Dict[str, int] = {}

        self.pump_commands: Dict[str, str] = {}
        self.valve_commands: Dict[str, float] = {}

        # EPANET engine handle，会在 initialize 里真正打开
        self._en = enData.ENepanet()

    def initialize(self) -> None:
        if not self.inp_path.exists():
            raise FileNotFoundError(f"Missing EPANET file: {self.inp_path}")

        # 打开 EPANET 工具箱引擎
        self._en.ENopen(str(self.inp_path), "closed_loop.rpt", "")

        self._en.ENsettimeparam(EN.DURATION, int(self.duration_seconds))
        self._en.ENsettimeparam(EN.HYDSTEP, int(self.step_seconds))
        self._en.ENsettimeparam(EN.REPORTSTEP, int(self.step_seconds))
        self._en.ENsettimeparam(EN.REPORTSTART, 0)

        # 用 WNTR 读网络，拿到 ID 列表
        wn = WaterNetworkModel(str(self.inp_path))
        self.tank_ids = wn.tank_name_list
        self.pump_ids = wn.pump_name_list
        self.valve_ids = wn.valve_name_list

        # 建立 name -> index 映射表，方便后续 ENgetlinkvalue/ENgetnodevalue
        for lid in wn.link_name_list:
            idx = self._en.ENgetlinkindex(lid)
            self.link_name_to_index[lid] = idx
        for nid in wn.node_name_list:
            idx = self._en.ENgetnodeindex(nid)
            self.node_name_to_index[nid] = idx

        # 打开水力分析
        self._en.ENopenH()
        # 0 表示从当前时间开始
        self._en.ENinitH(0)

        self.current_time_s = 0.0
        self.finished = False
        logger.info("Closed-loop: opened EPANET toolkit for %s", self.inp_path)

    def apply_actuator_commands(
        self, pump_commands: Dict[str, str], valve_commands: Dict[str, float]
    ) -> None:
        """
        在下一步 ENrunH 之前，把 PLC/SCADA 的控制命令写到 EPANET 的 link status 里。
        """
        self.pump_commands = pump_commands.copy()
        self.valve_commands = valve_commands.copy()

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

        snapshot = {
            "time": self.current_time_s,
            "tanks": tanks,
            "pumps": pumps,
            "valves": valves,
        }
        # 推进到下一个时间步
        tstep = self._en.ENnextH()
        # tstep == 0 表示仿真结束
        if tstep <= 0 or self.current_time_s >= self.duration_seconds:
            self.finished = True
            self.close()

        return snapshot

    def close(self) -> None:
        try:
            self._en.ENcloseH()
        except Exception:
            pass
        try:
            self._en.ENclose()
        except Exception:
            pass



def make_physical_simulator(inp_path: Path, sim_cfg: Dict) -> object:
    mode = sim_cfg["simulation"].get("mode", "closed_loop")
    # if mode == "open_loop":
    #     logger.info("Running simulation in OPEN-LOOP mode (precomputed trajectory).")
    #     return OpenLoopPhysicalSimulator(
    #         inp_path, sim_cfg["simulation"]["duration_hours"], sim_cfg["simulation"]["step_minutes"]
    #     )
    # logger.info("Running simulation in CLOSED-LOOP mode (EPANET toolkit step-wise, no network).")
    return ClosedLoopPhysicalSimulator(
        inp_path, sim_cfg["simulation"]["duration_hours"], sim_cfg["simulation"]["step_minutes"]
    )
