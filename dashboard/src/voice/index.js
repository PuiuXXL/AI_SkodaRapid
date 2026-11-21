/**
 * @file Public API of the assistant's browser voice (P3), used by P4's dashboard.
 *
 * Keeps the voice separate from the UI (roluri/P3, interfaces table): P4 only calls
 *
 * ```js
 * import { initVoice, onTranscript, isSpeaking } from "./voice/index.js";
 * // inside a click handler (browsers need a gesture for microphone + audio):
 * await initVoice(ws);              // ws = the WebSocket to ws://localhost:8000/ws/ui
 * onTranscript((r) => showSubtitle(r.text));
 * ```
 *
 * Messages handled on `/ws/ui` (formats in docs/assistant.md):
 * - **received**: `speak`, `speak_control` (pause / resume / stop), `alarm`, `media`,
 *   `state` (only `interaction.dialog_window_open` is read);
 * - **sent**: `speech` (recognised text), `speech_onset` (voice start, for P2's
 *   verbal reaction time), `speak_done` (utterance finished; core opens the 6 s
 *   dialog window after a question), `alarm_played` (for the alarm latency, plan J1).
 *
 * Works the same from plain JS or React (wrap `initVoice` in a `useEffect`).
 */

import { OnsetDetector } from "./onset.js";
import { VoicePlayer } from "./player.js";
import { SpeechInput } from "./stt.js";

const nowSeconds = () => (performance.timeOrigin + performance.now()) / 1000;

/** Default options; override any of them in `initVoice(ws, options)`. */
export const DEFAULT_OPTIONS = {
  lang: "ro-RO",
  wakeWords: ["drivemate", "drive mate", "copilot"],
  dialogWindowMs: 6000,          // plan E1: voice accepted without the name for 6 s
  onsetThreshold: 0.035,
  preloadClips: [],              // e.g. ["/sounds/clips/alarm_andrei.mp3", ...]
  clipsManifestUrl: "/sounds/clips/clips.json",
  enableOnset: true,
  quickAnswerMs: 300,            // short answers ("da", "nu", "7") sent after 300 ms of stable text
  earlyFinalMs: 800,             // other addressed requests sent after 800 ms of stable text (0 = off)
  onStatus: () => {},            // diagnostics callback (string), e.g. log it in a dev panel
};

let controller = null;

class VoiceController {
  constructor(ws, options) {
    this.ws = ws;
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.transcriptListeners = new Set();
    this.dialogFromState = false;   // dialog window as reported by core
    this.localDialogUntil = 0;      // local copy (works with a fake core too)

    this.player = new VoicePlayer({
      lang: this.options.lang,
      onSpeakStart: () => this._setHearing(false),
      onSpeakDone: (utterance, info) => this._speakDone(utterance, info),
      onAlarmPlayed: (alarm, ts) => this._send({ type: "alarm_played", id: alarm.id, ts }),
    });
    this.stt = new SpeechInput({
      lang: this.options.lang,
      wakeWords: this.options.wakeWords,
      isDialogOpen: () => this.isDialogOpen(),
      quickAnswerMs: this.options.quickAnswerMs,
      earlyFinalMs: this.options.earlyFinalMs,
      onResult: (result) => this._transcript(result),
      onError: (error) => {
        console.warn("speech recognition error:", error);
        this.options.onStatus(`speech recognition ERROR: ${error}`);
      },
      onStatus: (status) => this.options.onStatus(`speech recognition: ${status}`),
    });
    this.onset = this.options.enableOnset
      ? new OnsetDetector({ threshold: this.options.onsetThreshold, onOnset: (ts) => this._send({ type: "speech_onset", ts }) })
      : null;
    this._onMessage = (event) => this._handleMessage(event);
  }

  async start() {
    this.player.unlock();
    this.ws.addEventListener("message", this._onMessage);
    await this._preloadClips();
    this.stt.start();
    if (this.onset) {
      try {
        await this.onset.start();
      } catch (err) {
        console.warn("onset detector disabled:", err);
        this.options.onStatus(`onset detector disabled: ${err}`);
        this.onset = null;
      }
    }
  }

