import assert from 'node:assert/strict';
import fs from 'node:fs';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { MotionActor, EMOTIONS, MOTIONS } from './motion.mjs';
import { validateModel } from './model.mjs';

const [modelPath, reportPath] = process.argv.slice(2);
assert.ok(modelPath && reportPath, 'model and report paths required');
const bytes = fs.readFileSync(modelPath);
const data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const checks = [];
function check(name, condition) {
  checks.push({name, passed: Boolean(condition)});
  fs.writeFileSync(reportPath, JSON.stringify({scope: 'Real VRM loader, humanoid and morph integration; no GPU or Android execution', checks}, null, 2));
  assert.ok(condition, name);
}
check('real VRM1 GLB accepted by APK validator', validateModel(data).version === '1.0');
const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));
const gltf = await loader.parseAsync(data, '');
const vrm = gltf.userData.vrm;
check('VRMLoaderPlugin returns genuine VRM', Boolean(vrm?.humanoid && vrm?.expressionManager));
const actor = new MotionActor();
const face = vrm.scene.getObjectByName('face_morphs');
check('face has actual morph-target geometry', Boolean(face?.geometry?.morphAttributes.position?.length));
function step(frames) {
  let frame;
  for (let i = 0; i < frames; i++) {
    frame = actor.tick(1 / 30);
    vrm.humanoid.setNormalizedPose(frame.pose);
    for (const [name, weight] of Object.entries(frame.expressions)) {
      if (vrm.expressionManager.getExpression(name)) vrm.expressionManager.setValue(name, weight);
    }
    vrm.update(1 / 30);
    vrm.scene.updateMatrixWorld(true);
  }
  return frame;
}
for (const name of EMOTIONS) {
  actor.send({type: 'emotion', name});
  step(30);
  const actual = name === 'excited' ? 'happy' : name;
  check('expression reaches mesh: ' + name, ['happy', 'sad', 'angry', 'relaxed', 'surprised'].every((preset, i) =>
    Math.abs(face.morphTargetInfluences[i] - (preset === actual ? 1 : 0)) < 0.001));
}
actor.send({type: 'emotion', name: 'neutral'});
for (const name of MOTIONS.filter(n => n !== 'idle')) {
  actor.send({type: 'motion', name, loop: name.startsWith('dance_')});
  step(20);
  const bones = ['head', 'leftUpperArm', 'rightUpperArm', 'leftUpperLeg', 'rightUpperLeg'];
  const before = bones.map(n => vrm.humanoid.getRawBoneNode(n).quaternion.toArray());
  step(5);
  check('motion changes real rig: ' + name, bones.some((n, i) =>
    vrm.humanoid.getRawBoneNode(n).quaternion.toArray().some((v, j) => Math.abs(v - before[i][j]) > 0.00001)));
}
actor.send({type: 'motion', name: 'wave', loop: false, duration: 0.5});
check('one-shot returns to idle', step(30).motion === 'idle');
actor.send({type: 'visemes', weights: {aa: 1}});
step(3);
check('viseme reaches real morph target', face.morphTargetInfluences[6] > 0.5);
step(60);
check('stale viseme decays to zero', face.morphTargetInfluences[6] < 0.001);
actor.send({type: 'motion', name: 'dance_step', loop: true});
step(20);
actor.send({type: 'stop'});
check('stop clears dance', step(15).motion === 'idle');
check('stop closes mouth', face.morphTargetInfluences.slice(6).every(v => v < 0.001));
actor.send({type: 'active', value: false});
const paused = step(1);
check('pause freezes rig state', JSON.stringify(step(120).pose) === JSON.stringify(paused.pose));
actor.send({type: 'active', value: true});
check('resume advances rig', JSON.stringify(step(20).pose) !== JSON.stringify(paused.pose));
let finite = true;
vrm.scene.traverse(o => { finite &&= o.matrixWorld.elements.every(Number.isFinite); });
check('all world matrices finite', finite);
assert.throws(() => actor.send({type: 'eval', code: 'evil()'}));
check('unknown operation rejected', true);
assert.throws(() => validateModel(new Uint8Array(32).buffer));
check('malformed VRM rejected', true);
VRMUtils.deepDispose(vrm.scene);
const report = {scope: 'Actual APK modules + real texture-free VRM; CPU loader/rig/morph integration, NOT GPU/Android E2E',
  passed: true, checks};
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
console.log(`${checks.length} real-loader integration checks PASS`);
