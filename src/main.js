import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import * as CANNON from 'cannon-es';
import { KeySound, PROFILE_LIST } from './sound.js';

// 暖米色摄影棚是这把键盘的固定布景，不跟随系统深浅色
document.documentElement.dataset.theme = 'light';
const BACKDROP = 0xd8ccb8;

// ---------------------------------------------------------------- 场景
const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = 1.0;

const scene = new THREE.Scene();
scene.background = new THREE.Color(BACKDROP);

// 自己搭一个影棚当环境贴图：暖色墙面 + 顶部大柔光箱 + 后方条形灯 + 侧面补光
function studioEnv() {
  const s = new THREE.Scene();
  const lit = (v, tint = [1, 1, 1]) => new THREE.MeshBasicMaterial({ color: new THREE.Color(v * tint[0], v * tint[1], v * tint[2]), side: THREE.DoubleSide });
  // 穹顶：朝主光方向亮、背光方向暗的渐变，金属面上才有明暗过渡
  const g = new THREE.SphereGeometry(8, 48, 32);
  const keyDir = new THREE.Vector3(-0.45, 0.8, -0.4).normalize(), n = new THREE.Vector3();
  const col = new Float32Array(g.attributes.position.count * 3);
  for (let i = 0; i < g.attributes.position.count; i++) {
    n.fromBufferAttribute(g.attributes.position, i).normalize();
    const d = n.dot(keyDir) * 0.5 + 0.5;
    const v = 0.22 + 1.5 * d * d * d + (n.y < 0 ? -0.1 : 0);
    col.set([v, v * 0.93, v * 0.82], i * 3);
  }
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  s.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
  const panel = (w, h, pos, v, tint) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), lit(v, tint));
    m.position.set(...pos);
    m.lookAt(0, 0, 0);
    s.add(m);
  };
  panel(3.2, 3.2, [-1.8, 3.2, -1.6], 9, [1, 0.95, 0.88]);     // 主光柔光箱（左后上方）
  panel(6, 0.6, [1.0, 1.0, -4.6], 11, [1, 0.93, 0.84]);       // 轮廓条灯（后方）
  panel(3, 2.2, [4.6, 1.4, 2.2], 2.6, [0.93, 0.95, 1]);       // 冷色补光（右前）
  panel(5, 0.7, [-0.8, 0.8, 4.6], 4, [1, 0.96, 0.92]);        // 正面低位条灯
  panel(1.2, 5, [2.6, 3.4, 0.4], 5, [1, 0.97, 0.93]);         // 顶部条灯：给定位板一道高光
  return s;
}
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(studioEnv(), 0.02).texture;
scene.environmentIntensity = 1.0;

const camera = new THREE.PerspectiveCamera(30, 1, 0.02, 20);
const controls = new OrbitControls(camera, canvas);
const TARGET = new THREE.Vector3(0, 0.012, 0.0);
controls.target.copy(TARGET);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.14;
controls.maxDistance = 1.8;
controls.maxPolarAngle = Math.PI * 0.485;
controls.enablePan = false;

const sun = new THREE.DirectionalLight(0xfff1e0, 2.6);
sun.position.set(-0.55, 0.95, -0.5);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
Object.assign(sun.shadow.camera, { left: -0.6, right: 0.6, top: 0.6, bottom: -0.6, near: 0.2, far: 3 });
sun.shadow.bias = -0.00012;
sun.shadow.normalBias = 0.0005;
sun.shadow.radius = 5;
scene.add(sun);
const fill = new THREE.DirectionalLight(0xe6edff, 0.45);
fill.position.set(0.75, 0.45, 0.55);
scene.add(fill);

const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ color: 0x3b2a17, opacity: 0.34 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// 后期：景深 + 色调映射。合成目标带 4x MSAA。
const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, samples: 4 }));
composer.addPass(new RenderPass(scene, camera));
// 环境光遮蔽：键帽之间、轴体和定位板的接触处压暗。半径按真实尺寸给（米）。
const gtao = new GTAOPass(scene, camera, 4, 4, undefined, { radius: 0.012, distanceExponent: 1.4, thickness: 1.5, scale: 1.35, samples: 16, screenSpaceRadius: false });
gtao.blendIntensity = 1.0;
composer.addPass(gtao);
const bokeh = new BokehPass(scene, camera, { focus: 0.5, aperture: 0.02, maxblur: 0.006 });
composer.addPass(bokeh);
composer.addPass(new OutputPass());
const dof = { focus: 0.5, aperture: 0.02, maxblur: 0.006 };

