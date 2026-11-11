import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import * as CANNON from 'cannon-es';
import { KeySound, PROFILE_LIST } from './sound.js';

// ---------------------------------------------------------------- 主题
const mq = window.matchMedia('(prefers-color-scheme: dark)');
const applyTheme = () => {
  document.documentElement.dataset.theme = mq.matches ? 'dark' : 'light';
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#f5f5f7';
  if (scene) scene.background = new THREE.Color(bg);
  if (ground) ground.material.opacity = mq.matches ? 0.6 : 0.3;
};

// ---------------------------------------------------------------- 场景
const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.0;

let scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.03).texture;
scene.environmentIntensity = 0.85;

const camera = new THREE.PerspectiveCamera(30, 1, 0.02, 20);
const controls = new OrbitControls(camera, canvas);
const TARGET = new THREE.Vector3(0, 0.012, 0.0);
controls.target.copy(TARGET);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.18;
controls.maxDistance = 1.8;
controls.maxPolarAngle = Math.PI * 0.485;
controls.enablePan = false;

const sun = new THREE.DirectionalLight(0xfff4e6, 2.4);
sun.position.set(-0.45, 1.0, 0.35);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
Object.assign(sun.shadow.camera, { left: -0.6, right: 0.6, top: 0.6, bottom: -0.6, near: 0.2, far: 3 });
sun.shadow.bias = -0.00012;
sun.shadow.normalBias = 0.0005;
sun.shadow.radius = 4;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xdfe9ff, 0.5);
fill.position.set(0.6, 0.5, 0.7);
scene.add(fill);

let ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.3 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);
applyTheme();
mq.addEventListener('change', applyTheme);

const DEFAULT_DIR = new THREE.Vector3(0, 0.62, 0.78).normalize();
function fitDistance() {
  const aspect = window.innerWidth / window.innerHeight;
  const vfov = THREE.MathUtils.degToRad(camera.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
  return Math.max(0.21 / Math.tan(hfov / 2), 0.13 / Math.tan(vfov / 2)) * 1.12;
}
let camReady = false;
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  if (!w || !h) return;                 // 窗口还没布局好（比如后台标签页）
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  if (!camReady) {
    camera.position.copy(TARGET).addScaledVector(DEFAULT_DIR, fitDistance());
    camReady = true;
  }
}
resize();
window.addEventListener('resize', resize);

// ---------------------------------------------------------------- 物理世界（键帽刚体）
// cannon 的容差按“米级”物体调的，键帽只有 18mm，所以物理世界整体放大 S 倍。
const S = 20;
const world = new CANNON.World({ gravity: new CANNON.Vec3(0, -9.81 * S, 0) });
world.allowSleep = true;
world.broadphase = new CANNON.SAPBroadphase(world);
world.solver.iterations = 14;
world.defaultContactMaterial.friction = 0.38;
world.defaultContactMaterial.restitution = 0.32;
world.addBody(new CANNON.Body({ type: CANNON.Body.STATIC, shape: new CANNON.Plane(), quaternion: new CANNON.Quaternion().setFromEuler(-Math.PI / 2, 0, 0) }));

const sound = new KeySound();
const keys = {};          // code -> key
const keyList = [];
const pickables = [];
const tweens = [];
let root, knob, rootBaseY = 0;
const rootQ = new THREE.Quaternion();
const upW = new THREE.Vector3(0, 1, 0);
const board = { y: 0, v: 0 };
const TRAVEL = 4.0;       // mm

function addStatic(localCenter, half) {
  const p = root.localToWorld(localCenter.clone());
  const b = new CANNON.Body({ type: CANNON.Body.STATIC, shape: new CANNON.Box(new CANNON.Vec3(half.x * S, half.y * S, half.z * S)) });
  b.position.set(p.x * S, p.y * S, p.z * S);
  b.quaternion.set(rootQ.x, rootQ.y, rootQ.z, rootQ.w);
  return b;
}

