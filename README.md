# mini_water_cps

Minimal co-simulation skeleton for a water distribution CPS using WNTR for the physics. The current default is a tiny, in-process closed loop: physical step → middleware placeholder → apply commands. Legacy PLC/SCADA/Mininet scaffolding is preserved under `legacy/` for later reference.

## Quick start
1) Place an EPANET network at `water_network/minitown.inp` (copy from DHALSIM `examples/minitown_topology` or your own file).
2) Adjust `config/sim_config.yaml` for your scenario.
3) Install deps: `pip install -r requirements.txt` (needs `wntr` at minimum).
4) Run the minimal loop: `python run_simulation.py` (or `python quick_test.py` for a smoke check).

## What this repo contains
- Step-based physical wrapper (`physical/physical_sim.py`) around WNTR/EPANET.
- Middleware placeholder (`middleware/middleware.py`) where OpenPLC/ns-3/SCADA logic will be attached.
- Legacy PLC/SCADA/Mininet scaffolding and attack hooks under `legacy/` (kept for reference, not used in the minimal loop).

The default loop keeps everything in-process for simplicity; you can later reintroduce networked PLC–SCADA flows by reviving the legacy code.

## Minimal closed loop (current default)
- `run_simulation.py` loads `config/sim_config.yaml`, opens `water_network/minitown.inp`, and steps the physics via `ClosedLoopPhysicalSimulator`.
- Each iteration: `state = plant.step()` → `commands = middleware(state)` → `plant.apply_actuator_commands(commands)`.
- `middleware` currently returns empty pump/valve commands; it is documented with TODOs for OpenPLC, ns-3, and SCADA integration.
