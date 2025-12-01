from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from wntr.network import WaterNetworkModel

from physical.controls_parser import parse_controls_from_inp, ControlRule


LOGIC_MAP = {
    ("BELOW", "OPEN"): "open_if_below",
    ("BELOW", "CLOSED"): "close_if_below",
    ("ABOVE", "OPEN"): "open_if_above",
    ("ABOVE", "CLOSED"): "close_if_above",
}


def _infer_element_type(model: WaterNetworkModel, link_id: str) -> str:
    link = model.get_link(link_id)
    klass = link.__class__.__name__.lower()
    if "pump" in klass:
        return "pump"
    if "valve" in klass:
        return "valve"
    return "link"


def _node_type(model: WaterNetworkModel, node_id: str) -> str:
    node = model.get_node(node_id)
    klass = node.__class__.__name__.lower()
    if "tank" in klass:
        return "tank"
    if "reservoir" in klass:
        return "reservoir"
    return "junction"


def build_runtime_plc_config(user_plc_config: Dict, inp_path: Path | str) -> Dict:
    """
    Merge minimal user PLC entries (id, element_id, ip) with inferred roles/types/logic
    from the INP [CONTROLS] section. Returns a full PLC config dict consumable by
    SCADA/PLC code.
    """
    inp_path = Path(inp_path)
    model = WaterNetworkModel(str(inp_path))
    controls = parse_controls_from_inp(inp_path)

    # Index minimal PLC entries by element_id.
    user_by_elem = {plc["element_id"]: plc for plc in user_plc_config.get("plcs", [])}

    runtime_plcs: List[Dict] = []
    sensor_nodes: set[str] = set()

    for ctl in controls:
        mode = LOGIC_MAP.get((ctl.comparator, ctl.action))
        if mode is None:
            continue

        minimal = user_by_elem.get(ctl.link_id)
        if minimal is None:
            # If no user entry, synthesize a PLC id/ip placeholder.
            minimal = {
                "id": f"PLC_{ctl.link_id}",
                "element_id": ctl.link_id,
                "ip": "10.0.0.250",
            }

        plc_entry = {
            "id": minimal["id"],
            "element_id": minimal["element_id"],
            "ip": minimal.get("ip", "10.0.0.250"),
            "role": "actuator",
            "type": _infer_element_type(model, ctl.link_id),
            "logic": {
                "mode": mode,
                "node_id": ctl.node_id,
                "threshold": ctl.threshold,
            },
        }
        runtime_plcs.append(plc_entry)
        sensor_nodes.add(ctl.node_id)

    # Add sensor PLCs for conditioning nodes if missing.
    existing_sensor_nodes = {plc["element_id"] for plc in runtime_plcs if plc.get("role") == "sensor"}
    for node_id in sensor_nodes:
        if node_id in existing_sensor_nodes:
            continue
        runtime_plcs.append(
            {
                "id": f"PLC_SENSOR_{node_id}",
                "element_id": node_id,
                "ip": f"10.0.1.{len(runtime_plcs)+10}",
                "role": "sensor",
                "type": _node_type(model, node_id),
                "logic": {"mode": "report_level", "node_id": node_id},
            }
        )

    runtime_cfg = {
        "scada": user_plc_config.get("scada", {}),
        "plcs": runtime_plcs,
    }
    return runtime_cfg
