export const MOTIONS = Object.freeze(['idle', 'wave', 'nod', 'shake', 'dance_bounce', 'dance_sway', 'dance_step']);
export const EMOTIONS = Object.freeze(['neutral', 'happy', 'sad', 'angry', 'relaxed', 'surprised', 'excited']);
const FACES = ['happy', 'sad', 'angry', 'relaxed', 'surprised'];
const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];
const BONES = ['hips', 'spine', 'chest', 'neck', 'head', 'leftUpperArm', 'rightUpperArm',
  'leftLowerArm', 'rightLowerArm', 'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg'];
const FIELDS = Object.freeze({
  motion: ['type', 'name', 'loop', 'bpm', 'duration'], emotion: ['type', 'name', 'strength'],
  visemes: ['type', 'weights'], speech: ['type', 'active'], active: ['type', 'value'], stop: ['type'],
});

function record(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && [Object.prototype, null].includes(Object.getPrototypeOf(value));
}
function number(value, lo, hi) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < lo || value > hi) {
    throw new Error('invalid_number');
  }
  return value;
}
function command(input) {
  if (!record(input) || !Object.hasOwn(FIELDS, input.type)) throw new Error('invalid_command');
  if (Object.keys(input).some(key => !FIELDS[input.type].includes(key))) throw new Error('unknown_field');
  const c = { ...input };
  if (c.type === 'motion') {
    if (!MOTIONS.includes(c.name)) throw new Error('unknown_motion');
    c.bpm = number(c.bpm ?? 120, 40, 200);
    c.duration = number(c.duration ?? (c.name.startsWith('dance_') ? 10 : 3), 0.25, 120);
    c.loop ??= c.name === 'idle';
    if (typeof c.loop !== 'boolean') throw new Error('invalid_loop');
  } else if (c.type === 'emotion') {
    if (!EMOTIONS.includes(c.name)) throw new Error('unknown_emotion');
    c.strength = number(c.strength ?? 1, 0, 1);
  } else if (c.type === 'visemes') {
    if (!record(c.weights) || Object.keys(c.weights).some(key => !VISEMES.includes(key))) {
      throw new Error('invalid_visemes');
    }
    c.weights = Object.fromEntries(VISEMES.map(name => [name, number(c.weights[name] ?? 0, 0, 1)]));
  } else if (c.type === 'speech' && typeof c.active !== 'boolean') throw new Error('invalid_speech');
  else if (c.type === 'active' && typeof c.value !== 'boolean') throw new Error('invalid_active');
  return c;
}

function emptyPose() { return Object.fromEntries(BONES.map(name => [name, [0, 0, 0]])); }
function quaternion([x, y, z]) {
  const [a, b, c] = [x / 2, y / 2, z / 2];
  const [sx, sy, sz, cx, cy, cz] = [Math.sin(a), Math.sin(b), Math.sin(c), Math.cos(a), Math.cos(b), Math.cos(c)];
  return [sx * cy * cz + cx * sy * sz, cx * sy * cz - sx * cy * sz,
    cx * cy * sz + sx * sy * cz, cx * cy * cz - sx * sy * sz];
}
function blend(a, b, f) { return a.map((v, i) => v + (b[i] - v) * f); }

function sample(name, age, time, bpm) {
  const pose = emptyPose();
  const offset = [0, 0, 0];
  pose.leftUpperArm[2] = -1.15;
  pose.rightUpperArm[2] = 1.15;
  pose.leftLowerArm[1] = -0.1;
  pose.rightLowerArm[1] = 0.1;
  pose.chest[0] = Math.sin(time * 1.7) * 0.018;
  pose.head[1] = Math.sin(time * 0.37) * 0.035;
  pose.head[2] = Math.sin(time * 0.6) * 0.018;
  if (name === 'wave') {
    pose.rightUpperArm = [0.1, 0, -0.65];
    pose.rightLowerArm = [0, 0, -0.65 + Math.sin(age * 10) * 0.3];
  } else if (name === 'nod') pose.head[0] = Math.sin(age * 6) * 0.2;
  else if (name === 'shake') pose.head[1] = Math.sin(age * 6) * 0.25;
  else if (name.startsWith('dance_')) {
    const beat = age * bpm / 60 * Math.PI * 2;
    const sway = Math.sin(beat / 2), bounce = (1 - Math.cos(beat)) / 2;
    pose.hips = [bounce * 0.045, sway * 0.12, sway * 0.06];
    pose.spine[2] = -sway * 0.07;
    pose.head[0] = bounce * 0.05;
    pose.leftUpperLeg[0] = bounce * -0.12;
    pose.rightUpperLeg[0] = bounce * -0.12;
    pose.leftLowerLeg[0] = bounce * 0.24;
    pose.rightLowerLeg[0] = bounce * 0.24;
    pose.leftUpperArm = [Math.sin(beat) * 0.15, 0, -0.9 + sway * 0.18];
    pose.rightUpperArm = [-Math.sin(beat) * 0.15, 0, 0.9 + sway * 0.18];
    offset[1] = -bounce * 0.025;
    if (name === 'dance_sway') {
      offset[0] = sway * 0.035;
      pose.leftUpperArm[2] = -0.55 + sway * 0.3;
      pose.rightUpperArm[2] = 0.55 + sway * 0.3;
      pose.chest[1] = sway * 0.12;
    } else if (name === 'dance_step') {
      const step = Math.sin(beat / 2);
      offset[0] = step * 0.055;
      pose.leftUpperLeg[0] -= Math.max(0, step) * 0.28;
      pose.rightUpperLeg[0] -= Math.max(0, -step) * 0.28;
      pose.leftLowerLeg[0] += Math.max(0, step) * 0.3;
      pose.rightLowerLeg[0] += Math.max(0, -step) * 0.3;
      pose.leftUpperArm[0] = step * 0.4;
      pose.rightUpperArm[0] = -step * 0.4;
    }
  }
  return { pose, offset };
}

