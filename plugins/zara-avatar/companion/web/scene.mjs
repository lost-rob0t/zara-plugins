import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { MotionActor, MOTIONS, EMOTIONS } from './motion.mjs';
import { validateModel } from './model.mjs';

const actor = new MotionActor();
const status = document.getElementById('status');
let vrm, renderer, frameId = null, active = true, fps = 30, previous = 0, disposed = false;
const scene = new THREE.Scene();
const root = new THREE.Group();
scene.add(root);
const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 50);
const gaze = new THREE.Object3D();
scene.add(gaze);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444466, 2));
const light = new THREE.DirectionalLight(0xffffff, 2.5);
light.position.set(2, 3, 4);
scene.add(light);

function resize() {
  if (!renderer) return;
  const w = Math.max(1, innerWidth), h = Math.max(1, innerHeight);
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function loop(now) {
  frameId = null;
  if (!active || disposed || !vrm) return;
  frameId = requestAnimationFrame(loop);
  if (previous && now - previous < 1000 / fps) return;
  const dt = previous ? Math.min((now - previous) / 1000, 0.1) : 0;
  previous = now;
  const f = actor.tick(dt);
  vrm.humanoid.setNormalizedPose(f.pose);
  root.position.fromArray(f.offset);
  for (const [name, weight] of Object.entries(f.expressions)) {
    if (vrm.expressionManager?.getExpression(name)) vrm.expressionManager.setValue(name, weight);
  }
  gaze.position.set(f.gaze[0], camera.position.y, camera.position.z);
  vrm.update(dt);
  renderer.render(scene, camera);
}
function setActive(value) {
  active = value;
  actor.send({ type: 'active', value });
  actor.tick(0);
  if (frameId !== null) cancelAnimationFrame(frameId);
  frameId = null;
  previous = 0;
  if (active && vrm && !disposed) frameId = requestAnimationFrame(loop);
}
function dispose() {
  if (disposed) return;
  disposed = true;
  setActive(false);
  controller.abort();
  if (vrm) { root.remove(vrm.scene); VRMUtils.deepDispose(vrm.scene); vrm = null; }
  renderer?.dispose();
  renderer?.forceContextLoss();
}
const controller = new AbortController();
window.companion = {
  ready: false,
  command(c) {
    if (disposed) return { ok: false, error: 'renderer_closed' };
    try {
      if (c?.type === 'active' && typeof c.value === 'boolean' && Object.keys(c).length === 2) setActive(c.value);
      else if (c?.type === 'quality' && [15, 30].includes(c.fps) && Object.keys(c).length === 2) fps = c.fps;
      else { if (!vrm) throw new Error('model_not_ready'); actor.send(c); }
      return { ok: true };
    } catch (e) {
      return { ok: false, error: ['mailbox_full', 'model_not_ready'].includes(e.message) ? e.message : 'invalid_command' };
    }
  },
  dispose,
};
window.addEventListener('resize', resize);
window.addEventListener('pagehide', dispose, { once: true });
document.addEventListener('visibilitychange', () => setActive(!document.hidden));

async function load() {
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/avatar.vrm', { signal: controller.signal });
    if (!response.ok) throw new Error('model_unavailable');
    const data = await response.arrayBuffer();
    validateModel(data);
    if (disposed) return;
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.setClearColor(0x000000, 0);
    document.body.appendChild(renderer.domElement);
    renderer.domElement.addEventListener('webglcontextlost', event => {
      event.preventDefault(); status.textContent = 'Renderer lost. Hide and show to restart.'; dispose();
    });
    const manager = new THREE.LoadingManager();
    manager.setURLModifier(url => {
      if (!url.startsWith('blob:')) throw new Error('external_resource_denied');
      return url;
    });
    const loader = new GLTFLoader(manager);
    loader.register(parser => new VRMLoaderPlugin(parser));
    const gltf = await loader.parseAsync(data, '');
    const loaded = gltf.userData.vrm;
    if (!loaded) { VRMUtils.deepDispose(gltf.scene); throw new Error('no_vrm'); }
    if (disposed) { VRMUtils.deepDispose(loaded.scene); return; }
    vrm = loaded;
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.traverse(object => { object.frustumCulled = false; });
    root.add(vrm.scene);
    vrm.humanoid.setNormalizedPose(actor.tick(0).pose);
    vrm.update(0);
    const bounds = new THREE.Box3().setFromObject(vrm.scene);
    const height = bounds.max.y - bounds.min.y;
    if (!Number.isFinite(height) || height < 0.1 || height > 10) throw new Error('invalid_dimensions');
    const center = bounds.getCenter(new THREE.Vector3());
    camera.position.set(center.x, center.y, center.z + height * 2.1);
    camera.lookAt(center);
    if (vrm.lookAt) vrm.lookAt.target = gaze;
    resize();
    const supported = EMOTIONS.filter(name => name === 'neutral' || vrm.expressionManager?.getExpression(name === 'excited' ? 'happy' : name));
    window.companion.supported = { motions: MOTIONS, emotions: supported };
    window.companion.ready = true;
    status.textContent = supported.length > 1 ? '' : 'Model has no supported facial expressions.';
    setActive(active);
  } catch {
    status.textContent = 'VRM unavailable or unsupported. Import another model, then show again.';
    dispose();
  } finally { clearTimeout(timeout); }
}
load();
