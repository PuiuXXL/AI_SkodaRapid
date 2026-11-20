/**
 * @file Exact moment when someone starts speaking (plan B1, verbal reaction channel).
 *
 * The Web Speech API reports text late (hundreds of ms after the person started
 * talking), so P2 cannot measure the **verbal reaction time** from it. This module
 * opens a separate microphone stream (getUserMedia + WebAudio `AnalyserNode`) and
 * reports the instant the sound level rises above a threshold after a silence.
 * The voice controller sends it to core as `speech_onset`; P2 computes
 * `reaction.verbal_ms` = onset - end of the assistant's question.
 *
 * Detection is suppressed while the assistant itself speaks (half-duplex).
 */

export class OnsetDetector {
  /**
   * @param {object} options
   * @param {(ts: number) => void} options.onOnset Called with the onset time (Unix seconds).
   * @param {number} [options.threshold=0.035] RMS level (0-1) that counts as voice.
   * @param {number} [options.minVoiceMs=60] Level must stay above threshold this long.
   * @param {number} [options.minSilenceMs=350] Silence required before a new onset.
   * @param {number} [options.intervalMs=15] Sampling period.
   */
  constructor({ onOnset, threshold = 0.035, minVoiceMs = 60, minSilenceMs = 350, intervalMs = 15 }) {
    this.onOnset = onOnset;
    this.threshold = threshold;
    this.minVoiceMs = minVoiceMs;
    this.minSilenceMs = minSilenceMs;
    this.intervalMs = intervalMs;
    this.suppressed = false; // true while the assistant speaks
    this._timer = null;
    this._voiceStart = null;   // when the level first went above the threshold
    this._silenceSince = 0;    // last time the level was below the threshold
    this._inVoice = false;
  }

  /** Open the microphone and start sampling (call after a user gesture). */
  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
    });
    this.context = new AudioContext();
    const source = this.context.createMediaStreamSource(this.stream);
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    source.connect(this.analyser);
    this._buffer = new Float32Array(this.analyser.fftSize);
    this._silenceSince = performance.now();
    this._timer = setInterval(() => this._sample(), this.intervalMs);
  }

  /** Stop sampling and release the microphone. */
  stop() {
    clearInterval(this._timer);
    this._timer = null;
    if (this.stream) this.stream.getTracks().forEach((track) => track.stop());
    if (this.context) this.context.close();
  }

  /** Ignore sound (assistant speaking) or listen again. */
  setSuppressed(value) {
    this.suppressed = value;
    this._voiceStart = null;
    this._inVoice = false;
    this._silenceSince = performance.now();
  }

  /** Current RMS level of the microphone (0-1), for a level meter. */
  level() {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this._buffer);
    let sum = 0;
    for (const sample of this._buffer) sum += sample * sample;
    return Math.sqrt(sum / this._buffer.length);
  }

  _sample() {
    if (this.suppressed) return;
    const now = performance.now();
    const loud = this.level() > this.threshold;
    if (!loud) {
      this._voiceStart = null;
      if (this._inVoice) this._silenceSince = now;
      this._inVoice = false;
      return;
    }
    if (this._inVoice) return;
    if (this._voiceStart === null) this._voiceStart = now;
    const longEnough = now - this._voiceStart >= this.minVoiceMs;
    const afterSilence = this._voiceStart - this._silenceSince >= this.minSilenceMs;
    if (longEnough && afterSilence) {
      this._inVoice = true;
      // Report the moment the voice started, not when it was confirmed.
      this.onOnset((performance.timeOrigin + this._voiceStart) / 1000);
    } else if (longEnough) {
      this._inVoice = true; // continuous sound without a preceding silence: not an onset
    }
  }
}
