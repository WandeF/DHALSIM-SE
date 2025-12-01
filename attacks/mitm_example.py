"""
Placeholder for a simple man-in-the-middle attack module.

In a full setup, this could sniff PLC <-> SCADA JSON messages and modify
commands (e.g., force pumps OFF). For now we just keep a stub to show where
attack logic would be inserted.
"""


def intercept_and_modify(message: bytes) -> bytes:
    """Return the message unchanged; extend this with real MITM logic later."""
    return message
