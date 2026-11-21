/**
 * @file Audio output of the assistant: speech, alarms, music (plan D4, D8, C1, C3).
 *
 * Responsibilities:
 * - **Speech, sentence by sentence.** A `speak` message carries a list of sentences,
 *   each with its own `/tts/<id>.mp3`. They are played in order, the next one
 *   preloaded while the current one plays.
 * - **Yielding the floor (plan D4).** `pause()` stops mid-sentence (core sends
 *   `speak_control: pause` when the driver checks a mirror or an alert starts);
 *   `resume()` plays the "...cum ziceam," clip and restarts the interrupted sentence.
 * - **Ducking (plan 4.D).** Music volume is lowered while the assistant speaks.
 * - **Alarms interrupt everything (plan C1).** `alarm()` stops speech and music and
 *   plays a pre-generated, pre-loaded clip immediately (target < 300 ms end to end).
 * - **Fallback voice (plan C9).** If a TTS file cannot be loaded (no internet), the
 *   browser's local `speechSynthesis` says the sentence instead. It prefers a male
 *   voice (`fallbackVoiceNames`), matching edge-tts `ro-RO-EmilNeural`, so the voice
 *   does not switch between male and female from one sentence to the next.
 *
 * Browsers block audio until the user interacts with the page: create the player
 * (or call `unlock()`) from a click handler.
 */

const nowSeconds = () => (performance.timeOrigin + performance.now()) / 1000;

export class VoicePlayer {
  /**
   * @param {object} options
   * @param {string} [options.lang="ro-RO"] Language for the speechSynthesis fallback.
   * @param {string[]} [options.fallbackVoiceNames=["Andrei", "Emil"]] Preferred (male) local
   *        voices for the fallback, matched case-insensitively against the voice name; if none
   *        is installed, any voice of `lang` is used.
   * @param {string} [options.resumeClipUrl="/sounds/clips/resume.mp3"] "...cum ziceam," clip.
   * @param {number} [options.duckFactor=0.3] Music volume multiplier while speaking.
   * @param {(utterance: object) => void} [options.onSpeakStart] First sentence starts playing.
   * @param {(utterance: object, info: {interrupted: boolean, ts: number}) => void} [options.onSpeakDone]
   *        Utterance finished (or was stopped).
   * @param {(alarm: object, ts: number) => void} [options.onAlarmPlayed] Alarm audio actually started.
   */
  constructor({
    lang = "ro-RO",
    fallbackVoiceNames = ["Andrei", "Emil"],
    resumeClipUrl = "/sounds/clips/resume.mp3",
    duckFactor = 0.3,
    onSpeakStart = () => {},
    onSpeakDone = () => {},
    onAlarmPlayed = () => {},
  } = {}) {
    this.lang = lang;
    this.fallbackVoiceNames = fallbackVoiceNames.map((name) => name.toLowerCase());
    this.resumeClipUrl = resumeClipUrl;
    this.duckFactor = duckFactor;
    this.onSpeakStart = onSpeakStart;
    this.onSpeakDone = onSpeakDone;
    this.onAlarmPlayed = onAlarmPlayed;

    this.queue = [];        // utterances waiting to be spoken
    this.current = null;    // utterance being spoken
    this.index = 0;         // sentence index inside the current utterance
    this.audio = null;      // HTMLAudioElement of the current sentence
    this.paused = false;
    this.clipCache = new Map(); // url -> preloaded HTMLAudioElement (alarms, clips)

    this.music = new Audio();
    this.music.loop = true;
    this.musicVolume = 0.6;
  }

  /** True while an utterance is being spoken (or paused mid-way). */
  isSpeaking() {
    return this.current !== null;
  }

  /** Call from a click handler: lets the browser play audio later without a gesture. */
  unlock() {
    const silent = new Audio("data:audio/mp3;base64,//uQx");
    silent.play().catch(() => {});
    if (window.speechSynthesis) window.speechSynthesis.getVoices();
  }

  /**
   * Preload clips (alarms, "Ești bine?", passenger instructions) so they play instantly.
   * @param {string[]} urls
   */
  preloadClips(urls) {
    for (const url of urls) {
      if (this.clipCache.has(url)) continue;
      const element = new Audio(url);
      element.preload = "auto";
      element.load();
      this.clipCache.set(url, element);
    }
  }

  /**
   * Queue a `speak` message from core (see docs/assistant.md for the format).
   * @param {{id: string, sentences: {id: string, text: string, url: string}[], clip_url?: string, is_question?: boolean}} utterance
   */
  speak(utterance) {
    this.queue.push(utterance);
    if (!this.current) this._next();
  }

