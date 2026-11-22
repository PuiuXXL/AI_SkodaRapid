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
