from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ControlRule:
    link_id: str
    node_id: str
    comparator: str  # "BELOW" or "ABOVE"
    action: str      # "OPEN" or "CLOSED"
    threshold: float


def parse_controls_from_inp(inp_path: Path | str) -> List[ControlRule]:
    """
    Parse a limited subset of EPANET [CONTROLS] lines from an INP file.
    Supported pattern:
        LINK <link_id> OPEN|CLOSED IF NODE <node_id> BELOW|ABOVE <threshold>
    Lines not matching this pattern are ignored.
    """
    path = Path(inp_path)
    if not path.exists():
        raise FileNotFoundError(f"INP not found: {path}")

    controls: List[ControlRule] = []
    in_controls = False
    pattern = re.compile(
        r"LINK\s+(\S+)\s+(OPEN|CLOSED)\s+IF\s+NODE\s+(\S+)\s+(BELOW|ABOVE)\s+([0-9eE\.\+\-]+)",
        re.IGNORECASE,
    )

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.upper().startswith("[CONTROLS]"):
                in_controls = True
                continue
            if in_controls and line.startswith("["):
                # Reached next section
                break
            if not in_controls:
                continue
            m = pattern.match(line)
            if not m:
                continue
            link_id, action, node_id, comparator, threshold = m.groups()
            controls.append(
                ControlRule(
                    link_id=link_id,
                    node_id=node_id,
                    comparator=comparator.upper(),
                    action=action.upper(),
                    threshold=float(threshold),
                )
            )
    return controls
