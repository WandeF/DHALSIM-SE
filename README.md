# mini_water_cps

Minimal co-simulation skeleton for a water distribution CPS using WNTR for the physics and a Mininet/MiniCPS-style network layout for PLC–SCADA exchanges. The goal is to provide a small, hackable baseline for adding attacks/defenses later.

## Quick start
1) Place an EPANET network at `water_network/minitown.inp` (copy from DHALSIM `examples/minitown_topology` or your own file).
2) Adjust `config/plc_config.yaml` and `config/sim_config.yaml` for your scenario.
3) Install deps: `pip install -r requirements.txt` (Mininet and MiniCPS are usually installed via apt/source; see notes inside `requirements.txt`).
4) Run: `python run_simulation.py`.

## What this repo contains
- Step-based physical wrapper (`physical/physical_sim.py`) around WNTR.
- Logical PLC/SCADA scaffolding and JSON message helpers under `ics_network/`.
- Mininet topology builder stub (`ics_network/topology.py`) to allocate a star network.
- Placeholder attack hook under `attacks/`.

This version keeps PLC–SCADA exchanges in-process for simplicity; you can later swap in real TCP flows over Mininet by reusing the same message format.

## PLC configuration model
- User-facing `config/plc_config.yaml` is intentionally minimal: PLC id, element_id, and IP.
- At runtime we parse the INP `[CONTROLS]` (see `config/runtime_plc_builder.py` and `physical/controls_parser.py`) to infer roles/types/logic modes (`open_if_below/above`, `close_if_below/above`) and synthesize any missing sensor PLCs.
- The expanded PLC config is what SCADA/PLC logic consumes during simulation.

## Closed-loop roadmap
- `physical/physical_sim.py` currently reads from a precomputed WNTR trajectory (open-loop). It exposes `apply_actuator_commands` and notes where EPANET user_status updates would be applied when moving to a per-step closed-loop hydraulic run.