  stop() {
    this.ws.removeEventListener("message", this._onMessage);
    this.stt.stop();
    this.player.stop();
    this.player.stopMusic();
    if (this.onset) this.onset.stop();
  }

  isDialogOpen() {
    return this.dialogFromState || performance.now() < this.localDialogUntil;
  }

  async _preloadClips() {
    const urls = [...this.options.preloadClips];
    try {
      const manifest = await (await fetch(this.options.clipsManifestUrl)).json();
      for (const clip of Object.values(manifest)) urls.push(`/sounds/clips/${clip.file}`);
    } catch (err) {
      console.warn("clips manifest not loaded (run integrations/audio_clips.py):", err);
    }
    this.player.preloadClips(urls);
  }

  _handleMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    switch (message.type) {
      case "speak":
        this.player.speak(message);
        break;
      case "speak_control":
        if (message.action === "pause") this.player.pause();
        else if (message.action === "resume") this.player.resume();
        else if (message.action === "stop") this.player.stop();
        break;
      case "alarm":
        this.player.alarm(message);
        break;
      case "media":
        this.player.media(message);
        break;
      case "state":
        this.dialogFromState = Boolean(message.state?.interaction?.dialog_window_open);
        break;
      default:
        break; // other messages are for P4's UI
    }
  }

  _setHearing(hearing) {
    // Half-duplex (plan E6): no recognition and no onset while the assistant talks.
    if (hearing) this.stt.resume();
    else this.stt.pause();
    if (this.onset) this.onset.setSuppressed(!hearing);
  }

  _speakDone(utterance, info) {
    if (!utterance) return;
    if (utterance.is_question && !info.interrupted) {
      this.localDialogUntil = performance.now() + this.options.dialogWindowMs;
    }
    this._send({ type: "speak_done", id: utterance.id, is_question: Boolean(utterance.is_question), interrupted: info.interrupted, ts: info.ts });
    if (!this.player.isSpeaking()) this._setHearing(true);
  }

  _transcript(result) {
    for (const listener of this.transcriptListeners) listener(result);
    if (result.final) {
      // early: null (Chrome's final), "quick" (short answer) or "stable" (unchanged text);
      // wait_ms: how long after the last change the result was sent (latency diagnostics).
      this._send({ type: "speech", text: result.text, raw: result.raw, final: true, addressed: result.addressed,
                   early: result.early, wait_ms: result.waitMs, confidence: result.confidence, ts: result.ts });
    }
  }

  _send(message) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }
}

/**
 * Start the voice on an open (or opening) WebSocket to `/ws/ui`.
 * Call from a user gesture (click). Calling it again replaces the previous instance.
 * @param {EventTarget & {readonly readyState: number, send(data: string): void}} ws
 * @param {Partial<typeof DEFAULT_OPTIONS>} [options]
 * @returns {Promise<VoiceController>}
 */
export async function initVoice(ws, options = {}) {
  if (controller) controller.stop();
  controller = new VoiceController(ws, options);
  await controller.start();
  return controller;
}

/**
 * Subscribe to recognised speech (interim and final), e.g. for subtitles.
 * @param {(r: {text: string, final: boolean, addressed: boolean, confidence: number, ts: number}) => void} callback
 * @returns {() => void} Unsubscribe function.
 */
export function onTranscript(callback) {
  if (!controller) throw new Error("initVoice(ws) must be called first");
  controller.transcriptListeners.add(callback);
  return () => controller.transcriptListeners.delete(callback);
}

/** True while the assistant is speaking (e.g. to animate an avatar). */
export function isSpeaking() {
  return controller ? controller.player.isSpeaking() : false;
}

/** Stop microphone, speech and music (e.g. when the dashboard unmounts). */
export function stopVoice() {
  if (controller) controller.stop();
  controller = null;
}

export { nowSeconds };
