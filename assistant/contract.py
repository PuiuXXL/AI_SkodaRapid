"""Single import point for the DriveMate contract inside ``assistant/``.

Every module of the assistant imports contract types from here::

    from assistant.contract import Action, Event, State

How the switch works:

1. If ``shared/contracts.py`` (owned by P2) exists, each name below is taken from it.
2. Any name that ``shared/contracts.py`` does not define yet is taken from the
   temporary copy ``assistant/_TEMP_contract_DELETE_LATER.py`` and a warning is
   logged, so the gap is visible.
3. If ``shared/contracts.py`` does not exist at all, everything comes from the
   temporary copy.

So when P2 publishes the real contract nothing has to be edited here: run
``pytest tests/assistant`` and delete the temporary file once
:data:`USING_SHARED_CONTRACT` is True and no warning is printed.
"""

from __future__ import annotations

import importlib
import logging

from assistant import _TEMP_contract_DELETE_LATER as _temp

log = logging.getLogger("drivemate.assistant.contract")

#: Names the assistant needs from the contract.
__all__ = [
    "CONTRACT_VERSION",  # noqa: F822
    "EVENT_TYPES",  # noqa: F822
    "Action",  # noqa: F822
    "ActionType",  # noqa: F822
    "Addressee",  # noqa: F822
    "Event",  # noqa: F822
    "Message",  # noqa: F822
    "Occupant",  # noqa: F822
    "Poi",  # noqa: F822
    "Reminder",  # noqa: F822
    "ReminderTrigger",  # noqa: F822
    "SafetyLevel",  # noqa: F822
    "State",  # noqa: F822
]

try:
    _shared = importlib.import_module("shared.contracts")
except ImportError:
    _shared = None

#: True when at least part of the contract comes from ``shared/contracts.py``.
USING_SHARED_CONTRACT: bool = _shared is not None

#: Names that still come from the temporary copy (empty = temp file can be deleted).
MISSING_FROM_SHARED: list[str] = []

for _name in __all__:
    if _shared is not None and hasattr(_shared, _name):
        globals()[_name] = getattr(_shared, _name)
    else:
        globals()[_name] = getattr(_temp, _name)
        if _shared is not None:
            MISSING_FROM_SHARED.append(_name)

if MISSING_FROM_SHARED:
    log.warning(
        "shared/contracts.py exists but does not define %s; using the temporary "
        "copy in assistant/_TEMP_contract_DELETE_LATER.py for them.",
        ", ".join(MISSING_FROM_SHARED),
    )