new GLTFLoader().load(import.meta.env.BASE_URL + 'models/keyboard.glb', (gltf) => {
  scene.add(gltf.scene);
  for (const n of ['DeskMat', 'Cable', 'Plug']) {
    const o = gltf.scene.getObjectByName(n);
    if (o) o.visible = false;
  }
  root = gltf.scene.getObjectByName('Keyboard');
  knob = root.getObjectByName('Knob');
  rootBaseY = root.position.y;
  gltf.scene.updateMatrixWorld(true);
  root.getWorldQuaternion(rootQ);
  upW.set(0, 1, 0).applyQuaternion(rootQ);

  const seen = new Set();
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = o.receiveShadow = true;
    const m = o.material;
    if (seen.has(m)) return;
    seen.add(m);
    if (m.name.startsWith('Keycap')) { m.roughness = 0.5; m.envMapIntensity = 0.75; }
    if (m.name.startsWith('Legend')) { m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -2; m.roughness = 0.55; }
    if (m.name === 'Case_Aluminum') { m.roughness = 0.36; m.metalness = 1; }
    if (m.name === 'Plate') m.envMapIntensity = 0.3;
  });

  // 外壳 + 旋钮的静态碰撞体
  world.addBody(addStatic(new THREE.Vector3(0, 0.008 - 0.02, 0), new THREE.Vector3(0.1633, 0.02, 0.0704)));
  world.addBody(addStatic(new THREE.Vector3(knob.position.x, 0.008, knob.position.z), new THREE.Vector3(0.008, 0.008, 0.008)));

  for (const cap of root.children.slice()) {
    if (!cap.name.startsWith('Key_')) continue;
    const code = cap.userData.code || cap.name.slice(4);
    const w = cap.userData.w || 1;
    const stem = cap.getObjectByName('Stem_' + code);
    stem.position.copy(cap.position);
    root.add(stem);
    cap.geometry.computeBoundingBox();
    const bb = cap.geometry.boundingBox;
    const half = bb.getSize(new THREE.Vector3()).multiplyScalar(0.5);
    const center = bb.getCenter(new THREE.Vector3());
    const rest = cap.position.clone();
    const k = {
      code, cap, stem, rest, w, half, center,
      x: 0, v: 0, holders: new Set(), held: false,
      rx: 0, rz: 0, vrx: 0, vrz: 0, trx: 0, trz: 0,
      popped: false, restoring: false, body: null, lastHit: 0,
      pan: THREE.MathUtils.clamp(rest.x / 0.16, -1, 1),
      big: w >= 2 ? 0.8 : w >= 1.5 ? 0.4 : 0,
      space: code === 'Space',
    };
    const topY = rest.y + half.y * 2;
    k.staticCap = addStatic(new THREE.Vector3(rest.x, topY / 2, rest.z), new THREE.Vector3(half.x, topY / 2, half.z));
    world.addBody(k.staticCap);
    world.addBody(addStatic(new THREE.Vector3(rest.x, 0.0046, rest.z), new THREE.Vector3(0.0065, 0.0046, 0.0065)));
    cap.userData.key = k;
    pickables.push(cap);
    cap.children.forEach((c) => { c.userData.key = k; pickables.push(c); });
    keys[code] = k;
    keyList.push(k);
  }
  pickables.push(knob);
  document.getElementById('loading').classList.add('hide');
}, undefined, (err) => {
  document.getElementById('loading').textContent = '模型加载失败：' + (err?.message || err);
});

// ---------------------------------------------------------------- 按键
function press(k, src, local) {
  if (k.holders.has(src)) return;
  k.holders.add(src);
  if (k.holders.size > 1) return;
  k.held = true;
  sound.down({ pan: k.pan, big: k.big, space: k.space, bare: k.popped });
  // 按在键帽偏心处，键帽会朝那一边微微歪一下
  const stiff = 1 / (1 + k.big * 3);
  if (local) {
    k.trz = -THREE.MathUtils.clamp(local.x / k.half.x, -1, 1) * 0.022 * stiff;
    k.trx = THREE.MathUtils.clamp(local.z / k.half.z, -1, 1) * 0.022;
  } else {
    k.trz = (Math.random() - 0.5) * 0.014 * stiff;
    k.trx = (Math.random() - 0.5) * 0.014;
  }
}

