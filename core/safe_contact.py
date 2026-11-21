"""C10: the trusted contact. A tired driver refuses the assistant; a RULE (never the LLM) decides what happens.

```
fatigue dialog on (fatigue_high in the last safe_contact.dialog_s) AND F >= safe_contact.fatigue_min
AND a refusal: "lasă-mă în pace" (assistant.refusal) / ✋ / 👎 in the KSS question / LLM stay_silent(driver_refused)
  -> "Ok, te las în pace." (P3's clip, from driver_refused)
  -> assistant.muted_until = now + refusal_mute_min      (P3-P4 silent; alarms and SOS unaffected)
  -> "Îi dau de veste lui {contact}." when announce = true   (principle 9: nothing behind the driver's back)
  -> if the profile has a contact AND consent AND safe_contact.cooldown_min has passed:
       the SMS from the driver's phone + the yellow notice on DriveMate Contact (SOS-like channels)
       safe_contact.notified_ts = now; event safe_contact_notified (source RULE)
```

The contact's answer is an ordinary message (F2 applies, and it is delivered even while the assistant is silent).
Once it has been read, the assistant may propose a stop **once**, even while silent: core sends that single
``stop_suggested`` with the silence lifted for it.

The profile (``profiles/<driver>/profile.json``, P4) fills ``state.safe_contact`` every ``profile_check_s``.
Channels report ``not_connected`` until the phone part (SMS) and P4's Contact page (``push_safe_contact``) are wired.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from core import clips, profiles
from core.reminders import pick_stop
from core.settings import render, template, th
from shared.contracts import Message, SafeContactNotice, State

if TYPE_CHECKING:
    from pathlib import Path

    from core.engine import Engine

log = logging.getLogger("drivemate.core.safe_contact")

NoticeChannel = Callable[[SafeContactNotice], str]


def _contact_page(notice: SafeContactNotice) -> str:
    """The yellow "{name} pare obosit" notice on DriveMate Contact (P4)."""
    try:
        push = importlib.import_module("integrations.contact_app").push_safe_contact
    except (ImportError, AttributeError):
        return "not_connected"
    push(notice)
    return "ok"


def _not_connected(_: SafeContactNotice) -> str:
    return "not_connected"


def default_channels() -> dict[str, NoticeChannel]:
    return {"sms": _not_connected, "contact_page": _contact_page}


def elapsed_text(minutes: float) -> str:
    hours, rest = divmod(round(minutes), 60)
    if hours:
        return render("safe_contact", "elapsed_hours", h=hours, m=rest)
    return render("safe_contact", "elapsed_minutes", m=rest)


class SafeContactRule:
    def __init__(self, engine: Engine, channels: dict[str, NoticeChannel] | None = None,
                 profiles_root: Path | None = None) -> None:
        self.engine = engine
        engine.safe_contact = self
        self.channels = default_channels() if channels is None else dict(channels)
        self.profiles_root = profiles_root
        engine.add_tick_listener(self.on_tick)
        engine.add_reset_listener(self.reset)
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.dialog_until = float("-inf")
        self.dialog_fatigue = 0.0
        self.refused_at: float | None = None
        self.notified_ts: float | None = None
        self.stop_offered_for: str | None = None
        self.next_profile_check = float("-inf")
        self.last_notice: SafeContactNotice | None = None

    # --- the fatigue dialog --------------------------------------------------------------------------------------

    def fatigue_dialog_started(self, now: float, fatigue: float) -> None:
        """fatigue_high went to the assistant: the KSS conversation is on."""
        self.dialog_until = now + float(th("safe_contact", "dialog_s"))
        self.dialog_fatigue = fatigue

    def fatigue_dialog(self, state: State, now: float) -> bool:
        """A refusal now counts for C10 (F at its peak in this dialog, the score may dip a little meanwhile)."""
        fatigue = max(state.assessment.fatigue, self.dialog_fatigue)
        return now < self.dialog_until and fatigue >= float(th("safe_contact", "fatigue_min"))

    # --- the rule ------------------------------------------------------------------------------------------------

    def on_refusal(self, now: float, channel: str) -> bool:
        """A refusal (after "Ok, te las în pace."). Returns True when C10 applied."""
        state = self.engine.state
        if not self.fatigue_dialog(state, now):
            return False
        if self.refused_at is not None and now - self.refused_at < 5.0:
            return False  # the same refusal reported twice (keyword, then the LLM's stay_silent)
        self.refused_at = now
        self.dialog_until = float("-inf")  # the dialog is over
        mute_min = float(th("refusal_mute_min"))
        state.assistant.muted_until = now + mute_min * 60.0
        state.assistant.mute_reason = "driver_refused"
        self.engine.log_event("driver_refused", now, channel=channel, text=f"Asistentul tace {mute_min:.0f} min. "
                              "Alarmele și SOS-ul rămân active.", muted_until=state.assistant.muted_until)
        self._notify(state, now)
        return True

    def _notify(self, state: State, now: float) -> None:
        contact = state.safe_contact
        cooldown_s = float(th("safe_contact", "cooldown_min")) * 60.0
        if not contact.configured:
            reason = "no_contact"
        elif not contact.consent:
            reason = "no_consent"
        elif self.notified_ts is not None and now - self.notified_ts < cooldown_s:
            reason = "cooldown"
        else:
            reason = None
        if reason is not None:
            self.engine.log_event("safe_contact_skipped", now, text=f"Contactul nu e anunțat ({reason}).",
                                  reason=reason)
            return
        if contact.announce and contact.name:  # said only when the contact really is told
            clip_id = str(template("clips", "notify_contact")).format(contact=contact.name.lower())
            self.engine.say(clip_id, render("safe_contact", "announce", contact_name=contact.name), prefix="sc")
        notice = self.build_notice(state, now)
        self.last_notice = notice
        results: dict[str, str] = {}
        for name, channel in self.channels.items():
            try:
                results[name] = channel(notice)
            except Exception as exc:  # one broken channel must not stop the others
                log.exception("safe contact channel %s failed", name)
                results[name] = f"error: {exc.__class__.__name__}"
        self.notified_ts = now
        contact.notified_ts = now
        self.engine.log_event("safe_contact_notified", now, text=notice.text, contact=contact.name,
                              channels=results)

    def build_notice(self, state: State, now: float) -> SafeContactNotice:
        """The fixed text for the contact (templates.yaml, no LLM)."""
        driver, _ = clips.person_names(state)
        trip, pos = state.trip, state.trip.pos
        fields = {"driver_name": clips.display(driver), "elapsed_text": elapsed_text(trip.elapsed_min),
                  "maps_url": render("links", "maps", lat=pos.lat, lon=pos.lon)}
        if trip.eta_min is not None:
            text = render("safe_contact", "sms", eta_min=round(trip.eta_min), **fields)
        else:
            text = render("safe_contact", "sms_no_eta", **fields)
        return SafeContactNotice.model_validate({
            "contact_name": state.safe_contact.name or "", "driver_name": fields["driver_name"],
            "elapsed_min": trip.elapsed_min, "eta_min": trip.eta_min, "pos": pos.model_dump(),
            "maps_url": fields["maps_url"], "ts": now, "text": text,
        })

    # --- the contact's answer (F8) -------------------------------------------------------------------------------

    def is_contact_reply(self, message: Message) -> bool:
        contact = self.engine.state.safe_contact
        return bool(contact.name) and self.notified_ts is not None and message.from_ == contact.name \
            and (message.ts or 0.0) >= self.notified_ts

    def reply_read(self, message: Message, now: float) -> dict[str, object] | None:
        """The contact's answer was read: the one stop proposal allowed even while silent (event data or None)."""
        state = self.engine.state
        state.safe_contact.last_reply_msg_id = message.id
        if self.stop_offered_for is not None:
            return None
        stop = pick_stop(state)
        if stop is None:
            return None
        self.stop_offered_for = message.id
        return {**stop, "once_while_muted": True}

    # --- every tick ----------------------------------------------------------------------------------------------

    def on_tick(self, state: State, now: float) -> None:
        if now >= self.next_profile_check:
            self.next_profile_check = now + float(th("safe_contact", "profile_check_s"))
            driver, _ = clips.person_names(state)
            fields = profiles.safe_contact(profiles.load(driver, self.profiles_root))
            for key, value in fields.items():
                setattr(state.safe_contact, key, value)
        state.safe_contact.notified_ts = self.notified_ts
        muted = state.assistant.muted_until
        if muted is not None and now >= muted:
            state.assistant.muted_until, state.assistant.mute_reason = None, None
            self.engine.log_event("assistant_unmuted", now, text="Asistentul poate vorbi din nou.")
