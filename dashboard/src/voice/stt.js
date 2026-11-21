/**
 * @file Continuous, half-duplex speech recognition (plan E1, E6).
 *
 * Uses the Web Speech API (`webkitSpeechRecognition`). It works in **Google Chrome**
 * (not Chromium, which has no speech service) and sends the audio to Google's
 * recogniser - this is the "voice -> Chrome speech recognition" line of the
 * privacy slide (plan section 3).
 *
 * Behaviour:
 * - `continuous = true`, `interimResults = true`, restarted in `onend` (Chrome stops
 *   recognition by itself after silence or ~60 s);
 * - **half-duplex**: `pause()` while the assistant speaks, `resume()` afterwards.
 *   Echo cancellation of getUserMedia does not apply to the Web Speech API, so
 *   without this the assistant would hear itself (plan E6);
 * - an utterance is **addressed** to the assistant when it contains a wake word
 *   (the assistant's name) or when the dialog window is open (6 s after a question,
 *   plan E1). Only addressed final results should be acted upon by core.
 */

/** Text normalisation used to look for wake words (lower-case, no diacritics). */
export function normalizeText(text) {
  return (text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Words that make up a short answer (normalised): yes / no, KSS numbers, quiz control.
 * Matches assistant/answers.py (YES_WORDS, NO_WORDS, KSS_WORDS) and assistant/dialog.py.
 */
export const QUICK_ANSWER_WORDS = new Set([
  "da", "nu", "ok", "okay", "sigur", "bine", "desigur", "hai", "te", "rog", "multumesc", "corect", "exact",
  "gata", "stop", "ajunge", "quiz", "chiz", "podcast",
  "1", "2", "3", "4", "5", "6", "7", "8", "9",
  "unu", "una", "doi", "doua", "trei", "patru", "cinci", "sase", "sapte", "opt", "noua",
]);

export class SpeechInput {
  /**
   * @param {object} options
   * @param {string} [options.lang="ro-RO"] Recognition language (BCP-47).
   * @param {string[]} [options.wakeWords] Names that address the assistant (normalised form).
   * @param {() => boolean} [options.isDialogOpen] Returns true while the dialog window is open.
   * @param {(r: {text: string, final: boolean, addressed: boolean, confidence: number, ts: number}) => void} options.onResult
   *        Called for every interim and final result.
   * @param {(error: string) => void} [options.onError] Called on errors (e.g. "not-allowed", "network", "audio-capture").
   * @param {(status: string) => void} [options.onStatus] Diagnostics: "listening", "microphone audio received",
   *        "voice detected", "stopped" (shown in the dev page log).
   * @param {number} [options.quickAnswerMs=300] A short answer ("da", "nu", "7") that stays unchanged this
   *        long while the dialog window is open is sent immediately (0 = wait for Chrome's final result).
   * @param {number} [options.earlyFinalMs=800] Any other addressed utterance that stays unchanged this long
   *        is sent as final (0 = disabled). Lower = faster, but a long pause mid-sentence may cut the request.
   */
  constructor({ lang = "ro-RO", wakeWords = ["drivemate", "drive mate", "copilot"], isDialogOpen = () => false, onResult, onError = () => {}, onStatus = () => {}, quickAnswerMs = 300, earlyFinalMs = 800 }) {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      throw new Error("Web Speech API not available: use Google Chrome.");
    }
    this.lang = lang;
    this.wakeWords = wakeWords.map(normalizeText);
    this.isDialogOpen = isDialogOpen;
    this.onResult = onResult;
    this.onError = onError;
    this.onStatus = onStatus;
    this.running = false; // start() called and stop() not called
    this.paused = false;  // temporarily muted while the assistant speaks
    this.quickAnswerMs = quickAnswerMs;
    this.earlyFinalMs = earlyFinalMs;
    this._early = new Map();      // result index -> text already sent early
    this._dialogAtStart = new Map(); // result index -> dialog window open when it started
    this._earlyTimer = null;
    this._lastChange = performance.now(); // last time an interim result changed

    this.recognition = new Recognition();
    this.recognition.lang = lang;
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.maxAlternatives = 1;
    this.recognition.onresult = (event) => this._handleResult(event);
    this.recognition.onend = () => {
      this.onStatus(this.paused ? "paused (assistant speaking)" : "stopped, restarting");
      this._restartIfNeeded();
    };
    this.recognition.onerror = (event) => this._handleError(event);
    // Diagnostics: these tell whether the microphone and the recogniser really work.
    this.recognition.onstart = () => {
      // Result indexes restart with every recognition session.
      this._early.clear();
      this._dialogAtStart.clear();
      this._cancelEarly();
      this.onStatus(`listening (${lang})`);
    };
    this.recognition.onaudiostart = () => this.onStatus("microphone audio received");
    this.recognition.onaudioend = () => this.onStatus("microphone audio ended");
    this.recognition.onspeechstart = () => this.onStatus("voice detected");
  }

  /** Start listening (call after a user gesture: the browser asks for the microphone). */
  start(paused = false) {
    this.running = true;
    this.paused = paused;
    if (!paused) this._safeStart();
  }

  /** Stop listening for good. */
  stop() {
    this.running = false;
    this.recognition.abort();
  }

  /** Half-duplex: stop hearing while the assistant speaks (pending audio is dropped). */
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.recognition.abort();
  }

  /** Half-duplex: listen again once the assistant is silent. */
  resume() {
    if (!this.paused) return;
    this.paused = false;
    if (this.running) this._safeStart();
  }

  /**
   * Whether an utterance is addressed to the assistant, and the text without the wake word.
   * @param {string} text
   * @returns {{addressed: boolean, text: string}}
   */
  addressing(text, startedInDialog = false) {
    const norm = normalizeText(text);
    const wake = this.wakeWords.find((word) => norm.includes(word));
    if (wake) {
      // Remove only the wake word (and the comma after it) from the ORIGINAL text, so the
      // LLM gets the request exactly as recognised, diacritics included:
      // "Copilot, amintește-mi..." -> "amintește-mi...".
      const pattern = new RegExp(`\\b${wake.split(" ").join("[\\s-]*")}\\b[\\s,.!?:;-]*`, "i");
      const stripped = text.replace(pattern, "").trim();
      return { addressed: true, text: stripped || text };
    }
    // In the dialog window (or started while it was open, even if Chrome finalised the
    // text after it closed): no wake word needed.
    return { addressed: this.isDialogOpen() || startedInDialog, text };
  }

  _safeStart() {
    if (!this.running || this.paused) return;
    try {
      this.recognition.start();
    } catch (err) {
      // "InvalidStateError: already started" - harmless.
    }
  }

  _restartIfNeeded() {
    if (this.running && !this.paused) {
      setTimeout(() => this._safeStart(), 150);
    }
  }

  /**
   * True for a short answer to a question ("da", "nu", "șapte", "gata"...), which can be
   * acted upon as soon as it is stable instead of waiting for Chrome's final result.
   * @param {string} text
   */
  isQuickAnswer(text) {
    const words = normalizeText(text).split(" ").filter(Boolean);
    return words.length > 0 && words.length <= 3 && words.every((word) => QUICK_ANSWER_WORDS.has(word));
  }

  _handleResult(event) {
    if (this.paused) return;
    const now = performance.now();
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const raw = result[0].transcript.trim();
      if (!raw) continue;
      // Remember whether the dialog window was open when this utterance STARTED: Chrome
      // may publish the final text 1-3 s later, after the 6 s window has closed.
      if (!this._dialogAtStart.has(i)) this._dialogAtStart.set(i, this.isDialogOpen());
      const startedInDialog = this._dialogAtStart.get(i);
      const { addressed, text } = this.addressing(raw, startedInDialog);
      if (result.isFinal) {
        this._dialogAtStart.delete(i);
        this._cancelEarly();
        if (this._early.has(i)) {
          const sent = normalizeText(this._early.get(i));
          this._early.delete(i);
          const extra = normalizeText(raw).replace(sent, "").trim().split(" ").filter(Boolean);
          // Same text (or one extra word) as already sent early: do not send it twice.
          if (extra.length <= 1) continue;
          // The driver kept talking after a long pause: send the full sentence as well.
        }
        this._emit({ text, raw, final: true, addressed, early: null, waitMs: Math.round(now - this._lastChange), confidence: result[0].confidence });
      } else {
        this._lastChange = now;
        this._emit({ text: raw, raw, final: false, addressed, early: null, waitMs: 0, confidence: result[0].confidence });
        this._scheduleEarly(i, raw, startedInDialog);
      }
    }
  }

  /**
   * Early finalisation. Chrome publishes the final result only after it hears enough
   * silence (~0.5-1 s after the last word). If an ADDRESSED interim result stays unchanged
   * for `quickAnswerMs` (short answer while the dialog window is open) or `earlyFinalMs`
   * (any other addressed request), it is sent as final right away; Chrome's real final
   * for the same result is then ignored. Set either delay to 0 to disable that path.
   */
  _scheduleEarly(index, raw, startedInDialog = false) {
    this._cancelEarly();
    const { addressed, text } = this.addressing(raw, startedInDialog);
    if (!addressed || this._early.has(index)) return;
    const quick = (this.isDialogOpen() || startedInDialog) && this.isQuickAnswer(raw);
    // "Copilot..." followed by a pause: only the name so far, wait for the request itself.
    if (!quick && normalizeText(text).split(" ").filter(Boolean).length < 2) return;
    const delay = quick ? this.quickAnswerMs : this.earlyFinalMs;
    if (!delay) return;
    this._earlyTimer = setTimeout(() => {
      if (this.paused || this._early.has(index)) return;
      this._early.set(index, raw);
      this._emit({ text, raw, final: true, addressed: true, early: quick ? "quick" : "stable", waitMs: delay });
    }, delay);
  }

  _cancelEarly() {
    clearTimeout(this._earlyTimer);
    this._earlyTimer = null;
  }

  _emit({ text, raw, final, addressed, early, waitMs, confidence = 0 }) {
    this.onResult({ text, raw, final, addressed, early, waitMs, confidence: confidence || 0, ts: (performance.timeOrigin + performance.now()) / 1000 });
  }

  _handleError(event) {
    // "no-speech" and "aborted" are normal in continuous mode (and after pause()).
    if (event.error === "no-speech" || event.error === "aborted") return;
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      this.running = false;
    }
    this.onError(event.error);
  }
}
