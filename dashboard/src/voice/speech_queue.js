/**
 * @file Who gets the floor in the voice player (plan "alert severity vs. conversation", step 5).
 *
 * Every `speak` message carries `priority` (shared/contracts.py `SpeakPriority`, set by core):
 *
 * | priority  | who                                        | arriving while something else is said             |
 * |-----------|--------------------------------------------|---------------------------------------------------|
 * | critical  | the SOS ("Ești bine?", instructions)       | stops it at once, the whole queue is dropped       |
 * | urgent    | a distraction's warning, "Nu te mai văd"   | stops lower speech at once, lower waiting dropped  |
 * | important | P2's questions: a break, a reminder, ...   | waits for the end of the current SENTENCE, then    |
 * |           |                                            | cuts the rest of a lower utterance                 |
 * | normal    | the assistant (LLM, fixed texts)           | waits in line; dropped if it was held up too long  |
 * |           |                                            | by HIGHER speech (not by the assistant's own)      |
 *
 * Equal or higher speech is never cut: it is queued, higher priority first (stable order inside a priority).
 * Dropped utterances still get a `speak_done` with `interrupted: true` so core knows they were not said
 * (core resumes the assistant after a distraction's warning itself: "Cum ziceam, ...").
 *
 * Pure logic with an injectable clock: tested with `node --test dashboard/tests/voice.test.mjs`.
 */

export const PRIORITY_RANK = { normal: 0, important: 1, urgent: 2, critical: 3 };

/** Rank of an utterance (unknown / missing priority = normal, e.g. an older core). */
export function rankOf(utterance) {
  return PRIORITY_RANK[utterance?.priority] ?? PRIORITY_RANK.normal;
}

export class SpeechQueue {
  /**
   * @param {object} [options]
   * @param {number} [options.staleNormalMs=8000] A `normal` utterance held up longer than this by higher-priority
   *        speech is dropped: the moment has passed (e.g. an answer delayed behind an SOS and a break question).
   *        Waiting behind the assistant's own sentences does not count ("Te mai ajut cu ceva?" after a long answer).
   * @param {() => number} [options.now] Clock in ms (defaults to `performance.now()`).
   */
  constructor({ staleNormalMs = 8000, now = () => performance.now() } = {}) {
    this.staleNormalMs = staleNormalMs;
    this.now = now;
    this.items = []; // waiting utterances, highest priority first
  }

  get length() {
    return this.items.length;
  }

  /**
   * An utterance arrives while `current` (or nothing) is being said.
   * @returns {{action: "start"|"queue"|"stop_now"|"cut_at_sentence_end", dropped: object[]}}
   *   `start`: play it now (nothing is playing); `stop_now`: stop `current` (interrupted) and play the queue head;
   *   `cut_at_sentence_end`: let `current` finish its sentence, then stop it; `queue`: just wait.
   *   `dropped`: waiting utterances removed (to be reported as interrupted).
   */
  arrive(utterance, current) {
    utterance._arrived = this.now();
    const rank = rankOf(utterance);
    if (rank === PRIORITY_RANK.normal && current && rankOf(current) > rank) utterance._heldSince = this.now();
    let dropped = [];
    if (rank >= PRIORITY_RANK.urgent) {
      // critical drops everything that waits; urgent drops what is lower
      dropped = this.items.filter((u) => rank === PRIORITY_RANK.critical || rankOf(u) < rank);
      this.items = this.items.filter((u) => !dropped.includes(u));
    }
    this._insert(utterance);
    if (!current) return { action: "start", dropped };
    const currentRank = rankOf(current);
    if (rank <= currentRank) return { action: "queue", dropped };
    if (rank >= PRIORITY_RANK.urgent) return { action: "stop_now", dropped };
    return { action: "cut_at_sentence_end", dropped };
  }

  /**
   * The next utterance to say, skipping `normal` ones that waited longer than `staleNormalMs`.
   * When `cutRank` is given (an `important` utterance cut the current one), waiting utterances below it are
   * dropped too: they belonged to the conversation that was just cut.
   * @returns {{next: object|null, dropped: object[]}}
   */
  next(cutRank = null) {
    const dropped = [];
    if (cutRank !== null) {
      for (const u of this.items.filter((item) => rankOf(item) < cutRank)) dropped.push(u);
      this.items = this.items.filter((item) => !dropped.includes(item));
    }
    while (this.items.length) {
      const head = this.items.shift();
      const held = head._heldSince ?? null;
      if (rankOf(head) === PRIORITY_RANK.normal && held !== null && this.now() - held > this.staleNormalMs) {
        dropped.push(head);
        continue;
      }
      for (const item of this.items) {
        if (rankOf(item) !== PRIORITY_RANK.normal) continue;
        if (rankOf(head) > PRIORITY_RANK.normal) item._heldSince ??= this.now(); // held up by higher speech
        else item._heldSince = null; // the assistant has the floor again: its own sentences are not "late"
      }
      return { next: head, dropped };
    }
    return { next: null, dropped };
  }

  /** Highest priority waiting (null when empty). */
  peekRank() {
    return this.items.length ? rankOf(this.items[0]) : null;
  }

  /** Drop everything (stop / alarm). @returns the dropped utterances. */
  clear() {
    const dropped = this.items;
    this.items = [];
    return dropped;
  }

  _insert(utterance) {
    const rank = rankOf(utterance);
    const index = this.items.findIndex((u) => rankOf(u) < rank);
    if (index === -1) this.items.push(utterance);
    else this.items.splice(index, 0, utterance);
  }
}
