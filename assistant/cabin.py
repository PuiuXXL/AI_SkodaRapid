"""Read-only helpers about who is in the car, derived from the state (plan G1).

The state lists occupants by seat (``driver``, ``front_right``, ``rear``) with a
profile name such as ``"andrei"``. These helpers turn that into what the assistant
needs: display names for texts, whether a child is on board, whether anyone else
could hear a private message, etc.
"""

from __future__ import annotations

from typing import Optional

from assistant.contract import Occupant, State


def display_name(profile: Optional[str]) -> Optional[str]:
    """Turn a profile id into a spoken name: ``"andrei"`` -> ``"Andrei"``.

    Args:
        profile: Profile id from the state, or None.

    Returns:
        The capitalised name, or None when the profile is unknown.
    """
    if not profile:
        return None
    return " ".join(part.capitalize() for part in profile.replace("_", " ").split())


def occupant(state: State, seat: str) -> Optional[Occupant]:
    """Return the first occupant on a seat (``driver``, ``front_right``, ``rear``)."""
    return next((o for o in state.occupants if o.seat == seat), None)


def driver_name(state: State) -> Optional[str]:
    """Spoken name of the driver, or None when not recognised."""
    person = occupant(state, "driver")
    return display_name(person.profile) if person else None


def passenger_name(state: State) -> Optional[str]:
    """Spoken name of the front passenger, only if the passenger camera sees them."""
    person = occupant(state, "front_right")
    if person is None or not state.passenger.present:
        return None
    return display_name(person.profile)


def child_name(state: State) -> Optional[str]:
    """Spoken name of the first declared child, or None."""
    person = next((o for o in state.occupants if o.role == "child"), None)
    return display_name(person.profile) if person else None


def has_child(state: State) -> bool:
    """True when a child is on board (media must be ``kid_safe``, plan G4)."""
    return any(o.role == "child" for o in state.occupants)


def others_present(state: State) -> bool:
    """True when someone besides the driver could hear a message (plan F2: ask first)."""
    return state.passenger.present or any(o.seat == "rear" for o in state.occupants)


def passenger_asleep(state: State) -> bool:
    """True when the front passenger is present and asleep (plan G3: low volume)."""
    return state.passenger.present and not state.passenger.awake


def known_people(state: State) -> dict[str, Occupant]:
    """Map of lower-case spoken names (and seats) to occupants, for ``delegate``.

    Returns:
        e.g. ``{"maria": <front_right>, "front_right": <front_right>, ...}``.
    """
    people: dict[str, Occupant] = {}
    for person in state.occupants:
        people[person.seat] = person
        if person.profile:
            people[person.profile.lower()] = person
    if "front_right" in people and not state.passenger.present:
        # The passenger camera does not see anyone: nobody to delegate to there.
        front = people.pop("front_right")
        if front.profile:
            people.pop(front.profile.lower(), None)
    return people