const DEFAULT_DIR = new THREE.Vector3(-0.30, 0.56, 0.78).normalize();
function fitDistance() {
  const aspect = window.innerWidth / window.innerHeight;
  const vfov = THREE.MathUtils.degToRad(30);   // 默认视角固定 30°，装配镜头用的是长焦
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
  return Math.max(0.21 / Math.tan(hfov / 2), 0.13 / Math.tan(vfov / 2)) * 1.2;
}
let camReady = false;
function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  if (!w || !h) return;                 // 窗口还没布局好（比如后台标签页）
  renderer.setSize(w, h, false);
  composer.setPixelRatio(renderer.getPixelRatio());
  composer.setSize(w, h);
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

// 按材质名字重调质感（Blender 导出的参数是给 Cycles 用的）
const LOOK = {
  Keycap_Alpha: { hex: '#e9e2d2', roughness: 0.46, envMapIntensity: 0.75 },
  Keycap_Mod: { hex: '#2f4875', roughness: 0.42, envMapIntensity: 0.9 },
  Keycap_Accent: { hex: '#e98468', roughness: 0.42, envMapIntensity: 0.85 },
  Legend_Dark: { hex: '#35507f', roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 },
  Legend_Light: { hex: '#efeadf', roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 },
  Case_Aluminum: { hex: '#273b66', roughness: 0.36, metalness: 0.85, envMapIntensity: 1.1 },
  Plate: { hex: '#efca8e', roughness: 0.32, metalness: 0.72, envMapIntensity: 1.2 },
  PCB: { hex: '#232426', roughness: 0.4 },
  PCB_Pad: { hex: '#f0c070', roughness: 0.3, metalness: 1, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 },
  PCB_Silk: { polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 },
  PCB_Hole: { polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 },
  Switch_Top: { hex: '#ffffff', transmission: 0.9, thickness: 0.004, ior: 1.49, roughness: 0.1, envMapIntensity: 2.0 },
  Switch_Bottom: { hex: '#e8e2d8', transmission: 0.9, thickness: 0.006, ior: 1.49, roughness: 0.1, envMapIntensity: 1.8 },
  Switch_Stem: { hex: '#eea08c', roughness: 0.4 },
  Switch_Spring: { hex: '#f3c77c', roughness: 0.25, metalness: 1 },
  Stabilizer: { hex: '#3a3b40', roughness: 0.45 },
  Knob: { hex: '#f0c283', roughness: 0.24, metalness: 1, envMapIntensity: 1.25 },
  Knob_Mark: { hex: '#2f4875' },
  Encoder: { roughness: 0.28, metalness: 1 },
};
let plate, plateRestY = 0, knobRestY = 0;