function release(k, src) {
  if (!k.holders.delete(src) || k.holders.size) return;
  k.held = false;
  k.trx = k.trz = 0;
  sound.up({ pan: k.pan, big: k.big, space: k.space, bare: k.popped });
}

function stepKey(k, dt) {
  // 轴体：按住时手指的力压过弹簧；松开后弹簧 + 预压把轴心顶回去。单位 mm、秒。
  if (k.held || k.x > 0 || k.v !== 0) {
    const a = k.held ? 15000 - 1600 * k.x - 10 * k.v : -(9500 + 1600 * k.x) - 10 * k.v;
    k.v += a * dt;
    k.x += k.v * dt;
    if (k.x >= TRAVEL) {            // 触底
      k.x = TRAVEL;
      if (k.v > 40) { board.v -= k.v * 7e-5; k.v = -k.v * 0.16; } else k.v = 0;
    } else if (k.x <= 0) {          // 回弹撞到上盖
      k.x = 0;
      k.v = k.v < -60 ? -k.v * 0.2 : 0;
    }
  }
  const W = 120, Z = 0.28;
  k.vrx += (-W * W * (k.rx - k.trx) - 2 * Z * W * k.vrx) * dt;
  k.rx += k.vrx * dt;
  k.vrz += (-W * W * (k.rz - k.trz) - 2 * Z * W * k.vrz) * dt;
  k.rz += k.vrz * dt;
}

// ---------------------------------------------------------------- 拔键帽 / 刚体
const _v = new THREE.Vector3(), _q = new THREE.Quaternion();

function pop(k, power = 1) {
  if (k.popped) return kick(k);
  k.popped = true;
  k.restoring = false;
  scene.attach(k.cap);
  const body = new CANNON.Body({ mass: 0.4 + k.w * 0.6, shape: new CANNON.Box(new CANNON.Vec3(k.half.x * S, k.half.y * S, k.half.z * S)) });
  k.cap.getWorldQuaternion(_q);
  k.cap.localToWorld(_v.copy(k.center)).addScaledVector(upW, 0.0045);
  body.position.set(_v.x * S, _v.y * S, _v.z * S);
  body.quaternion.set(_q.x, _q.y, _q.z, _q.w);
  const sp = (1.1 + Math.random() * 0.7) * power;
  body.velocity.set((upW.x * sp + (Math.random() - 0.5) * 0.5) * S, upW.y * sp * S, (upW.z * sp + (Math.random() - 0.5) * 0.5) * S);
  body.angularVelocity.set((Math.random() - 0.5) * 22, (Math.random() - 0.5) * 8, (Math.random() - 0.5) * 22);
  body.sleepSpeedLimit = 0.5;
  body.sleepTimeLimit = 0.4;
  body.linearDamping = 0.05;
  body.angularDamping = 0.12;
  body.addEventListener('collide', (e) => {
    const vi = Math.abs(e.contact.getImpactVelocityAlongNormal()) / S;
    const now = performance.now();
    if (vi > 0.12 && now - k.lastHit > 45) {
      k.lastHit = now;
      sound.clack(Math.min(0.9, vi * 0.55), THREE.MathUtils.clamp(body.position.x / S / 0.3, -1, 1), 1.15 - k.big * 0.3);
    }
  });
  world.removeBody(k.staticCap);
  world.addBody(body);
  k.body = body;
  k.lastHit = performance.now() + 60;
  sound.pop(k.pan);
}

function kick(k) {
  if (!k.body) return;
  k.body.wakeUp();
  k.body.velocity.set((Math.random() - 0.5) * 0.8 * S, (0.9 + Math.random() * 0.6) * S, (Math.random() - 0.5) * 0.8 * S);
  k.body.angularVelocity.set((Math.random() - 0.5) * 24, (Math.random() - 0.5) * 10, (Math.random() - 0.5) * 24);
}

