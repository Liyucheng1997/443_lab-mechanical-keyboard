// 机械键盘音效：全部用程序合成（模态共振 + 带通噪声脉冲），没有任何录音素材。
// 一次按键 = 触底声（冲击噪声 + 外壳/定位板/键帽的几个衰减共振）+ 回弹声（轴心撞上盖）。

function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 图层：['m', 频率, 衰减时间, 增益]  共振模态
//       ['n', 中心频率, Q, 衰减时间, 增益, 延迟?]  带通噪声脉冲
function render(sr, dur, layers, rnd, jitter = 0.035) {
  const n = Math.floor(sr * dur);
  const out = new Float32Array(n);
  for (const L of layers) {
    if (L[0] === 'm') {
      const f = L[1] * (1 + (rnd() - 0.5) * 2 * jitter);
      const tau = L[2] * (0.85 + rnd() * 0.3);
      const g = L[3] * (0.8 + rnd() * 0.4);
      const ph = rnd() * 0.6;
      const w = (2 * Math.PI * f) / sr;
      for (let i = 0; i < n; i++) {
        const t = i / sr;
        out[i] += g * Math.exp(-t / tau) * Math.sin(w * i + ph) * Math.min(1, i / 6);
      }
    } else {
      const f = L[1] * (1 + (rnd() - 0.5) * 2 * jitter);
      const q = L[2], tau = L[3], g = L[4] * (0.8 + rnd() * 0.4);
      const n0 = Math.floor((L[5] || 0) * sr);
      const w0 = (2 * Math.PI * f) / sr;
      const alpha = Math.sin(w0) / (2 * q);
      const a0 = 1 + alpha;
      const b0 = alpha / a0, b2 = -alpha / a0, a1 = (-2 * Math.cos(w0)) / a0, a2 = (1 - alpha) / a0;
      let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
      for (let i = n0; i < n; i++) {
        const t = (i - n0) / sr;
        const x = (rnd() * 2 - 1) * Math.exp(-t / tau);
        const y = b0 * x + b2 * x2 - a1 * y1 - a2 * y2;
        x2 = x1; x1 = x; y2 = y1; y1 = y;
        out[i] += g * y * 3;
      }
    }
  }
  let peak = 1e-6;
  for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(out[i]));
  const fade = Math.floor(sr * 0.004);
  for (let i = 0; i < n; i++) {
    out[i] = (out[i] / peak) * 0.9 * Math.min(1, (n - i) / fade);
  }
  return out;
}

const PROFILES = {
  thock: {
    label: '线性 Thock',
    down: [['n', 3100, 0.9, 0.0022, 0.42], ['n', 850, 1.1, 0.009, 0.5],
      ['m', 172, 0.034, 0.55], ['m', 296, 0.030, 0.45], ['m', 505, 0.018, 0.26],
      ['m', 1120, 0.008, 0.11], ['m', 2550, 0.004, 0.05]],
    up: [['n', 4100, 1.0, 0.0018, 0.32], ['n', 1350, 1.0, 0.005, 0.28],
      ['m', 410, 0.016, 0.20], ['m', 860, 0.010, 0.13], ['m', 1900, 0.005, 0.06]],
    downGain: 0.9, upGain: 0.42,
  },
  clack: {
    label: '段落 Clack',
    down: [['n', 4600, 0.8, 0.0028, 0.6], ['n', 1750, 1.0, 0.006, 0.5],
      ['m', 325, 0.022, 0.30], ['m', 640, 0.016, 0.32], ['m', 1340, 0.010, 0.24],
      ['m', 2900, 0.006, 0.15], ['m', 4150, 0.004, 0.08]],
    up: [['n', 5300, 1.0, 0.002, 0.4], ['n', 2100, 1.0, 0.004, 0.25],
      ['m', 700, 0.012, 0.16], ['m', 1620, 0.008, 0.15], ['m', 3300, 0.004, 0.08]],
    downGain: 0.8, upGain: 0.5,
  },
  click: {
    label: '青轴 Click',
    down: [['n', 4300, 0.8, 0.0026, 0.5], ['n', 1600, 1.0, 0.006, 0.45],
      ['m', 300, 0.022, 0.30], ['m', 610, 0.016, 0.28], ['m', 1280, 0.010, 0.2], ['m', 2800, 0.005, 0.12]],
    up: [['n', 5000, 1.0, 0.002, 0.36], ['m', 720, 0.012, 0.16], ['m', 1700, 0.007, 0.13]],
    click: [['n', 6400, 2.2, 0.0014, 0.6], ['m', 3750, 0.0034, 0.5], ['m', 5550, 0.0024, 0.34], ['m', 8100, 0.0015, 0.12]],
    downGain: 0.62, upGain: 0.4,
  },
};

const EXTRA = {
  stab: [['n', 2400, 2.0, 0.002, 0.35], ['n', 2900, 2.0, 0.002, 0.28, 0.009],
    ['m', 128, 0.045, 0.6], ['m', 215, 0.035, 0.35]],
  pop: [['n', 2500, 1.0, 0.004, 0.4], ['m', 470, 0.020, 0.6], ['m', 955, 0.012, 0.3], ['m', 1500, 0.006, 0.12]],
  clack: [['n', 3800, 1.0, 0.003, 0.5], ['m', 1700, 0.007, 0.4], ['m', 2900, 0.005, 0.3], ['m', 5200, 0.003, 0.14]],
  tick: [['n', 5200, 1.5, 0.001, 0.4], ['m', 2250, 0.003, 0.4]],
};

