# Hackathon requirements (CodeLap 2026, AI Drive)

> Extracted from the organizers' kick-off deck `Codelap Hackathon 2026_AI_Workshop.pptx` (Mentors Workshop).
> The deck is the authority; this file is a working summary. If they disagree, the deck wins.

The challenge: **build a driver-monitoring assistant that makes every drive safer.**
**Detect** (computer vision reads the driver's state) → **React** (an LLM turns it into an in-car alert or voice guidance) → **Show** (a live dashboard displays everything in real time).

The mentors are also the jury. They evaluate the live demo against R1–R4, apply the same Definition of Done to all teams, and consider the code, the documentation and the way of working.

---

## Mandatory requirements

| ID | Name | What the deck says |
|---|---|---|
| **R1** | Driver detection | Detect the driver's activity and attention with **computer vision**. Possible ideas (choosing one is not mandatory): eyes closed / drowsiness; looking left / right / down → distraction; phone detection; driver posture. |
| **R2** | In-car reaction | Based on the CV output from R1, trigger a reaction inside the car: alert, warning, dialogue, voice assist. **Using an LLM is required.** How to integrate it is up to the team. |
| **R3** | Live demo | Run **live on real data**. No post-processed videos or images with labels on top. Showing responses in a terminal is fine, as long as it runs live. |
| **R4** | Live dashboard | Show everything as it happens: **all categories and detections visible** in a live dashboard, plus a **live text/audio suggestion** based on the driver's attention level. |

## Optional: GenAI features

Natural-language explanations, passenger interaction, or RAG.

## What the organizers expect beyond the code

1. **Code and libraries:** a Git repo with the code and the libraries used, clearly listed and easy to run.
2. **Documentation:** a README with the chosen idea, the architecture and the steps to start the demo.
3. **Way of working:** regular commits, clear tasks and visible collaboration in Git.
4. **Full demo:** the full live flow: detection → LLM → alert → dashboard.

## Definition of Done

1. **Working demo**
   - Runs live on real data (camera feed).
   - No post-processed videos or labelled images.
   - Terminal output is fine if it is live.
2. **Visible in the demo**
   - Computer vision detections.
   - A live "dashboard".
   - A live text/audio suggestion from the LLM.
3. **Deliverables**
   - Code in the registered Git repo.
   - Documentation: idea, architecture, how to run.
   - Presentation and demo presented to the jury.

## Jury criteria and weights

| Criterion | Weight | What is evaluated |
|---|---|---|
| **Technical execution** | **30%** | Functionality · Architecture · Technical decisions · Functional demo |
| **Presentation and demo** | **30%** | Clarity · Structure · Quality of the demonstration · Answers to questions · Time management |
| **Innovation and creativity** | **20%** | Originality · Creativity · Quality of the approach |
| **Relevance and impact** | **20%** | Extent to which the solution addresses the challenge, and its practical value |

(The mapping of weights to criteria was checked against the shape positions on the jury slide.)

## Repository requirements

1. **Name:** `Direction_TeamName`, with no spaces, diacritics or special characters. Ours: `AI_SkodaRapid`.
2. **Visibility:** public, used only for the hackathon.
3. **Deadline:** send the repo link by **Friday, 20 November, 20:00**.
4. **Good practices:** regular commits with clear messages, **one commit per feature or important step**, not one big commit at the end.
5. **The repo must contain:**
   - the final source code;
   - a README with the solution description;
   - install and run instructions;
   - the dependencies and the relevant tools used;
   - the presentation.
6. **Presentation:** on the official template (sent by email), as a `.ppt`/`.pptx` named `Direction_TeamName` (`AI_SkodaRapid.pptx`), saved in a dedicated folder in the repo (`presentation/`).

---

## What this means for perception (P1)

| Requirement | Consequence for `perception/` |
|---|---|
| **R1** | All detections in the AS (driver camera) and AP (passenger camera) tables of `DriveMate-PLAN-FINAL.md` §4.A are R1. The M rows must work live. |
| **R3** | Perception runs **live on the real cameras**. No pre-recorded video and no pre-processed images, ever. The recorded JSON feature stream (replay) exists **only for development, evaluation and as a declared backup**. It is not the demo. We never record video. |
| **R4** | **Every detection has a field in `PerceptionFrame`**, so P4 can display it on the dashboard. A detection without a field is invisible to the jury and does not count. The debug overlay (MJPEG, key D) shows the raw signals: landmarks, gaze zone, live EAR, phone box, fps. |
| **Jury: Technical execution (30%)** | "Architecture" and "Technical decisions" are scored explicitly. That is why every P1 choice is written down with its reason in [`docs/perception.md`](perception.md), and why we **measure** it: per-model latency p50/p95, fps per camera, end-to-end latency, and `scripts/benchmark.py` on the demo laptop. |
| **Way of working** | One commit per feature, prefixed with the module: `perception: add PERCLOS window`. |
