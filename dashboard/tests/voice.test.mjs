// Dialog window of the browser voice (dashboard/src/voice/dialog_window.js).
// Run: node --test dashboard/tests/voice.test.mjs   (pure logic, no browser needed)
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { DialogWindow } from "../src/voice/dialog_window.js";

function make() {
  const clock = { t: 0 };
  const window = new DialogWindow({ windowMs: 15000, now: () => clock.t });
  return { clock, window };
}

test("closed at start: the wake word is needed", () => {
  const { window } = make();
  assert.equal(window.isOpen(), false);
  assert.equal(window.remainingMs(), 0);
});

test("a question opens it for 15 s", () => {
  const { clock, window } = make();
  window.speakStarted();
  window.speakDone({ isQuestion: true, interrupted: false, stillSpeaking: false });
  clock.t = 14900;
  assert.equal(window.isOpen(), true);
  clock.t = 15001;
  assert.equal(window.isOpen(), false);
});

test("the driver's words keep it open: it closes 15 s after the last one", () => {
  const { clock, window } = make();
  window.speakDone({ isQuestion: true, interrupted: false, stillSpeaking: false });
  for (clock.t = 1000; clock.t <= 25000; clock.t += 1000) window.heard({ addressed: true });  // 24 s of talking
  clock.t = 25000 + 14900;
  assert.equal(window.isOpen(), true);
  clock.t = 25000 + 15001;
  assert.equal(window.isOpen(), false);
});

test("a late answer such as 'sapte' 12 s after the question is still inside the window", () => {
  const { clock, window } = make();
  window.speakDone({ isQuestion: true, interrupted: false, stillSpeaking: false });
  clock.t = 12000;
  assert.equal(window.isOpen(), true);
});

test("speech that is not addressed never opens it", () => {
  const { clock, window } = make();
  window.heard({ addressed: false });
  clock.t = 1;
  assert.equal(window.isOpen(), false);
});

test("the wake word opens it: the driver can go on without saying it again", () => {
  const { clock, window } = make();
  window.heard({ addressed: true });  // "Copilot, cât mai am?"
  clock.t = 10000;
  assert.equal(window.isOpen(), true);
});

test("an answer given inside the conversation restarts the countdown when it ends", () => {
  const { clock, window } = make();
  window.heard({ addressed: true });   // driver asks at t=0
  clock.t = 2000;
  window.speakStarted();               // the answer starts inside the window...
  clock.t = 14000;                     // ...and is long (12 s)
  window.speakDone({ isQuestion: false, interrupted: false, stillSpeaking: false });
  clock.t = 14000 + 14900;
  assert.equal(window.isOpen(), true);
});

test("an assistant statement outside a conversation does not open it", () => {
  const { clock, window } = make();
  window.speakStarted();
  window.speakDone({ isQuestion: false, interrupted: false, stillSpeaking: false });
  clock.t = 1;
  assert.equal(window.isOpen(), false);
});

test("an interrupted question (alarm) does not open it", () => {
  const { clock, window } = make();
  window.speakStarted();
  window.speakDone({ isQuestion: true, interrupted: true, stillSpeaking: false });
  clock.t = 1;
  assert.equal(window.isOpen(), false);
});

test("'nu' / 'gata' closes it at once", () => {
  const { clock, window } = make();
  window.heard({ addressed: true });
  clock.t = 1000;
  window.close();
  assert.equal(window.isOpen(), false);
  window.speakStarted();               // the next statement no longer re-opens it
  window.speakDone({ isQuestion: false, interrupted: false, stillSpeaking: false });
  assert.equal(window.isOpen(), false);
});

// --- who gets the floor (dashboard/src/voice/speech_queue.js) --------------------------------------------------------
import { SpeechQueue } from "../src/voice/speech_queue.js";

function queue() {
  const clock = { t: 0 };
  return { clock, q: new SpeechQueue({ staleNormalMs: 8000, now: () => clock.t }) };
}
const u = (id, priority = "normal") => ({ id, priority });

test("nothing playing: any utterance starts at once", () => {
  const { q } = queue();
  assert.equal(q.arrive(u("a"), null).action, "start");
  assert.equal(q.next().next.id, "a");
});

test("the assistant never cuts the assistant: it waits in line", () => {
  const { q } = queue();
  assert.equal(q.arrive(u("u2"), u("u1")).action, "queue");
});