export const PROFILE_LIST = Object.entries(PROFILES).map(([id, p]) => ({ id, label: p.label }));

export class KeySound {
  constructor() {
    this.ctx = null;
    this.profile = 'thock';
    this.volume = 0.7;
    this.bank = {};
  }

  ensure() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = (this.ctx = new AC({ latencyHint: 'interactive' }));
    this.master = ctx.createGain();
    this.master.gain.value = this.volume;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -10; comp.ratio.value = 4; comp.attack.value = 0.002; comp.release.value = 0.08;
    this.master.connect(comp).connect(ctx.destination);
    // 很短的房间混响，让声音“落在桌面上”而不是贴在耳朵上
    const sr = ctx.sampleRate, len = Math.floor(sr * 0.24);
    const ir = ctx.createBuffer(2, len, sr);
    const rnd = mulberry32(7);
    for (let c = 0; c < 2; c++) {
      const d = ir.getChannelData(c);
      let lp = 0;
      for (let i = 0; i < len; i++) {
        lp += ((rnd() * 2 - 1) - lp) * 0.45;
        d[i] = lp * Math.exp(-i / sr / 0.045) * (i < 40 ? i / 40 : 1);
      }
    }
    this.reverb = ctx.createConvolver();
    this.reverb.buffer = ir;
    const wet = ctx.createGain();
    wet.gain.value = 0.2;
    this.reverb.connect(wet).connect(this.master);
    const mk = (layers, count, dur, seed) => {
      const arr = [];
      for (let i = 0; i < count; i++) {
        const data = render(sr, dur, layers, mulberry32(seed + i * 101));
        const b = ctx.createBuffer(1, data.length, sr);
        b.copyToChannel(data, 0);
        arr.push(b);
      }
      return arr;
    };
    let seed = 11;
    for (const [id, p] of Object.entries(PROFILES)) {
      this.bank[id] = { down: mk(p.down, 7, 0.14, seed += 1000), up: mk(p.up, 7, 0.09, seed += 1000) };
      if (p.click) this.bank[id].click = mk(p.click, 5, 0.03, seed += 1000);
    }
    for (const [id, layers] of Object.entries(EXTRA)) this.bank[id] = mk(layers, 5, id === 'stab' ? 0.16 : 0.1, seed += 1000);
  }

  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.master) this.master.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.02);
  }

  _play(buffers, { gain = 1, rate = 1, pan = 0, delay = 0 } = {}) {
    if (!this.ctx || !buffers) return;
    const ctx = this.ctx;
    const src = ctx.createBufferSource();
    src.buffer = buffers[(Math.random() * buffers.length) | 0];
    src.playbackRate.value = rate * (0.97 + Math.random() * 0.06);
    const g = ctx.createGain();
    g.gain.value = gain * (0.85 + Math.random() * 0.3);
    const p = ctx.createStereoPanner();
    p.pan.value = Math.max(-1, Math.min(1, pan));
    src.connect(g).connect(p);
    p.connect(this.master);
    p.connect(this.reverb);
    src.start(ctx.currentTime + delay);
  }

  // big: 0 普通键，0~1 大键（越大越低沉），space 单独更空
  down({ pan = 0, big = 0, space = false, bare = false } = {}) {
    this.ensure();
    const P = PROFILES[this.profile], B = this.bank[this.profile];
    let rate = 1 - big * 0.16 - (space ? 0.12 : 0);
    let gain = P.downGain * (1 + big * 0.15);
    if (bare) { rate *= 1.3; gain *= 0.5; }      // 没有键帽：只有轴体的声音
    let delay = 0;
    if (B.click) { this._play(B.click, { gain: 0.55, pan, rate: 1 }); delay = 0.012; }
    this._play(B.down, { gain, rate, pan: pan * 0.6, delay });
    if ((big > 0.3 || space) && !bare) this._play(this.bank.stab, { gain: space ? 0.5 : 0.3, rate: space ? 0.85 : 1.05, pan: pan * 0.6, delay });
  }

  up({ pan = 0, big = 0, space = false, bare = false } = {}) {
    if (!this.ctx) return;
    const P = PROFILES[this.profile], B = this.bank[this.profile];
    let rate = 1 - big * 0.14 - (space ? 0.1 : 0);
    let gain = P.upGain;
    if (bare) { rate *= 1.25; gain *= 0.6; }
    if (B.click) this._play(B.click, { gain: 0.3, pan, rate: 1.06, delay: 0.004 });
    this._play(B.up, { gain, rate, pan: pan * 0.6, delay: 0.016 });
    if ((big > 0.3 || space) && !bare) this._play(this.bank.stab, { gain: 0.14, rate: 1.3, pan: pan * 0.6, delay: 0.016 });
  }

  pop(pan = 0) { this.ensure(); this._play(this.bank.pop, { gain: 0.7, pan: pan * 0.6 }); }
  clack(gain, pan = 0, rate = 1) { this._play(this.bank.clack, { gain, pan: pan * 0.6, rate }); }
  tick() { this.ensure(); this._play(this.bank.tick, { gain: 0.35, pan: 0.5 }); }
}
