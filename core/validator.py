"""C8: core checks every action of the assistant again before executing it ("validate de C").

P3 already validates against the same table; core does it once more because it owns safety and the state may have
changed while the LLM was answering (a P1 alarm in the meantime). An action is rejected when:

* its type is not in section 6, or is internal to the assistant (``search_media`` never reaches core);
* a parameter is missing (the typed models of ``shared.contracts``);
* the current level does not allow it (``ACTION_ALLOWED_LEVELS``; ``safety.level = null`` counts as P4): this is
  the veto, the LLM says nothing at P0-P2;
* it needs the driver's "yes" and did not get it (``ACTION_NEEDS_CONFIRMATION``; volume is the exception,
  ``NO_CONFIRMATION_PREFERENCES``).

Rejected actions go to the event log as ``action_rejected`` with the reason (plan section 6: "Orice altceva primit
de la LLM e respins și trecut în jurnal").
"""

from __future__ import annotations

from pydantic import ValidationError

from shared.contracts import (
    ACTION_ALLOWED_LEVELS,
    ACTION_NEEDS_CONFIRMATION,
    ACTION_TYPES,
    ASSISTANT_INTERNAL_ACTIONS,
    NO_CONFIRMATION_PREFERENCES,
    Action,
    State,
    parse_action,
)


def check(action: Action, state: State, *, confirmed: bool) -> str | None:
    """None when ``action`` may run now, else the reason it is rejected.

    Args:
        confirmed: True for actions the driver confirmed (released by the dialog manager after a "yes").
    """
    if action.type not in ACTION_TYPES:
        return "unknown_type"
    if action.type in ASSISTANT_INTERNAL_ACTIONS:
        return "internal_to_assistant"
    try:
        parse_action(action)
    except ValidationError as exc:
        return f"invalid:{exc.errors()[0]['loc'][-1] if exc.errors() else 'params'}"
    level = state.safety.level or "P4"
    if level not in ACTION_ALLOWED_LEVELS[action.type]:
        return f"level:{level}"
    exempt = action.type == "set_preference" and action.key in NO_CONFIRMATION_PREFERENCES
    if action.type in ACTION_NEEDS_CONFIRMATION and not confirmed and not exempt:
        return "needs_confirmation"
    return None
