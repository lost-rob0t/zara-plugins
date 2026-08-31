// Zara's VRM scene controller.
//
// Owns the Three.js scene: one humanoid VRM (0.x or 1.0), MToon materials,
// spring bones, expressions, procedural presence (blink, gaze drift,
// breathing, subtle head sway), VRMA animation playback with crossfades, and
// audio-driven visemes. Everything is driven by the avatar protocol document
// stream forwarded from the Electron host; nothing here talks to a network.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin } from "@pixiv/three-vrm-animation";

const VISEME_EXPRESSIONS = {
  a: "aa",
  i: "ih",
  u: "ou",
  e: "ee",
  o: "oh",
};

const SEMANTIC_EXPRESSIONS = [
  "neutral",
  "happy",
  "sad",
  "angry",
  "annoyed",
  "relaxed",
  "surprised",
  "excited",
  "embarrassed",
];

const FRAMINGS = {
  half: { offset: new THREE.Vector3(0.0, 1.35, 1.1), lookAt: new THREE.Vector3(0.0, 1.4, 0.0) },
  full: { offset: new THREE.Vector3(0.0, 0.95, 2.6), lookAt: new THREE.Vector3(0.0, 0.9, 0.0) },
};

function mulberry32(seed) {
  let state = seed >>> 0;
  return function random() {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

class Scene {
  constructor() {
    this.canvas = document.createElement("canvas");
    document.body.appendChild(this.canvas);
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
    this.camera.position.copy(FRAMINGS.half.offset);
    this.camera.lookAt(FRAMINGS.half.lookAt);
    this.framing = "half";
    this._buildLights();
    this.vrm = null;
    this.mixer = null;
    this.clipSources = new Map();
    this.currentAction = null;
    this.visemes = { a: 0, i: 0, u: 0, e: 0, o: 0 };
    this.gazeMode = "auto";
    this.gazePoint = new THREE.Vector3(0, 1.4, 1.0);
    this.random = mulberry32(7);
    this.nextBlinkAt = 1 + this.random() * 4;
    this.blinkUntil = 0;
    this.clock = new THREE.Clock();
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.renderer.setAnimationLoop(() => this.update());
  }

  _buildLights() {
    this.hemisphere = new THREE.HemisphereLight(0xffffff, 0x334455, 0.9);
    this.scene.add(this.hemisphere);
    this.keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
    this.keyLight.position.set(1.0, 1.6, 1.2);
    this.scene.add(this.keyLight);
    this.fillLight = new THREE.DirectionalLight(0xbfd4ff, 0.5);
    this.fillLight.position.set(-1.4, 1.0, 0.6);
    this.scene.add(this.fillLight);
    this.rimLight = new THREE.DirectionalLight(0xfff0dd, 0.6);
    this.rimLight.position.set(0.0, 1.4, -1.6);
    this.scene.add(this.rimLight);
  }

  resize() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }

  // -- lifecycle ----------------------------------------------------------

  async loadAvatar(params) {
    if (!params || !params.path) {
      throw new Error("LoadAvatar requires a path");
    }
    const seed = Number.isFinite(params.seed) ? params.seed : 7;
    this.random = mulberry32(seed);
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(params.path);
    const vrm = gltf.userData.vrm;
    if (!vrm) {
      throw new Error("file loaded but no VRM was found inside");
    }
    if (this.vrm) {
      this.unloadAvatar();
    }
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    vrm.scene.traverse((object) => {
      object.frustumCulled = false;
    });
    this.vrm = vrm;
    this.scene.add(vrm.scene);
    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.expression(0);
    const expressions = this.availableExpressions();
    window.zaraAvatar.emit({
      event: "avatarLoaded",
      params: {
        avatarId: params.avatarId,
        expressions,
        vrmVersion: String(vrm.meta?.metaVersion || "unknown"),
      },
    });
    return { expressions, vrmVersion: String(vrm.meta?.metaVersion || "unknown") };
  }

  unloadAvatar() {
    if (this.mixer) {
      this.mixer.stopAllAction();
      this.mixer = null;
    }
    if (this.vrm) {
      VRMUtils.deepDispose(this.vrm.scene);
      this.scene.remove(this.vrm.scene);
      this.vrm = null;
    }
    this.currentAction = null;
  }

  availableExpressions() {
    if (!this.vrm?.expressionManager) {
      return ["neutral"];
    }
    const names = new Set(["neutral"]);
    for (const semantic of SEMANTIC_EXPRESSIONS) {
      if (this.vrm.expressionManager.getExpressionTrackName(semantic)) {
        names.add(semantic);
      }
    }
    return [...names];
  }

  // -- protocol handlers ---------------------------------------------------

  async handle(document) {
    const params = document.params || {};
    switch (document.command) {
      case "LoadAvatar":
        return await this.loadAvatar(params);
      case "UnloadAvatar":
        this.unloadAvatar();
        return {};
      case "SetExpression":
        this.expression(params.name || "neutral");
        return {};
      case "SetTransform":
        this.transform(params);
        return {};
      case "SetCamera":
        this.framing = params.framing || "half";
        return {};
      case "SetGaze":
        this.setGaze(params);
        return {};
      case "SetVisemes":
        this.visemes = { ...this.visemes, ...(params.weights || {}) };
        return {};
      case "SetLighting":
        this.lighting(params);
        return {};
      case "PlayAnimation":
        return await this.playAnimation(params);
      case "StopAnimation":
        this.stopAnimation();
        return {};
      default:
        throw new Error(`unsupported scene command ${document.command}`);
    }
  }

  expression(name) {
    const manager = this.vrm?.expressionManager;
    if (!manager) {
      return;
    }
    for (const semantic of SEMANTIC_EXPRESSIONS) {
      if (semantic === "neutral") {
        continue;
      }
      manager.setValue(semantic, semantic === name ? 1.0 : 0.0);
    }
  }

  transform(params) {
    if (!this.vrm) {
      return;
    }
    const scene = this.vrm.scene;
    if (Array.isArray(params.position) && params.position.length === 3) {
      scene.position.fromArray(params.position);
    }
    if (Array.isArray(params.rotation) && params.rotation.length === 3) {
      scene.rotation.set(
        THREE.MathUtils.degToRad(params.rotation[0]),
        THREE.MathUtils.degToRad(params.rotation[1]),
        THREE.MathUtils.degToRad(params.rotation[2]),
      );
    }
    if (Number.isFinite(params.scale)) {
      scene.scale.setScalar(params.scale);
    }
  }

  setGaze(params) {
    if (typeof params.target === "string") {
      this.gazeMode = params.target;
    } else if (Array.isArray(params.point) && params.point.length === 3) {
      this.gazeMode = "point";
      this.gazePoint.fromArray(params.point);
    }
  }

  lighting(params) {
    if (Number.isFinite(params.exposure)) {
      this.renderer.toneMappingExposure = params.exposure;
    }
    if (Number.isFinite(params.keyIntensity)) {
      this.keyLight.intensity = params.keyIntensity;
    }
    if (Number.isFinite(params.fillIntensity)) {
      this.fillLight.intensity = params.fillIntensity;
    }
    if (Number.isFinite(params.rimIntensity)) {
      this.rimLight.intensity = params.rimIntensity;
    }
    if (Number.isFinite(params.hemisphereIntensity)) {
      this.hemisphere.intensity = params.hemisphereIntensity;
    }
  }

  async loadClipSource(clip) {
    if (this.clipSources.has(clip)) {
      return this.clipSources.get(clip);
    }
    const manifest = await this.loadManifest();
    const file = manifest[clip];
    if (!file) {
      throw new Error(`animation ${clip} is not available in the manifest`);
    }
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.loadAsync(`./animations/${file}`);
    const animation = gltf.userData.vrmAnimations?.[0];
    if (!animation) {
      throw new Error(`animation file for ${clip} contains no VRM animation`);
    }
    this.clipSources.set(clip, animation);
    return animation;
  }

  async loadManifest() {
    if (this.manifest) {
      return this.manifest;
    }
    try {
      const response = await fetch("./animations/manifest.json");
      this.manifest = response.ok ? await response.json() : {};
    } catch {
      this.manifest = {};
    }
    return this.manifest;
  }

  async playAnimation(params) {
    if (!this.vrm || !this.mixer) {
      throw new Error("no avatar is loaded");
    }
    const animation = await this.loadClipSource(params.clip);
    const clip = animation.createAnimationClip(this.vrm);
    const action = this.mixer.clipAction(clip);
    action.reset();
    action.setLoop(
      params.loop ? THREE.LoopRepeat : THREE.LoopOnce,
      params.loop ? Infinity : 1,
    );
    action.clampWhenFinished = !params.loop;
    action.timeScale = Math.max(0.05, params.speed || 1.0);
    const crossfade = Math.max(0.01, params.crossfade || 1.0);
    if (this.currentAction && this.currentAction !== action) {
      this.currentAction.fadeOut(crossfade);
    }
    action.fadeIn(crossfade).play();
    this.currentAction = action;
    return { clip: params.clip };
  }

  stopAnimation() {
    if (this.currentAction) {
      this.currentAction.fadeOut(0.2);
      this.currentAction = null;
    }
  }

  // -- procedural presence ---------------------------------------------------

  update() {
    const delta = this.clock.getDelta();
    const elapsed = this.clock.elapsedTime;
    if (this.vrm) {
      this.updateBlink(elapsed);
      this.updateGaze(delta, elapsed);
      this.updateVisemes(delta);
      this.updatePresenceSway(elapsed);
      this.mixer?.update(delta);
      this.vrm.update(delta);
    }
    this.updateCamera(delta);
    this.renderer.render(this.scene, this.camera);
  }

  updateBlink(elapsed) {
    const manager = this.vrm?.expressionManager;
    if (!manager) {
      return;
    }
    if (elapsed >= this.nextBlinkAt) {
      this.blinkUntil = elapsed + 0.12;
      this.nextBlinkAt = elapsed + 1.5 + this.random() * 4.5;
    }
    const blinking = elapsed < this.blinkUntil;
    manager.setValue("blink", blinking ? 1.0 : 0.0);
  }

  updateGaze(delta, elapsed) {
    const lookAt = this.vrm?.lookAt;
    if (!lookAt) {
      return;
    }
    if (!this.gazeTarget) {
      this.gazeTarget = new THREE.Object3D();
      this.scene.add(this.gazeTarget);
      lookAt.target = this.gazeTarget;
    }
    if (this.gazeMode === "user") {
      this.gazeTarget.position.copy(this.camera.position);
    } else if (this.gazeMode === "center") {
      this.gazeTarget.position.set(0, 1.4, 1.0);
    } else if (this.gazeMode === "point") {
      this.gazeTarget.position.copy(this.gazePoint);
    } else {
      // Bounded autonomous drift; never leaves the general camera direction.
      this.gazeTarget.position.set(
        Math.sin(elapsed * 0.23) * 0.4,
        1.4 + Math.sin(elapsed * 0.17) * 0.12,
        1.0,
      );
    }
  }

  updateVisemes(delta) {
    const manager = this.vrm?.expressionManager;
    if (!manager) {
      return;
    }
    const follow = Math.min(1.0, delta * 18.0);
    for (const [viseme, expression] of Object.entries(VISEME_EXPRESSIONS)) {
      const target = Math.max(0.0, Math.min(1.0, Number(this.visemes[viseme]) || 0.0));
      const current = manager.getValue(expression) ?? 0.0;
      manager.setValue(expression, current + (target - current) * follow);
    }
  }

  updatePresenceSway(elapsed) {
    const humanoid = this.vrm?.humanoid;
    if (!humanoid) {
      return;
    }
    const head = humanoid.getNormalizedBoneNode("head");
    if (head) {
      head.rotation.x = Math.sin(elapsed * 0.45) * 0.015;
      head.rotation.z = Math.sin(elapsed * 0.31) * 0.012;
    }
    const chest = humanoid.getNormalizedBoneNode("chest");
    if (chest) {
      chest.rotation.x = Math.sin(elapsed * 0.9) * 0.004;
    }
  }

  updateCamera(delta) {
    const preset = FRAMINGS[this.framing] || FRAMINGS.half;
    const follow = Math.min(1.0, delta * 4.0);
    this.camera.position.lerp(preset.offset, follow);
    this.camera.lookAt(preset.lookAt);
  }
}

const scene = new Scene();
window.zaraAvatar.onCommand(async (document) => {
  try {
    const result = await scene.handle(document);
    window.zaraAvatar.respond({ id: document.id, ok: true, result });
  } catch (error) {
    window.zaraAvatar.respond({
      id: document.id,
      ok: false,
      error: String(error?.message || error),
    });
  }
});
window.zaraAvatar.ready();
