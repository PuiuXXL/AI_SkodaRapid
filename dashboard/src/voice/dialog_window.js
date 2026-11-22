/**
 * @file The browser's dialog window (plan E1): while it is open, speech without the wake word
 * ("copilot", "drivemate") is addressed to the assistant.
 *
 * Rules (decided 2026-11-22 after the first voice tests, where a "șapte" answer to the KSS
 * question was ignored because the old fixed 6 s window had already closed):
 * - it **opens** for `windowMs` (15 s) after a question of the assistant, or when the driver
 *   addresses the assistant with the wake word;
 * - it **stays open while the driver speaks**: every addressed recognition result (interim or
 *   final) restarts the countdown, so it closes `windowMs` after the driver's LAST word;
 * - an answer of the assistant given **inside the conversation** restarts it when the answer
 *   ends (the assistant's own speech does not eat the driver's time);
 * - it **closes at once** on "nu" / "nimic" / "gata" / "mersi" (`NO_MORE_ANSWERS` in index.js);
 * - once closed, the wake word is needed again.
 *
 * Pure logic with an injectable clock, so it can be tested without a browser
 * (`node --test dashboard/tests/voice.test.mjs`).
 */

export class DialogWindow {
  /**
   * @param {object} options
   * @param {number} [options.windowMs=15000] How long the window stays open after the last activity.
   * @param {() => number} [options.now] Clock in milliseconds (defaults to `performance.now()`).
   */
  constructor({ windowMs = 15000, now = () => performance.now() } = {}) {
    this.windowMs = windowMs;
    this.now = now;
    this.until = 0;             // clock time when the window closes (0 = closed)
    this.heldBySpeech = false;  // the assistant started talking while the window was open
  }

  /** True while voice without the wake word is accepted. */
  isOpen() {
    return this.now() < this.until;
  }

  /** Milliseconds left (0 when closed), e.g. for a countdown in a dev page. */
  remainingMs() {
    return Math.max(0, this.until - this.now());
  }

  /** Open the window, or restart its countdown: closes `windowMs` from now. */
  open() {
    this.until = this.now() + this.windowMs;
  }

  /** Close at once ("nu", "gata", "mersi"): the wake word is needed again. */
  close() {
    this.until = 0;
    this.heldBySpeech = false;
  }

  /**
   * A recognition result from the microphone.
   * @param {{addressed: boolean}} result Addressed = wake word, or the window was open when the utterance started.
   */
  heard(result) {
    if (result.addressed) this.open();
  }

  /** The assistant starts an utterance: remember whether it speaks inside an open conversation. */
  speakStarted() {
    this.heldBySpeech = this.heldBySpeech || this.isOpen();
  }

  /**
   * The assistant finished an utterance.
   * @param {{isQuestion: boolean, interrupted: boolean, stillSpeaking: boolean}} info
   *        `stillSpeaking`: more utterances are queued (the conversation goes on).
   */
  speakDone({ isQuestion, interrupted, stillSpeaking }) {
    if (!interrupted && (isQuestion || this.heldBySpeech)) this.open();
    if (!stillSpeaking) this.heldBySpeech = false;
  }
}