new GLTFLoader().load(import.meta.env.BASE_URL + 'models/keyboard.glb', (gltf) => {
  scene.add(gltf.scene);
  root = gltf.scene.getObjectByName('Keyboard');
  knob = root.getObjectByName('Knob');
  plate = root.getObjectByName('Plate');
  plateRestY = plate.position.y;
  knobRestY = knob.position.y;
  rootBaseY = root.position.y;
  gltf.scene.updateMatrixWorld(true);
  root.getWorldQuaternion(rootQ);
  upW.set(0, 1, 0).applyQuaternion(rootQ);

  const seen = new Set();
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const m = o.material;
    const glass = m.name.startsWith('Switch_Top') || m.name.startsWith('Switch_Bottom');
    o.castShadow = !glass && !m.name.startsWith('Legend') && !m.name.startsWith('PCB_');
    o.receiveShadow = !glass;
    if (seen.has(m)) return;
    seen.add(m);
    const { hex, ...look } = LOOK[m.name] || {};
    Object.assign(m, look);
    if (hex) m.color.set(hex);
    m.needsUpdate = true;
  });

  // 外壳 + 旋钮的静态碰撞体
  world.addBody(addStatic(new THREE.Vector3(0, 0.008 - 0.02, 0), new THREE.Vector3(0.1633, 0.02, 0.0704)));
  world.addBody(addStatic(new THREE.Vector3(knob.position.x, 0.011, knob.position.z), new THREE.Vector3(0.009, 0.009, 0.009)));

  for (const cap of root.children.slice()) {
    if (!cap.name.startsWith('Key_')) continue;
    const code = cap.userData.code || cap.name.slice(4);
    const w = cap.userData.w || 1;
    const sw = root.getObjectByName('Switch_' + code);
    const stem = sw.getObjectByName('Stem_' + code);
    const spring = sw.getObjectByName('Spring_' + code);
    const stabStem = plate.getObjectByName('StabStem_' + code) || null;
    cap.geometry.computeBoundingBox();
    const bb = cap.geometry.boundingBox;
    const half = bb.getSize(new THREE.Vector3()).multiplyScalar(0.5);
    const center = bb.getCenter(new THREE.Vector3());
    const rest = cap.position.clone();
    const k = {
      code, cap, stem, spring, stabStem, sw, swRestY: sw.position.y, rest, w, half, center,
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
  pickables.push(knob, ...knob.children);
  document.getElementById('loading').classList.add('hide');
  buildAssembly();
  startAssembly();
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

// ---------------------------------------------------------------- 装配动画
// 时间单位是“帧”（30 帧/秒），和 Blender 里渲染成片用的时间线一致。
const asm = { on: false, f: 0, rate: 1, end: 470, events: [], ei: 0, plate: null, knob: null, shot: null };
const bv = (x, y, z) => new THREE.Vector3(x, z, -y);       // Blender 坐标(Z 朝上) -> three
const skipEl = document.getElementById('skip');

function dropPose(f, d) {
  const f0 = d.land - d.dur;
  if (f < f0) return null;                                   // 还没出场
  if (f <= d.land) { const u = (f - f0) / d.dur; return { z: d.off + d.h * (1 - u * u), t: 1 - u }; }
  let pf = 0, pz = d.off;
  for (const [df, dz] of d.after) {
    if (f <= d.land + df) return { z: pz + (dz - pz) * ((f - d.land - pf) / (df - pf)), t: 0 };
    pf = df; pz = dz;
  }
  return { z: 0, t: 0, done: true };
}
function applyDrop(o, restY, f, d) {
  const p = dropPose(f, d);
  o.visible = !!p;
  if (!p) return false;
  o.position.y = restY + p.z * 0.001;
  o.rotation.set(d.tilt[0] * p.t, d.tilt[2] * p.t, -d.tilt[1] * p.t);
  return !!p.done;
}

function buildAssembly() {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const span = (a, b) => a + (b - a) * rnd();
  const ev = [];
  asm.plate = { land: 50, dur: 14, h: 260, off: 0, after: [[3, 1.6], [6, 0]], tilt: [0.02, -0.015, 0] };
  ev.push([50, () => sound.clack(0.8, 0, 0.55)]);
  asm.knob = { land: 402, dur: 11, h: 200, off: 1.5, after: [[3, 1.5], [5, 0]], tilt: [0, 0, 0] };
  ev.push([407, () => sound.clack(0.5, 0.8, 0.8)]);
  for (let i = 0; i < 12; i++) ev.push([412 + i * i * 0.28, () => sound.tick()]);

  // 轴体：特写里先落几颗，然后整片下雨
  const first = { KeyX: 96, KeyS: 112, KeyC: 122, KeyD: 128, KeyZ: 132 };
  const rest = keyList.filter((k) => !(k.code in first))
    .map((k) => [k, k.rest.x * 550 + k.rest.z * 300 + span(-60, 60)]).sort((a, b) => a[1] - b[1]);
  rest.forEach(([k], i) => { first[k.code] = 146 + Math.round((96 * i) / (rest.length - 1)); });
  // 键帽：从后排往前排铺
  const order = keyList.slice().sort((a, b) => (a.rest.z - b.rest.z) || (a.rest.x - b.rest.x));
  order.forEach((k, i) => {
    k.asmSw = { land: first[k.code], dur: 10, h: 230, off: 2.4, after: [[3, 2.4], [5, 0]], tilt: [span(-0.3, 0.3), span(-0.3, 0.3), span(-0.5, 0.5)] };
    k.asmCap = { land: 272 + Math.round((92 * i) / (order.length - 1)) + Math.round(span(-2, 2)), dur: 10, h: 240, off: 2.6,
      after: [[2, 2.6], [4, -2.2], [7, 0.25], [9, 0]], tilt: [span(-0.5, 0.5), span(-0.5, 0.5), span(-0.6, 0.6)] };
    ev.push([k.asmSw.land + 5, () => sound.clack(0.22, k.pan, 1.5 + Math.random() * 0.3)]);
    ev.push([k.asmCap.land + 4, () => sound.down({ pan: k.pan, big: k.big, space: k.space })]);
    k.capDone = true;
  });
  // 收尾：一圈敲击波纹
  for (const k of keyList) {
    const d = Math.hypot(k.rest.x - 0.02, k.rest.z - 0.005) * 1000;
    ev.push([440 + d * 0.16, () => { press(k, 'asm'); setTimeout(() => release(k, 'asm'), 70); }]);
  }
  asm.events = ev.sort((a, b) => a[0] - b[0]);

  const K = (code, z = 0) => root.localToWorld(keys[code].rest.clone().setY(z * 0.001));
  const knobW = root.localToWorld(new THREE.Vector3(knob.position.x, 0.012, knob.position.z));
  // [起始帧, 结束帧, 相机起止, 注视点起止, 焦段, 景深强度, 对焦点]
  asm.shots = [
    [1, 80, bv(-0.36, -0.40, 0.42), bv(-0.31, -0.35, 0.36), bv(0, 0, 0), bv(0, 0, 0), 50, 0.02, bv(-0.05, -0.03, 0.01)],
    [81, 138, bv(-0.250, -0.175, 0.085), bv(-0.235, -0.180, 0.078), K('KeyD', 3), K('KeyD', 3), 85, 0.22, K('KeyX', 4)],
    [139, 258, bv(-0.29, -0.30, 0.27), bv(-0.24, -0.31, 0.24), bv(-0.02, -0.005, 0.01), bv(-0.015, -0.005, 0.012), 62, 0.04, bv(-0.06, -0.04, 0.02)],
    [259, 380, bv(-0.27, -0.27, 0.15), bv(-0.21, -0.28, 0.16), bv(-0.03, 0, 0.02), bv(-0.02, 0, 0.02), 65, 0.07, bv(-0.06, -0.03, 0.03)],
    [381, 438, bv(0.020, -0.085, 0.105), bv(0.040, -0.077, 0.097), knobW.clone().add(bv(-0.028, -0.014, -0.004)), knobW.clone().add(bv(-0.024, -0.012, -0.004)), 95, 0.2, knobW],
  ];
}

function startAssembly() {
  if (!root) return;
  explodeTimers.forEach(clearTimeout);
  explodeTimers = [];
  tweens.length = 0;
  for (const k of keyList) {            // 飞出去的键帽先归位
    if (k.body) { world.removeBody(k.body); k.body = null; }
    if (k.popped) { root.attach(k.cap); world.addBody(k.staticCap); }
    k.popped = k.restoring = false;
    k.cap.position.copy(k.rest);
    k.cap.quaternion.identity();
    k.holders.clear();
    k.held = false; k.x = k.v = 0; k.trx = k.trz = 0;
    k.capDone = false;
  }
  asm.on = true; asm.f = 0; asm.ei = 0; asm.shot = null; asm.flown = false;
  controls.enabled = false;
  document.body.classList.add('cinema');
}

function poseAssembly(f) {
  applyDrop(plate, plateRestY, f, asm.plate);
  applyDrop(knob, knobRestY, f, asm.knob);
  if (f > 410) knobAngle = knobBase - 2.6 * (1 - Math.pow(1 - Math.min(1, (f - 410) / 45), 3));
  for (const k of keyList) {
    applyDrop(k.sw, k.swRestY, f, k.asmSw);
    if (!k.capDone) {
      k.capDone = applyDrop(k.cap, k.rest.y, f, k.asmCap);
      if (k.capDone) k.cap.rotation.set(0, 0, 0);
    }
  }
}

const _cp = new THREE.Vector3(), _ct = new THREE.Vector3();
function shotCamera(f) {
  const s = asm.shots.find((q) => f <= q[1]) || asm.shots[asm.shots.length - 1];
  const u = THREE.MathUtils.clamp((f - s[0]) / (s[1] - s[0]), 0, 1);
  const e = 0.5 * u + 0.5 * u * (2 - u);
  camera.position.lerpVectors(s[2], s[3], e);
  _ct.lerpVectors(s[4], s[5], e);
  camera.lookAt(_ct);
  // 和 Blender 一样按 36mm 画幅的长边换算视角
  const sensorV = camera.aspect >= 1 ? 36 / camera.aspect : 36;
  camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(sensorV / 2 / s[6]));
  camera.updateProjectionMatrix();
  dof.focus = camera.position.distanceTo(s[8]);
  dof.aperture = s[7];
  dof.maxblur = 0.01;
  asm.shot = s;
}

let knobBase = 0;
function flyOut(dur) {                  // 从当前机位飞到可交互的默认视角
  if (asm.flown) return;
  asm.flown = true;
  document.body.classList.remove('cinema');
  const p0 = camera.position.clone(), p1 = TARGET.clone().addScaledVector(DEFAULT_DIR, fitDistance());
  const t0 = _ct.clone(), fov0 = camera.fov, d0 = { ...dof };
  tweens.push({
    t: 0, dur,
    update(u) {
      const e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      camera.position.lerpVectors(p0, p1, e);
      camera.lookAt(_cp.lerpVectors(t0, TARGET, e));
      camera.fov = fov0 + (30 - fov0) * e;
      camera.updateProjectionMatrix();
      dof.focus = camera.position.distanceTo(_cp);
      dof.aperture = d0.aperture + (0.012 - d0.aperture) * e;
    },
    done() { controls.target.copy(TARGET); controls.enabled = true; },
  });
}
function endAssembly() {
  asm.on = false;
  poseAssembly(1e9);
  for (const k of keyList) { k.capDone = true; k.cap.visible = true; k.cap.rotation.set(0, 0, 0); release(k, 'asm'); }
  knobBase = knobAngle;
}
function finishAssembly() {             // 用户跳过：直接装好
  if (!asm.on) return;
  for (const k of keyList) k.cap.position.copy(k.rest);
  endAssembly();
  flyOut(0.9);
}

function stepAssembly(dt) {
  const f0 = asm.f;
  asm.f = Math.min(asm.end, asm.f + dt * 30 * asm.rate);
  poseAssembly(asm.f);
  while (asm.ei < asm.events.length && asm.events[asm.ei][0] <= asm.f) {
    if (asm.events[asm.ei][0] > f0 - 2) asm.events[asm.ei][1]();
    asm.ei++;
  }
  if (asm.f <= 438) shotCamera(asm.f);
  else flyOut(1.7);                     // 最后一镜直接飞到默认视角，同时放敲击波纹
  if (asm.f >= asm.end) endAssembly();
}

// ---------------------------------------------------------------- 输入：实体键盘
const typedEl = document.getElementById('typedText');
let typed = '';
function showTyped() { typedEl.textContent = typed.slice(-42); }

window.addEventListener('keydown', (e) => {
  if (asm.on) { if (!e.ctrlKey && !e.metaKey && !/^F\d/.test(e.code)) { e.preventDefault(); finishAssembly(); } return; }
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
  if (asm.on) { finishAssembly(); return; }
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
  const hitObj = pick(e)?.object;
  if (asm.on || !hitObj || (hitObj !== knob && hitObj.parent !== knob)) return;
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
if (skipEl) skipEl.onclick = () => { sound.ensure(); finishAssembly(); };
const pullBtn = document.getElementById('pullMode');
pullBtn.onclick = () => { pullMode = !pullMode; pullBtn.classList.toggle('active', pullMode); pullBtn.blur(); };
document.getElementById('explode').onclick = (e) => { if (!asm.on) explodeAll(); e.currentTarget.blur(); };
document.getElementById('replay').onclick = (e) => { sound.ensure(); startAssembly(); e.currentTarget.blur(); };
document.getElementById('restore').onclick = (e) => { if (!asm.on) restoreAll(); e.currentTarget.blur(); };
document.getElementById('resetView').onclick = (e) => {
  if (asm.on) return;
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
    if (asm.on) stepAssembly(dt);
    for (const k of keyList) {
      const y = k.rest.y - k.x * 0.001;
      k.stem.position.y = -k.x * 0.001;
      k.spring.scale.y = 1 - k.x / 6.6;
      if (k.stabStem) k.stabStem.position.y = -k.x * 0.001;
      if (k.body) {
        const b = k.body;
        k.cap.quaternion.set(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w);
        _v.copy(k.center).applyQuaternion(k.cap.quaternion);
        k.cap.position.set(b.position.x / S - _v.x, b.position.y / S - _v.y, b.position.z / S - _v.z);
      } else if (!k.popped && k.capDone) {
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
  if (controls.enabled) {
    controls.update();
    // 可交互时：对焦在注视点上，离得越近景深越浅
    const d = camera.position.distanceTo(controls.target);
    dof.focus = d;
    dof.aperture = THREE.MathUtils.clamp(0.03 / d - 0.035, 0.008, 0.2);
    dof.maxblur = 0.008;
  }
  const bu = bokeh.uniforms, kf = Math.min(1, dt * 8);
  bu.focus.value += (dof.focus - bu.focus.value) * (asm.on ? 1 : kf);
  bu.aperture.value += (dof.aperture - bu.aperture.value) * (asm.on ? 1 : kf);
  bu.maxblur.value = dof.maxblur;
  composer.render();
}
frame();

// 调试/自动化用
window.__kb = { gtao, sun, scene, world, keys, keyList, press, release, pop, explodeAll, restoreAll, sound, camera, controls, asm, dof, bokeh, startAssembly, finishAssembly, renderer };
