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
   */
  constructor({ lang = "ro-RO", wakeWords = ["drivemate", "drive mate", "copilot"], isDialogOpen = () => false, onResult, onError = () => {}, onStatus = () => {} }) {
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
    this.recognition.onstart = () => this.onStatus(`listening (${lang})`);
    this.recognition.onaudiostart = () => this.onStatus("microphone audio received");
    this.recognition.onspeechstart = () => this.onStatus("voice detected");
  }

  /** Start listening (call after a user gesture: the browser asks for the microphone). */
  start() {
    this.running = true;
    this.paused = false;
    this._safeStart();
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
  addressing(text) {
    const norm = normalizeText(text);
    const wake = this.wakeWords.find((word) => norm.includes(word));
    if (wake) {
      return { addressed: true, text: norm.replace(wake, "").trim() || norm };
    }
    return { addressed: this.isDialogOpen(), text };
  }

  _safeStart() {
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

  _handleResult(event) {
    if (this.paused) return;
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const raw = result[0].transcript.trim();
      if (!raw) continue;
      const { addressed, text } = this.addressing(raw);
      this.onResult({
        text: result.isFinal ? text : raw,
        raw,
        final: result.isFinal,
        addressed,
        confidence: result[0].confidence || 0,
        ts: (performance.timeOrigin + performance.now()) / 1000,
      });
    }
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
