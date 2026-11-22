# DriveMate — CodeLap Hackathon 2026

The official-template pitch deck, speaker script and source template live here so a fresh clone includes the presentation.

## Files

| File | Purpose |
| --- | --- |
| [DriveMate_CodeLap_2026_updated.pptx](DriveMate_CodeLap_2026_updated.pptx) | Current editable deck, seven slides, Romanian speaker notes |
| [pitch.md](pitch.md) | Complete spoken pitch, slide cues and source references |
| [Official CodeLap template](template/CodeLap_Hackathon_2026_Official.pptx) | Unmodified source template provided for the event |

The earlier `DriveMate_CodeLap_2026.pptx` is a local working copy. Use the **updated** deck linked above: it includes the icebreaker added after the first version.

## Presenting

Open the updated PPTX in PowerPoint and use Presenter View to see the full script. Aim for approximately **3 minutes 10 seconds**, including the joke and the two-second pause. Rehearse aloud; timings are cues, not slide auto-advance settings. All slides use a subtle fade.

The opening is:

> Mașinile noi primesc monitorizarea șoferului prin regulament. Škoda noastră din 2016 o primește prin hackathon.

Pause briefly, then ask the seated audience to close their eyes for **two real seconds**. On the next slide, explain that at 100 km/h this is about **56 metres** travelled. This is an audience exercise, never something to demonstrate while driving.

## Narrative

1. Icebreaker, then the two-second exercise.
2. Distraction expressed as distance: 100 ÷ 3.6 × 2 = 55.6 m.
3. Euro NCAP 2026: reliability and acceptance alongside monitoring.
4. The idea, contextual monitoring and useful voice features.
5. Safety escalation and the priority of deterministic rules.
6. Cameras → perception → context → rules → assistant; shared contracts, dashboard, simulator and integration.
7. Configurable comfort preferences and the goal of an assistant drivers choose to keep active.

## Branding and editing

The deck retains the official template's slide size, background, theme and CodeLap marks. It adds the approved DriveMate full logo, cyan accents and transparent PNG illustrations reused from the platform. Text and pipeline shapes remain editable. Segoe UI supports Romanian characters on Windows.

The DriveMate asset sources are [brand](../dashboard/public/brand/) and [illustrations](../dashboard/src/voice/illustrations/). Keep both DriveMate and CodeLap logos visible when editing. Critical safety priorities must remain clear even when describing configurable behaviour.

The original template is preserved separately. Temporary slide renders and packaging files belong in the ignored `.pitch-build/` folder, not in the deliverable.

## Evidence and scope

- [Euro NCAP protocol changes for 2026](https://www.euroncap.com/press-media/euro-ncap-announces-2026-protocol-changes-to-tackle-modern-driving-risks/) is the official assessment-programme update. It is not a DriveMate evaluation or a user study proving retention.
- [European Commission, new rules effective July 2026](https://commission.europa.eu/news-and-media/news/safer-cars-safer-roads-new-rules-take-effect-2026-07-08_en) supports the opening's regulatory context for new passenger cars and vans. It does not require retrofitting the project's 2016 vehicle.
- DriveMate is a prototype. SOS is a software escalation flow whose delivery depends on configured integrations; the deck does not claim automatic 112 dispatch, production certification or physical vehicle control.
- Keeping the assistant active is a design goal to validate with users. Comfort settings do not override critical safety rules.

The deck was checked for package integrity and slide geometry. Native PowerPoint playback should be checked on the presentation computer, especially fonts, logos and Presenter View notes.