test("P2's question waits for the end of the assistant's sentence, then drops what was left of the conversation", () => {
  const { q } = queue();
  q.arrive(u("u2"), u("u1"));                         // "Te mai ajut cu ceva?" waits behind the answer
  const result = q.arrive(u("drw1", "important"), u("u1"));
  assert.equal(result.action, "cut_at_sentence_end");
  const { next, dropped } = q.next(1);                // the answer was cut at a sentence end
  assert.equal(next.id, "drw1");
  assert.deepEqual(dropped.map((x) => x.id), ["u2"]);
});

test("a distraction's warning stops the assistant at once and drops its waiting sentences", () => {
  const { q } = queue();
  q.arrive(u("u2"), u("u1"));
  const result = q.arrive(u("dis1", "urgent"), u("u1"));
  assert.equal(result.action, "stop_now");
  assert.deepEqual(result.dropped.map((x) => x.id), ["u2"]);
  assert.equal(q.next().next.id, "dis1");
});

test("the SOS drops everything that waits, even important questions", () => {
  const { q } = queue();
  q.arrive(u("rem1", "important"), u("dis1", "urgent"));
  const result = q.arrive(u("sos1", "critical"), u("dis1", "urgent"));
  assert.equal(result.action, "stop_now");
  assert.deepEqual(result.dropped.map((x) => x.id), ["rem1"]);
});

test("an urgent warning does not cut the SOS: it waits", () => {
  const { q } = queue();
  assert.equal(q.arrive(u("dis1", "urgent"), u("sos1", "critical")).action, "queue");
});

test("higher priority first, arrival order inside a priority", () => {
  const { q } = queue();
  const current = u("sos0", "critical");
  for (const item of [u("u1"), u("rem1", "important"), u("u2"), u("sc1", "important")]) q.arrive(item, current);
  const order = [];
  for (let r = q.next(); r.next; r = q.next()) order.push(r.next.id);
  assert.deepEqual(order, ["rem1", "sc1", "u1", "u2"]);
});

test("the assistant's speech that waited too long is dropped, P2's is not", () => {
  const { clock, q } = queue();
  const current = u("sos0", "critical");
  q.arrive(u("u1"), current);
  q.arrive(u("drw1", "important"), current);
  clock.t = 9000;                                     // e.g. after an SOS and a break question
  const first = q.next();
  assert.equal(first.next.id, "drw1");
  const second = q.next();
  assert.equal(second.next, null);
  assert.deepEqual(second.dropped.map((x) => x.id), ["u1"]);
});

test("speech without a priority (an older core) counts as normal", () => {
  const { q } = queue();
  assert.equal(q.arrive({ id: "x" }, u("u1")).action, "queue");
});

test("waiting behind the assistant's own long answer is not 'too long'", () => {
  const { clock, q } = queue();
  q.arrive(u("u2"), u("u1"));                         // "Te mai ajut cu ceva?" behind a 10 s answer
  clock.t = 10000;
  assert.equal(q.next().next.id, "u2");
});

test("held up behind P2's question: the clock starts when P2 takes the floor", () => {
  const { clock, q } = queue();
  q.arrive(u("u2"), u("u1"));
  q.arrive(u("drw1", "important"), u("u1"));
  clock.t = 5000;
  assert.equal(q.next(1).next?.id ?? null, "drw1");  // cut at the sentence end: u2 belonged to the cut answer
  q.arrive(u("u3"), u("drw1", "important"));          // a new answer while P2 speaks
  clock.t = 14000;
  const after = q.next();
  assert.equal(after.next, null);
  assert.deepEqual(after.dropped.map((x) => x.id), ["u3"]);
});

test("after P2's warning the assistant's resumed answer and its question are not 'late'", () => {
  const { clock, q } = queue();
  const warning = u("dis1", "urgent");
  q.arrive(u("u5"), warning);                         // "Cum ziceam, ..." queued behind the warning
  q.arrive(u("u6"), warning);                         // "Te mai ajut cu ceva?"
  clock.t = 2000;
  assert.equal(q.next().next.id, "u5");               // the warning ended: the assistant has the floor again
  clock.t = 14000;                                    // u5 was a long answer
  assert.equal(q.next().next.id, "u6");
});
