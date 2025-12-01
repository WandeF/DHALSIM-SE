import json
from typing import Any, Dict


def encode_plc_request(plc_state: Dict[str, Any]) -> bytes:
    return json.dumps(plc_state).encode("utf-8")


def decode_plc_request(payload: bytes) -> Dict[str, Any]:
    return json.loads(payload.decode("utf-8"))


def encode_scada_reply(reply: Dict[str, Any]) -> bytes:
    return json.dumps(reply).encode("utf-8")


def decode_scada_reply(payload: bytes) -> Dict[str, Any]:
    return json.loads(payload.decode("utf-8"))
