import test from 'node:test';
import assert from 'node:assert/strict';
import { MotionActor, MOTIONS, EMOTIONS } from '../web/motion.mjs';

function run(actor, seconds, step = 1 / 60) {
  let frame;
  for (let i = 0; i < Math.ceil(seconds / step); i++) frame = actor.tick(step);
  return frame;
}

function finite(frame) {
  for (const q of Object.values(frame.pose)) {
    assert.equal(q.rotation.length, 4);
    assert.ok(q.rotation.every(Number.isFinite));
    assert.ok(Math.abs(Math.hypot(...q.rotation) - 1) < 1e-8);
  }
  for (const v of Object.values(frame.expressions)) assert.ok(v >= 0 && v <= 1);
  assert.ok(Math.abs(frame.offset[0]) < 0.15);
  assert.ok(Math.abs(frame.offset[1]) < 0.15);
}

test('shipping catalog includes idle, gestures, talking and three built-in dances', () => {
  for (const name of ['idle', 'wave', 'nod', 'shake', 'dance_bounce', 'dance_sway', 'dance_step']) {
    assert.ok(MOTIONS.includes(name));
  }
  for (const name of ['neutral', 'happy', 'sad', 'angry', 'relaxed', 'surprised', 'excited']) {
    assert.ok(EMOTIONS.includes(name));
  }
});

test('idle breathes, arms are relaxed, and blink occurs without external assets', () => {
  const a = new MotionActor();
  const first = a.tick(0);
  let blink = false;
  for (let n = 0; n < 400; n++) {
    const f = a.tick(0.02);
    blink ||= f.expressions.blink > 0.5;
    finite(f);
  }
  assert.ok(blink);
  assert.notDeepEqual(first.pose.chest, a.tick(0.01).pose.chest);
  assert.ok(Math.abs(first.pose.leftUpperArm.rotation[2]) > 0.4);
});

for (const name of ['dance_bounce', 'dance_sway', 'dance_step']) {
  test(`${name} animates upper and lower body, loops, and stop returns to idle`, () => {
    const a = new MotionActor();
    a.send({ type: 'motion', name, loop: true, bpm: 120 });
    const first = run(a, 0.7);
    const next = run(a, 0.3);
    assert.equal(next.motion, name);
    assert.notDeepEqual(first.pose.hips, next.pose.hips);
    assert.notDeepEqual(first.pose.leftUpperArm, next.pose.leftUpperArm);
    assert.notDeepEqual(first.pose.leftUpperLeg, next.pose.leftUpperLeg);
    finite(next);
    a.send({ type: 'stop' });
    assert.equal(run(a, 0.5).motion, 'idle');
  });
}

test('one-shot gestures finish, bounded dance has a duration and no stuck pose', () => {
  const a = new MotionActor();
  a.send({ type: 'motion', name: 'wave', loop: false });
  assert.equal(run(a, 4).motion, 'idle');
  a.send({ type: 'motion', name: 'dance_step', duration: 1 });
  assert.equal(run(a, 1.5).motion, 'idle');
});

test('emotions smoothly crossfade and neutral clears every expression', () => {
  const a = new MotionActor();
  a.send({ type: 'emotion', name: 'happy', strength: 0.8 });
  assert.ok(run(a, 0.5).expressions.happy > 0.7);
  a.send({ type: 'emotion', name: 'sad' });
  const f = a.tick(1 / 60);
  assert.ok(f.expressions.happy > 0 && f.expressions.sad > 0);
  a.send({ type: 'emotion', name: 'neutral' });
  const neutral = run(a, 2);
  assert.ok(neutral.expressions.happy < 0.001);
  assert.ok(neutral.expressions.sad < 0.001);
});

test('speech visemes expire and stop cannot leave an open mouth', () => {
  const a = new MotionActor();
  a.send({ type: 'visemes', weights: { aa: 1, ih: 0.2 } });
  assert.ok(run(a, 0.1).expressions.aa > 0.5);
  assert.ok(run(a, 1).expressions.aa < 0.01);
  a.send({ type: 'speech', active: true });
  assert.ok(run(a, 0.4).expressions.aa > 0.01);
  a.send({ type: 'stop' });
  assert.ok(run(a, 0.5).expressions.aa < 0.01);
});

test('pause freezes time and resume does not jump or accumulate transforms', () => {
  const a = new MotionActor();
  a.send({ type: 'motion', name: 'dance_sway', loop: true });
  run(a, 1);
  a.send({ type: 'active', value: false });
  const paused = a.tick(0);
  assert.deepEqual(a.tick(300), paused);
  a.send({ type: 'active', value: true });
  finite(a.tick(300));
});

test('invalid commands, extreme values and mailbox floods fail explicitly', () => {
  const a = new MotionActor();
  for (const c of [null, {}, { type: 'eval', code: 'bad()' },
    { type: 'motion', name: '../dance' }, { type: 'motion', name: 'wave', bpm: Infinity },
    { type: 'motion', name: 'wave', loop: 'yes' }, { type: 'motion', name: 'wave', duration: -1 },
    { type: 'emotion', name: 'happy', strength: 9 }, { type: 'visemes', weights: { aa: NaN } },
    { type: 'active', value: 'false' }, { type: 'stop', code: 'injected' }]) {
    assert.throws(() => a.send(c));
  }
  for (let n = 0; n < 32; n++) a.send({ type: 'emotion', name: 'neutral' });
  assert.throws(() => a.send({ type: 'emotion', name: 'happy' }), /mailbox_full/);
  a.send({ type: 'stop' });
  assert.equal(a.tick(0).motion, 'idle');
});

test('repeated switches are continuous and every pose stays bounded', () => {
  const a = new MotionActor();
  for (let i = 0; i < 500; i++) {
    const before = a.tick(0);
    a.send({ type: 'motion', name: MOTIONS[i % MOTIONS.length], loop: true });
    const after = a.tick(0);
    assert.deepEqual(after.pose, before.pose);
    finite(a.tick(0.05));
  }
});

test('invalid clock deltas are rejected; long frames are clamped', () => {
  const a = new MotionActor();
  assert.throws(() => a.tick(-1));
  assert.throws(() => a.tick(NaN));
  finite(a.tick(1000));
});