  /** Stop mid-sentence (plan D4). */
  pause() {
    if (!this.current || this.paused) return;
    this.paused = true;
    if (this.audio) this.audio.pause();
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  /** Resume with "...cum ziceam," and restart the interrupted sentence (plan D4). */
  resume() {
    if (!this.current || !this.paused) return;
    this.paused = false;
    this._playUrl(this.resumeClipUrl, () => this._playSentence(), () => this._playSentence());
  }

  /** Stop speaking and forget queued utterances. */
  stop() {
    const utterance = this.current;
    this.queue = [];
    this._cleanupAudio();
    this.current = null;
    this.paused = false;
    this._unduck();
    if (utterance) this.onSpeakDone(utterance, { interrupted: true, ts: nowSeconds() });
  }

  /**
   * Play an alarm clip immediately: stops speech and music first (plan C1, C3).
   * @param {{id: string, clip_url: string}} alarm
   */
  alarm(alarm) {
    this.stop();
    this.stopMusic();
    let element = this.clipCache.get(alarm.clip_url);
    if (!element) {
      element = new Audio(alarm.clip_url);
      this.clipCache.set(alarm.clip_url, element);
    }
    element.currentTime = 0;
    element.onplaying = () => this.onAlarmPlayed(alarm, nowSeconds());
    element.play().catch((err) => console.error("alarm clip failed", err));
  }

  /**
   * Handle a `media` message: play / stop / change volume (plan D8).
   * `loop` (default true) is false for YouTube songs and podcasts (`/media/yt/<id>.m4a`).
   * @param {{action: "play"|"stop"|"volume", url?: string, volume?: number, loop?: boolean}} message
   */
  media(message) {
    if (message.action === "play" && message.url) {
      this.musicVolume = message.volume ?? this.musicVolume;
      this.music.loop = message.loop ?? true;
      this.music.src = message.url;
      this.music.volume = this.current ? this.musicVolume * this.duckFactor : this.musicVolume;
      this.music.play().catch((err) => console.error("music failed", err));
    } else if (message.action === "stop") {
      this.stopMusic();
    } else if (message.action === "volume" && typeof message.volume === "number") {
      this.musicVolume = message.volume;
      this.music.volume = this.current ? this.musicVolume * this.duckFactor : this.musicVolume;
    }
  }

  /** Stop the music (alarms and the driver can always do this). */
  stopMusic() {
    this.music.pause();
    this.music.removeAttribute("src");
    this.music.load();
  }

  // --- internals --------------------------------------------------------------

  _next() {
    this.current = this.queue.shift() || null;
    this.index = 0;
    if (!this.current) {
      this._unduck();
      return;
    }
    this._duck();
    this.onSpeakStart(this.current);
    if (this.current.clip_url) {
      this._playUrl(this.current.clip_url, () => this._finish(), () => this._fallbackSpeak(this.current.text, () => this._finish()));
    } else {
      this._playSentence();
    }
  }

  _playSentence() {
    const utterance = this.current;
    if (!utterance || this.paused) return;
    const sentence = utterance.sentences[this.index];
    if (!sentence) {
      this._finish();
      return;
    }
    const nextSentence = utterance.sentences[this.index + 1];
    if (nextSentence?.url) new Audio(nextSentence.url).preload = "auto"; // warm the HTTP cache
    const advance = () => {
      if (this.current !== utterance || this.paused) return;
      this.index += 1;
      this._playSentence();
    };
    if (!sentence.url) this._fallbackSpeak(sentence.text, advance);
    else this._playUrl(sentence.url, advance, () => this._fallbackSpeak(sentence.text, advance));
  }

  _playUrl(url, onEnded, onError) {
    this._cleanupAudio();
    const element = this.clipCache.get(url) || new Audio(url);
    element.currentTime = 0;
    element.onended = onEnded;
    element.onerror = onError;
    this.audio = element;
    element.play().catch(onError);
  }

  _fallbackSpeak(text, onEnded) {
    if (!window.speechSynthesis || !text) {
      onEnded();
      return;
    }
    const speech = new SpeechSynthesisUtterance(text);
    speech.lang = this.lang;
    const voice = this._fallbackVoice();
    if (voice) speech.voice = voice;
    speech.onend = onEnded;
    speech.onerror = onEnded;
    window.speechSynthesis.speak(speech);
  }

  /**
   * Local voice for the speechSynthesis fallback: the first installed voice of `lang`
   * whose name contains one of `fallbackVoiceNames`, else any voice of `lang`, else
   * null (the browser then picks its default for `speech.lang`).
   * @returns {SpeechSynthesisVoice | null}
   */
  _fallbackVoice() {
    const prefix = this.lang.slice(0, 2).toLowerCase();
    const voices = window.speechSynthesis.getVoices().filter((v) => v.lang?.toLowerCase().startsWith(prefix));
    for (const name of this.fallbackVoiceNames) {
      const match = voices.find((v) => v.name.toLowerCase().includes(name));
      if (match) return match;
    }
    return voices[0] || null;
  }

  _finish() {
    const utterance = this.current;
    this._cleanupAudio();
    this.current = null;
    this.onSpeakDone(utterance, { interrupted: false, ts: nowSeconds() });
    this._next();
  }

  _cleanupAudio() {
    if (this.audio) {
      this.audio.onended = null;
      this.audio.onerror = null;
      this.audio.pause();
      this.audio = null;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  _duck() {
    this.music.volume = this.musicVolume * this.duckFactor;
  }

  _unduck() {
    this.music.volume = this.musicVolume;
  }
}