export class MotionActor {
  constructor() {
    this.mailbox = [];
    this.active = true;
    this.time = 0;
    this.age = 0;
    this.transition = 1;
    this.motion = 'idle';
    this.bpm = 120;
    this.loop = true;
    this.duration = 3;
    this.emotion = 'neutral';
    this.strength = 1;
    this.speechRemaining = 0;
    this.visemeRemaining = 0;
    this.visemes = {};
    this.expressions = Object.fromEntries([...FACES, ...VISEMES, 'blink'].map(name => [name, 0]));
    this.current = sample('idle', 0, 0, 120);
    this.from = this.current;
  }

  send(input) {
    const c = command(input);
    if (c.type === 'stop' || (c.type === 'active' && !c.value)) {
      this.mailbox.length = 0;
      this.apply(c);
      return;
    }
    if (this.mailbox.length >= 32) throw new Error('mailbox_full');
    this.mailbox.push(c);
  }

  start(c) {
    this.from = this.current;
    this.age = 0;
    this.transition = 0;
    this.motion = c.name;
    this.loop = c.loop;
    this.bpm = c.bpm;
    this.duration = c.duration;
  }

  apply(c) {
    switch (c.type) {
      case 'motion': this.start(c); break;
      case 'emotion': this.emotion = c.name; this.strength = c.strength; break;
      case 'visemes': this.visemes = c.weights; this.visemeRemaining = 0.25; this.speechRemaining = 0; break;
      case 'speech':
        this.speechRemaining = c.active ? 10 : 0;
        this.visemeRemaining = 0;
        this.visemes = {};
        break;
      case 'active': this.active = c.value; this.speechRemaining = 0; this.visemeRemaining = 0; break;
      case 'stop':
        this.start({ name: 'idle', loop: true, bpm: 120, duration: 3 });
        this.speechRemaining = 0;
        this.visemeRemaining = 0;
        this.visemes = {};
        for (const name of VISEMES) this.expressions[name] = 0;
        break;
    }
  }

  tick(seconds) {
    number(seconds, 0, Number.MAX_VALUE);
    for (const c of this.mailbox.splice(0, 32)) this.apply(c);
    if (this.active) {
      const dt = Math.min(seconds, 0.1);
      this.time = (this.time + dt) % 3600;
      this.age += dt;
      if (!this.loop && this.age >= this.duration) this.start({ name: 'idle', loop: true, bpm: 120, duration: 3 });
      if (this.loop) this.age %= 3600;
      this.transition = Math.min(1, this.transition + dt / 0.25);
      const weight = this.transition * this.transition * (3 - 2 * this.transition);
      const target = sample(this.motion, this.age, this.time, this.bpm);
      this.current = {
        pose: Object.fromEntries(BONES.map(name => [name, blend(this.from.pose[name], target.pose[name], weight)])),
        offset: blend(this.from.offset, target.offset, weight),
      };
      const follow = 1 - Math.exp(-dt * 18);
      for (const name of FACES) {
        const selected = this.emotion === 'excited' ? 'happy' : this.emotion;
        const targetValue = name === selected ? this.strength : 0;
        this.expressions[name] += (targetValue - this.expressions[name]) * follow;
      }
      this.speechRemaining = Math.max(0, this.speechRemaining - dt);
      this.visemeRemaining = Math.max(0, this.visemeRemaining - dt);
      for (const name of VISEMES) {
        let value = this.visemeRemaining > 0 ? (this.visemes[name] ?? 0) : 0;
        if (this.speechRemaining > 0 && name === 'aa') value = 0.15 + 0.55 * Math.abs(Math.sin(this.time * 13));
        this.expressions[name] += (value - this.expressions[name]) * follow;
      }
      const blinkPhase = this.time % 4.3;
      this.expressions.blink = blinkPhase > 3.1 && blinkPhase < 3.26
        ? Math.sin((blinkPhase - 3.1) / 0.16 * Math.PI) : 0;
    }
    return {
      motion: this.motion, emotion: this.emotion,
      pose: Object.fromEntries(BONES.map(name => [name, { rotation: quaternion(this.current.pose[name]) }])),
      offset: [...this.current.offset], expressions: { ...this.expressions },
      gaze: [Math.sin(this.time * 0.23) * 0.15, 1.4, 2],
    };
  }
}