function restore(k, delay) {
  if (!k.popped || k.restoring) return;
  k.restoring = true;
  if (k.body) { world.removeBody(k.body); k.body = null; }
  root.attach(k.cap);
  const p0 = k.cap.position.clone(), q0 = k.cap.quaternion.clone();
  const lift = 0.02 + Math.min(0.05, p0.distanceTo(k.rest) * 0.25);
  tweens.push({
    t: -delay, dur: 0.5,
    update(u) {
      const e = 1 - Math.pow(1 - u, 3);
      k.cap.position.lerpVectors(p0, k.rest, e);
      k.cap.position.y += Math.sin(Math.PI * Math.min(1, u * 1.15)) * lift * (1 - u * 0.3);
      k.cap.quaternion.slerpQuaternions(q0, _q.identity(), e);
    },
    done() {
      k.popped = k.restoring = false;
      k.cap.quaternion.identity();
      world.addBody(k.staticCap);
      k.x = 2.2; k.v = 0;               // 按到位再弹起来
      sound.down({ pan: k.pan, big: k.big, space: k.space });
    },
  });
}

let explodeTimers = [];
function explodeAll() {
  sound.ensure();
  const list = keyList.filter((k) => !k.popped).sort((a, b) => a.rest.x - b.rest.x + (Math.random() - 0.5) * 0.03);
  list.forEach((k, i) => explodeTimers.push(setTimeout(() => pop(k, 1.25), i * 9)));
}
function restoreAll() {
  explodeTimers.forEach(clearTimeout);
  explodeTimers = [];
  keyList.filter((k) => k.popped).sort((a, b) => a.rest.x - b.rest.x).forEach((k, i) => restore(k, i * 0.012));
}

// ---------------------------------------------------------------- 输入：实体键盘
const typedEl = document.getElementById('typedText');
let typed = '';
function showTyped() { typedEl.textContent = typed.slice(-42); }

window.addEventListener('keydown', (e) => {
  const k = keys[e.code];
  if (!k) return;
  if (!(e.ctrlKey || e.metaKey) && !['F5', 'F11', 'F12'].includes(e.code)) e.preventDefault();
  if (e.repeat) return;
  press(k, 'kbd');
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) typed += e.key;
  else if (e.code === 'Backspace') typed = typed.slice(0, -1);
  else if (e.code === 'Enter' || e.code === 'Escape') typed = '';
  showTyped();
});
window.addEventListener('keyup', (e) => { const k = keys[e.code]; if (k) release(k, 'kbd'); });
window.addEventListener('blur', () => keyList.forEach((k) => { release(k, 'kbd'); release(k, 'ptr'); }));

// ---------------------------------------------------------------- 输入：鼠标
const ray = new THREE.Raycaster();
const ndc = new THREE.Vector2();
let pullMode = false, ptrKey = null;

function pick(e) {
  if (!root) return null;
  const r = canvas.getBoundingClientRect();
  ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  return ray.intersectObjects(pickables, false)[0] || null;
}

canvas.addEventListener('pointerdown', (e) => {
  sound.ensure();
  const hit = pick(e);
  const k = hit?.object.userData.key;
  if (!k) return;
  controls.enabled = false;
  canvas.setPointerCapture(e.pointerId);
  if (e.button === 2 || pullMode || e.shiftKey || k.popped) { if (!k.restoring) pop(k); return; }
  if (e.button !== 0) return;
  ptrKey = k;
  press(k, 'ptr', k.cap.worldToLocal(hit.point.clone()));
});
const endPtr = () => {
  if (ptrKey) release(ptrKey, 'ptr');
  ptrKey = null;
  controls.enabled = true;
};
canvas.addEventListener('pointerup', endPtr);
canvas.addEventListener('pointercancel', endPtr);
canvas.addEventListener('contextmenu', (e) => e.preventDefault());

