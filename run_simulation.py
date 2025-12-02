import logging
import os
from typing import Any, Dict, List

import yaml

from middleware.middleware import middleware
from physical.physical_sim import ClosedLoopPhysicalSimulator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("wntr").setLevel(logging.ERROR)
logging.getLogger("wntr.sim").setLevel(logging.ERROR)


def _calc_total_steps(sim_cfg: Dict[str, Any]) -> int:
    """Calculate total steps from config; fall back to duration/step if num_steps missing."""
    if "num_steps" in sim_cfg:
        return int(sim_cfg.get("num_steps", 0))
    sim = sim_cfg.get("simulation", {})
    duration_hours = float(sim.get("duration_hours", 0))
    step_minutes = float(sim.get("step_minutes", 1))
    if step_minutes <= 0:
        raise ValueError("simulation.step_minutes must be positive")
    return int(duration_hours * 60 / step_minutes)


def main() -> None:
    # 1. 读取仿真配置
    with open("config/sim_config.yaml", "r", encoding="utf-8") as f:
        sim_cfg = yaml.safe_load(f)

    inp_path = os.path.join("water_network", "minitown.inp")
    plant = ClosedLoopPhysicalSimulator(inp_path, sim_cfg)

    records: List[Dict[str, Any]] = []

    # 2. 重置物理模型
    state = plant.reset()
    total_steps = _calc_total_steps(sim_cfg)
    logger.info("Starting closed-loop simulation for %d steps", total_steps)

    # 3. 主循环：物理一步 -> 中间层 -> 应用控制
    for step in range(total_steps):
        # 3.1 物理前进一步，得到当前状态快照
        state = plant.step()
        if state is None:
            break

        # 3.2 CPS 中间层（未来会加入 OpenPLC/ns-3/SCADA）
        commands = middleware(state)

        # 3.3 根据中间层输出的命令，更新物理执行器状态
        plant.apply_actuator_commands(commands)

        # 3.4 可选：记录数据
        records.append(
            {
                "timestep": step,
                "state": state,
                "commands": commands,
            }
        )

    plant.close()
    logger.info("Simulation complete with %d records", len(records))

    # 4. 可选：保存 records / 调用原来的保存函数
    # save_records(records, output_dir)


if __name__ == "__main__":
    main()
