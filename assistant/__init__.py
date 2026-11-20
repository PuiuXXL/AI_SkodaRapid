"""DriveMate assistant (P3): LLM copilot, voice and phone.

Public entry points used by core (DriveMate-PLAN-FINAL.md, section 13 interfaces):

* ``assistant.client.handle_event(event, state) -> list[Action]`` - events to actions,
  with a 2.5 s deadline and fixed fallback texts;
* ``assistant.refusal.is_refusal(text) -> bool`` - deterministic refusal detection (D10);
* ``assistant.router.router`` - FastAPI router mounted by core (``/tts/{id}.mp3``,
  ``/media/{track_id}.mp3``).

See docs/assistant.md for the full description.
"""