// 旋钮：滚轮一格一格地拧，同时调音量
let knobAngle = 0;
const volEl = document.getElementById('volume'), volVal = document.getElementById('volumeVal');
function setVolume(v, fromKnob) {
  v = Math.round(THREE.MathUtils.clamp(v, 0, 100));
  sound.setVolume(v / 100);
  volEl.value = v;
  volVal.textContent = v;
  volEl.style.background = `linear-gradient(to right, var(--primary) ${v}%, var(--fill) ${v}%)`;
  if (!fromKnob) knobAngle = -(v / 100) * Math.PI * 1.5;
}
canvas.addEventListener('wheel', (e) => {
  if (pick(e)?.object !== knob) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const dir = e.deltaY < 0 ? 1 : -1;
  knobAngle -= dir * (Math.PI / 12);
  setVolume(+volEl.value + dir * 5, true);
  sound.tick();
}, { capture: true, passive: false });

// ---------------------------------------------------------------- 界面
const segEl = document.getElementById('profiles');
PROFILE_LIST.forEach((p) => {
  const b = document.createElement('button');
  b.textContent = p.label;
  b.classList.toggle('active', p.id === sound.profile);
  b.onclick = () => {
    sound.profile = p.id;
    [...segEl.children].forEach((c) => c.classList.toggle('active', c === b));
    sound.down({}); setTimeout(() => sound.up({}), 90);
    b.blur();
  };
  segEl.appendChild(b);
});
volEl.addEventListener('input', () => setVolume(+volEl.value));
volEl.addEventListener('change', () => volEl.blur());
setVolume(70);
const pullBtn = document.getElementById('pullMode');
pullBtn.onclick = () => { pullMode = !pullMode; pullBtn.classList.toggle('active', pullMode); pullBtn.blur(); };
document.getElementById('explode').onclick = (e) => { explodeAll(); e.currentTarget.blur(); };
document.getElementById('restore').onclick = (e) => { restoreAll(); e.currentTarget.blur(); };
document.getElementById('resetView').onclick = (e) => {
  const p0 = camera.position.clone(), p1 = TARGET.clone().addScaledVector(DEFAULT_DIR, fitDistance());
  tweens.push({ t: 0, dur: 0.7, update(u) { camera.position.lerpVectors(p0, p1, 1 - Math.pow(1 - u, 3)); }, done() {} });
  e.currentTarget.blur();
};

// ---------------------------------------------------------------- 主循环
const clock = new THREE.Clock();
const SUB = 1 / 1200;
let acc = 0;

function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.05);
  if (root) {
    acc += dt;
    while (acc >= SUB) {
      for (let i = 0; i < keyList.length; i++) stepKey(keyList[i], SUB);
      // 整块键盘坐在垫子上：被敲一下会轻微下沉再回弹
      board.v += (-150 * 150 * board.y - 2 * 0.5 * 150 * board.v) * SUB;
      board.y += board.v * SUB;
      acc -= SUB;
    }
    root.position.y = rootBaseY + board.y;
    world.step(1 / 180, dt, 6);
    for (const k of keyList) {
      const y = k.rest.y - k.x * 0.001;
      k.stem.position.y = y;
      if (k.body) {
        const b = k.body;
        k.cap.quaternion.set(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w);
        _v.copy(k.center).applyQuaternion(k.cap.quaternion);
        k.cap.position.set(b.position.x / S - _v.x, b.position.y / S - _v.y, b.position.z / S - _v.z);
      } else if (!k.popped) {
        k.cap.position.y = y;
        k.cap.rotation.set(k.rx, 0, k.rz);
      }
    }
    for (let i = tweens.length - 1; i >= 0; i--) {
      const tw = tweens[i];
      tw.t += dt;
      if (tw.t < 0) continue;
      const u = Math.min(1, tw.t / tw.dur);
      tw.update(u);
      if (u >= 1) { tw.done(); tweens.splice(i, 1); }
    }
    knob.rotation.y += (knobAngle - knob.rotation.y) * Math.min(1, dt * 22);
  }
  controls.update();
  renderer.render(scene, camera);
}
frame();

// 调试/自动化用
window.__kb = { world, keys, keyList, press, release, pop, explodeAll, restoreAll, sound, camera, controls };
