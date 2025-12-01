import logging
import warnings
from csv import DictWriter
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import yaml

from ics_network.plc_node import PlcLogic
from ics_network.scada_node import ScadaServer
from ics_network.topology import WaterCpsTopology
from physical.physical_sim import PhysicalSimulator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
warnings.filterwarnings("ignore")

logging.getLogger("wntr").setLevel(logging.ERROR)
logging.getLogger("wntr.sim").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def prepare_output_dir(inp_path: Path, repo_root: Path) -> Path:
    output_root = repo_root / "output"
    output_root.mkdir(exist_ok=True, parents=True)
    base_name = inp_path.stem + "_output"
    idx = 1
    while True:
        candidate = output_root / f"{base_name}_{idx}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        idx += 1


def main() -> None:
    repo_root = Path(__file__).parent
    plc_cfg = load_yaml(repo_root / "config" / "plc_config.yaml")
    sim_cfg = load_yaml(repo_root / "config" / "sim_config.yaml")

    inp_path = repo_root / "water_network" / "minitown.inp"
    phys = PhysicalSimulator(
        inp_path=inp_path,
        duration_hours=sim_cfg["simulation"]["duration_hours"],
        step_minutes=sim_cfg["simulation"]["step_minutes"],
    )
    phys.initialize()

    output_dir = prepare_output_dir(Path(phys.inp_path), repo_root)
    logger.info("Output directory: %s", output_dir)

    scada = ScadaServer(plc_cfg)
    plc_logics = {plc["id"]: PlcLogic(plc, inp_path=inp_path) for plc in plc_cfg.get("plcs", [])}

    network_cfg = sim_cfg.get("network", {})
    use_minicps = network_cfg.get("use_minicps", False)
    topo = None
    if use_minicps:
        topo = WaterCpsTopology(plc_cfg, network_cfg)
        topo.build()
        topo.start()
    else:
        logger.info("Mininet/MiniCPS disabled; running with in-process logical network only.")

    total_steps = int(
        sim_cfg["simulation"]["duration_hours"] * 60 / sim_cfg["simulation"]["step_minutes"]
    )
    logger.info("Starting co-simulation for %d steps", total_steps)

    pump_ids = []
    valve_ids = []
    tank_ids = []
    for plc in plc_cfg.get("plcs", []):
        if plc.get("type") == "pump":
            pump_ids.append(plc.get("element_id"))
        if plc.get("type") == "valve":
            valve_ids.append(plc.get("element_id"))
        if plc.get("type") == "tank":
            tank_ids.append(plc.get("element_id"))
    rows: List[Dict] = []

    for step in range(total_steps):
        physical_state = phys.step()

        for plc_id, plc_logic in plc_logics.items():
            request = plc_logic.build_request(physical_state)
            reply = scada.handle_plc_request(request)
            plc_logic.update_from_scada_reply(reply)

        pump_commands: Dict[str, str] = {}
        valve_commands: Dict[str, float] = {}
        for plc in plc_cfg.get("plcs", []):
            logic = plc_logics[plc["id"]]
            effect = logic.get_actuator_effect()
            if plc.get("type") == "pump":
                pump_commands.update(effect)
            if plc.get("type") == "valve":
                valve_commands.update(effect)

        phys.apply_actuator_commands(pump_commands, valve_commands)
        logger.info(
            "Step %d/%d: t=%ss pumps=%s valves=%s tanks=%s",
            step + 1,
            total_steps,
            physical_state.get("time"),
            physical_state.get("pumps", {}),
            physical_state.get("valves", {}),
            physical_state.get("tanks", {}),
        )

        row = {"time_s": physical_state.get("time")}
        for tid in tank_ids:
            row[f"tank_{tid}"] = physical_state.get("tanks", {}).get(tid)
        for pid in pump_ids:
            row[f"pump_{pid}"] = physical_state.get("pumps", {}).get(pid)
        for vid in valve_ids:
            row[f"valve_{vid}"] = physical_state.get("valves", {}).get(vid)
        rows.append(row)

    if topo is not None:
        topo.stop()
    logger.info("Simulation complete.")

    if rows:
        csv_path = output_dir / "timeseries.csv"
        fieldnames = ["time_s"]
        fieldnames += [f"tank_{tid}" for tid in tank_ids]
        fieldnames += [f"pump_{pid}" for pid in pump_ids]
        fieldnames += [f"valve_{vid}" for vid in valve_ids]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Wrote CSV to %s", csv_path)

        # Plot tank levels over time if present.
        tank_cols = [f"tank_{tid}" for tid in tank_ids]
        if tank_cols:
            plt.figure(figsize=(8, 4))
            times = [r["time_s"] for r in rows]
            for col in tank_cols:
                plt.plot(times, [r.get(col) for r in rows], label=col)
            plt.xlabel("Time (s)")
            plt.ylabel("Tank level")
            plt.title("Tank levels over time")
            plt.legend()
            plt.tight_layout()
            plot_path = output_dir / "tank_levels.png"
            plt.savefig(plot_path)
            plt.close()
            logger.info("Saved plot to %s", plot_path)


if __name__ == "__main__":
    main()
