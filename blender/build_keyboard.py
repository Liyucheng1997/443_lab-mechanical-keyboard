# -*- coding: utf-8 -*-
"""
程序化建模一把 75% 机械键盘（Blender 5.x）。

用法（在项目根目录）:
  blender -b -P blender/build_keyboard.py -- [--stills hero:690,switches:250] [--anim 1-690]
                                             [--samples 256] [--res 1080x1350] [--out renders]
                                             [--no-export] [--no-save] [--force]

产物:
  blender/keyboard.blend              完整场景（含 23 秒装配动画，7 个镜头）
  public/models/keyboard.glb          给网页用的模型
  renders/<name>.png                  --stills 指定的单帧（名字:帧号）
  renders/frames/0001.png …           --anim 指定的帧区间，已有的帧会跳过
"""
import bpy, bmesh, sys, os
from math import radians, sin, cos, tan, pi
from mathutils import Vector, Matrix

# ----------------------------------------------------------------------------
# 参数
# ----------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else True
    return default


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STILLS = [s for s in str(arg("--stills", "")).split(",") if s and s != "True"]
ANIM = arg("--anim", None)
SAMPLES = int(arg("--samples", 256))
RES = tuple(int(v) for v in str(arg("--res", "1080x1350")).split("x"))
OUT_DIR = os.path.join(ROOT, str(arg("--out", "renders")))
ANIM_DIR = os.path.join(OUT_DIR, "frames")
# 画面调子
VIEW, LOOK, EXPOSURE = "AgX", "AgX - Medium High Contrast", 0.0
WORLD_STRENGTH = 0.30
LIGHT_GAIN = 0.31
DO_EXPORT = not arg("--no-export", False)
DO_SAVE = not arg("--no-save", False)

MM = 0.001          # 建模用毫米，写入网格时换算成米
U = 19.05           # 1U 键距
TILT = 6.0          # 打字倾角（度）
TRAVEL = 4.0        # 键程
CAP_REST = 5.5      # 键帽底边静止时距定位板的高度
BEZ = 8.0           # 外壳上表面距定位板的高度
DF = 11.0           # 外壳前沿在定位板以下的厚度
KEYS_W = 16.25 * U
KEYS_H = 6.5 * U
PX, PY = KEYS_W / 2 + 1.0, KEYS_H / 2 + 1.0       # 键位凹槽半宽
OX, OY = PX + 7.5, PY + 7.5                       # 外壳半宽

# 每行键帽的 (高度, 顶面倾角)；倾角为正 = 后沿更高（类 Cherry 原厂高度的弧形）
PROFILES = {
    0: (9.6, 7.0),
    1: (9.3, 6.0),
    2: (8.0, 2.5),
    3: (7.3, -1.5),
    4: (7.7, -6.0),
    5: (7.7, -6.0),
}

# 线性色值
COL_ALPHA = (0.74, 0.67, 0.54)      # 奶白
COL_MOD = (0.030, 0.062, 0.155)      # 藏青
COL_ACCENT = (0.84, 0.22, 0.11)     # 珊瑚
COL_CASE = (0.022, 0.044, 0.110)     # 阳极氧化藏青
COL_GOLD = (1.0, 0.72, 0.38)

# ----------------------------------------------------------------------------
# 网格工具
# ----------------------------------------------------------------------------


def clamp(v, a, b):
    return max(a, min(b, v))


def lerp(a, b, t):
    return a + (b - a) * t


def rring(hx, hy, r, k=6, mx=6, my=6, ox=0.0, oy=0.0):
    """圆角矩形一圈点（逆时针）。点数 = 4(k+1) + 2(mx-1) + 2(my-1)。"""
    r = min(r, hx - 1e-4, hy - 1e-4)
    cs = [(hx - r, hy - r, 0), (-(hx - r), hy - r, 90), (-(hx - r), -(hy - r), 180), (hx - r, -(hy - r), 270)]
    segs = [mx, my, mx, my]  # 角 i 之后的直边：上、左、下、右
    pts = []
    for i, (cx, cy, a0) in enumerate(cs):
        for j in range(k + 1):
            a = radians(a0 + 90.0 * j / k)
            pts.append((cx + r * cos(a) + ox, cy + r * sin(a) + oy))
        ncx, ncy, na0 = cs[(i + 1) % 4]
        ex, ey = pts[-1]
        nx, ny = ncx + r * cos(radians(na0)) + ox, ncy + r * sin(radians(na0)) + oy
        m = segs[i]
        for j in range(1, m):
            t = j / m
            pts.append((lerp(ex, nx, t), lerp(ey, ny, t)))
    return pts


def circle(r, n, knurl=0.0):
    out = []
    for i in range(n):
        a = 2 * pi * i / n
        rr = r - (knurl if i % 2 else 0.0)
        out.append((rr * cos(a), rr * sin(a)))
    return out


class MB:
    """简易网格构建器（单位 mm）。"""

    def __init__(self):
        self.v = []
        self.f = []

    def ring(self, pts2, z):
        """pts2: [(x,y)]；z: 常数或 f(x,y)。"""
        i0 = len(self.v)
        for (x, y) in pts2:
            self.v.append((x, y, z(x, y) if callable(z) else z))
        return list(range(i0, i0 + len(pts2)))

    def bridge(self, a, b):
        n = len(a)
        for i in range(n):
            j = (i + 1) % n
            self.f.append((a[i], a[j], b[j], b[i]))

    def cap(self, a):
        self.f.append(tuple(a))

    def fan(self, a, p):
        c = len(self.v)
        self.v.append(p)
        n = len(a)
        for i in range(n):
            self.f.append((a[i], a[(i + 1) % n], c))

    def box(self, x0, x1, y0, y1, z0, z1):
        i = len(self.v)
        self.v += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for q in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
            self.f.append(tuple(i + t for t in q))

    def build(self, name, sharp_deg=40.0, smooth=True):
        me = bpy.data.meshes.new(name)
        me.from_pydata([Vector(p) * MM for p in self.v], [], self.f)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for f in bm.faces:
            f.smooth = smooth
        lim = radians(sharp_deg)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim:
                e.smooth = False
        bm.to_mesh(me)
        bm.free()
        me.update()
        return me


# ----------------------------------------------------------------------------
# 材质
# ----------------------------------------------------------------------------


def principled(name, color, rough=0.5, metal=0.0, bump=None, coat=0.0, emission=None,
               transmission=0.0, ior=None, sss=0.0):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if coat and "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
    if transmission and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if ior and "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = ior
    if sss and "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = sss
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.7, 0.5)
        bsdf.inputs["Subsurface Scale"].default_value = 0.0012
    if emission and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*emission[0], 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission[1]
    if bump:
        scale, strength = bump
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nz = nt.nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = scale
        nz.inputs["Detail"].default_value = 3.0
        bp = nt.nodes.new("ShaderNodeBump")
        bp.inputs["Strength"].default_value = strength
        bp.inputs["Distance"].default_value = 0.0001
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
        nt.links.new(nz.outputs[0], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    m.diffuse_color = (*color, 1.0)
    return m


def wood_material():
    m = principled("Desk", (0.12, 0.065, 0.03), rough=0.42)
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.2, 22.0, 1.0)
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 6.0
    nz.inputs["Detail"].default_value = 8.0
    nz.inputs["Roughness"].default_value = 0.65
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (0.045, 0.022, 0.010, 1)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.16, 0.085, 0.038, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], nz.inputs["Vector"])
    nt.links.new(nz.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], bsdf.inputs["Base Color"])
    return m


# ----------------------------------------------------------------------------
# 场景初始化
# ----------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
col_kb = bpy.data.collections.new("Keyboard")
col_env = bpy.data.collections.new("Studio")
scene.collection.children.link(col_kb)
scene.collection.children.link(col_env)


def add_obj(name, data, parent=None, loc=(0, 0, 0), col=None, mats=()):
    o = bpy.data.objects.new(name, data)
    (col or col_kb).objects.link(o)
    o.location = Vector(loc) * MM
    if parent:
        o.parent = parent
    for m in mats:
        o.data.materials.append(m)
    return o


M_ALPHA = principled("Keycap_Alpha", COL_ALPHA, rough=0.42, bump=(5200.0, 0.08), sss=0.22)
M_MOD = principled("Keycap_Mod", COL_MOD, rough=0.40, bump=(5200.0, 0.08))
M_ACCENT = principled("Keycap_Accent", COL_ACCENT, rough=0.40, bump=(5200.0, 0.08), sss=0.15)
M_LEG_DARK = principled("Legend_Dark", (0.035, 0.070, 0.17), rough=0.5)
M_LEG_LIGHT = principled("Legend_Light", (0.86, 0.83, 0.76), rough=0.5)
M_CASE = principled("Case_Aluminum", COL_CASE, rough=0.36, metal=1.0, bump=(9000.0, 0.03))
M_PLATE = principled("Plate", COL_GOLD, rough=0.30, metal=1.0, bump=(7000.0, 0.02))
M_PCB = principled("PCB", (0.016, 0.017, 0.019), rough=0.42, coat=0.4)
M_PAD = principled("PCB_Pad", (1.0, 0.70, 0.30), rough=0.32, metal=1.0)
M_SILK = principled("PCB_Silk", (0.78, 0.78, 0.76), rough=0.7)
M_HOLE = principled("PCB_Hole", (0.004, 0.004, 0.004), rough=0.9)
M_HOUSING_TOP = principled("Switch_Top", (1.0, 1.0, 1.0), rough=0.06, transmission=1.0, ior=1.49)
M_HOUSING_BOT = principled("Switch_Bottom", (0.82, 0.80, 0.77), rough=0.10, transmission=1.0, ior=1.49)
M_STEM = principled("Switch_Stem", (0.84, 0.30, 0.20), rough=0.38, sss=0.1)
M_SPRING = principled("Switch_Spring", (1.0, 0.74, 0.36), rough=0.25, metal=1.0)
M_STAB = principled("Stabilizer", (0.045, 0.047, 0.052), rough=0.42)
M_ENC = principled("Encoder", (0.70, 0.71, 0.73), rough=0.28, metal=1.0)
M_KNOB = principled("Knob", (1.0, 0.70, 0.34), rough=0.24, metal=1.0)
M_KNOB_MARK = principled("Knob_Mark", COL_MOD, rough=0.5)
M_FLOOR = principled("Backdrop", (0.72, 0.61, 0.46), rough=0.92)

KIND_MAT = {"a": M_ALPHA, "m": M_MOD, "x": M_ACCENT}
KIND_LEG = {"a": M_LEG_DARK, "m": M_LEG_LIGHT, "x": M_LEG_LIGHT}

# ----------------------------------------------------------------------------
# 键位布局（75% + 旋钮）
# ----------------------------------------------------------------------------


def build_layout():
    keys = []

    def row(y, prof, items):
        x = 0.0
        for it in items:
            if isinstance(it, (int, float)):
                x += it
                continue
            code, label, w, kind = it
            keys.append(dict(code=code, label=label, x=x, y=y, w=w, row=prof, kind=kind))
            x += w

    A, M, X = "a", "m", "x"
    row(0, 0, [("Escape", "esc", 1, X), .25,
               ("F1", "F1", 1, A), ("F2", "F2", 1, A), ("F3", "F3", 1, A), ("F4", "F4", 1, A), .25,
               ("F5", "F5", 1, M), ("F6", "F6", 1, M), ("F7", "F7", 1, M), ("F8", "F8", 1, M), .25,
               ("F9", "F9", 1, A), ("F10", "F10", 1, A), ("F11", "F11", 1, A), ("F12", "F12", 1, A), .25,
               ("Delete", "del", 1, M)])
    nums = [("Backquote", "`")] + [("Digit%d" % (i % 10), str(i % 10)) for i in range(1, 11)] + \
           [("Minus", "-"), ("Equal", "=")]
    row(1.25, 1, [(c, l, 1, A) for c, l in nums] + [("Backspace", "back", 2, M), .25, ("PageUp", "pg up", 1, M)])
    row(2.25, 2, [("Tab", "tab", 1.5, M)] + [("Key" + ch, ch, 1, A) for ch in "QWERTYUIOP"] +
        [("BracketLeft", "[", 1, A), ("BracketRight", "]", 1, A), ("Backslash", "\\", 1.5, A), .25,
         ("PageDown", "pg dn", 1, M)])
    row(3.25, 3, [("CapsLock", "caps", 1.75, M)] + [("Key" + ch, ch, 1, A) for ch in "ASDFGHJKL"] +
        [("Semicolon", ";", 1, A), ("Quote", "'", 1, A), ("Enter", "enter", 2.25, X), .25,
         ("Home", "home", 1, M)])
    row(4.25, 4, [("ShiftLeft", "shift", 2.25, M)] + [("Key" + ch, ch, 1, A) for ch in "ZXCVBNM"] +
        [("Comma", ",", 1, A), ("Period", ".", 1, A), ("Slash", "/", 1, A), ("ShiftRight", "shift", 1.75, M)])
    row(5.25, 5, [("ControlLeft", "ctrl", 1.25, M), ("MetaLeft", "win", 1.25, M), ("AltLeft", "alt", 1.25, M),
                  ("Space", "", 6.25, A), ("AltRight", "alt", 1, M), ("Fn", "fn", 1, M),
                  ("ControlRight", "ctrl", 1, M)])
    keys.append(dict(code="ArrowUp", label="sym:\u25B2", x=14.25, y=4.5, w=1, row=4, kind="m"))
    keys.append(dict(code="ArrowLeft", label="sym:\u25C0", x=13.25, y=5.5, w=1, row=5, kind="m"))
    keys.append(dict(code="ArrowDown", label="sym:\u25BC", x=14.25, y=5.5, w=1, row=5, kind="m"))
    keys.append(dict(code="ArrowRight", label="sym:\u25B6", x=15.25, y=5.5, w=1, row=5, kind="m"))
    for k in keys:
        k["cx"] = (k["x"] + k["w"] / 2) * U - KEYS_W / 2
        k["cy"] = KEYS_H / 2 - (k["y"] + 0.5) * U
    return keys


# ----------------------------------------------------------------------------
# 键帽
# ----------------------------------------------------------------------------
_cap_cache = {}


def make_cap(w, row, convex):
    key = (w, row, convex)
    if key in _cap_cache:
        return _cap_cache[key]
    h, tilt = PROFILES[row]
    tt = tan(radians(tilt))
    bx, by = (w * U - 0.9) / 2, (U - 0.9) / 2
    tx, ty = bx - 2.9, by - 2.3
    oy = 0.5                      # 顶面略向后偏
    rf, d = 0.6, 0.62             # 顶边圆角、碟形深度
    rb, rt = 0.9, 1.7
    k, my = 6, 6
    mx = max(6, int(round(6 * w)))

    def dish(x, y):
        if convex:
            yy = min(1.0, abs(y - oy) / ty)
            return -0.85 * yy * yy
        xe = (max(0.0, abs(x) - (tx - 6.3)) / 6.3) if tx > 6.3 else abs(x) / tx
        xe = min(1.0, xe)
        return -d * (1 - xe * xe)

    def ztop(x, y):
        xc, yc = clamp(x, -tx, tx), clamp(y, oy - ty, oy + ty)
        return h + (yc - oy) * tt + dish(xc, yc)

    mb = MB()
    rings = []
    # 侧壁
    for t in (0.0, 0.07, 0.5, 0.93, 1.0):
        pts = rring(lerp(bx, tx + rf, t), lerp(by, ty + rf, t), lerp(rb, rt + rf, t), k, mx, my, oy=oy * t)
        rings.append(mb.ring(pts, (lambda x, y, t=t: t * (ztop(x, y) - rf))))
    # 顶边圆角
    for phi in (30, 60, 90):
        c, s = cos(radians(phi)), sin(radians(phi))
        pts = rring(tx + rf * c, ty + rf * c, rt + rf * c, k, mx, my, oy=oy)
        rings.append(mb.ring(pts, (lambda x, y, s=s: ztop(x, y) - rf + rf * s)))
    # 顶面
    top = rring(tx, ty, rt, k, mx, my, oy=oy)
    for sc in (0.93, 0.7, 0.42, 0.16):
        pts = [(x * sc, oy + (y - oy) * sc) for (x, y) in top]
        rings.append(mb.ring(pts, ztop))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b)
    mb.fan(rings[-1], (0, oy, ztop(0, oy)))
    # 内腔
    wall = 1.25
    zc = h - abs(tt) * ty - (0.85 if convex else d) - 1.5
    tc = zc / h
    i0 = mb.ring(rring(bx - wall, by - wall, 0.5, k, mx, my), 0.0)
    i1 = mb.ring(rring(lerp(bx, tx + rf, tc) - wall, lerp(by, ty + rf, tc) - wall, 0.8, k, mx, my, oy=oy * tc), zc)
    mb.bridge(rings[0], i0)
    mb.bridge(i0, i1)
    mb.cap(i1)
    # 十字轴套
    posts = [0.0]
    if w >= 6:
        posts = [-50.0, 0.0, 50.0]
    elif w >= 2:
        posts = [-11.9, 0.0, 11.9]
    for px in posts:
        c0 = mb.ring([(x + px, y) for x, y in circle(2.75, 16)], zc + 0.3)
        c1 = mb.ring([(x + px, y) for x, y in circle(2.75, 16)], 1.3)
        mb.bridge(c0, c1)
        mb.cap(c0)
        mb.cap(c1)
    me = mb.build("Cap_%sU_R%d%s" % (str(w).replace(".", "_"), row, "_cvx" if convex else ""))
    _cap_cache[key] = (me, ztop, oy)
    return _cap_cache[key]


# ----------------------------------------------------------------------------
# 字符
# ----------------------------------------------------------------------------
def load_font(cands):
    for p in cands:
        if os.path.exists(p):
            try:
                return bpy.data.fonts.load(p)
            except Exception:
                pass
    return None


# 注意：可变字体（如 Bahnschrift）的轮廓互相重叠，Blender 填充会破面，所以用静态字体
FONT = load_font([r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\arialbd.ttf"])
FONT_SYM = load_font([r"C:\Windows\Fonts\seguisym.ttf", r"C:\Windows\Fonts\arial.ttf"])


def text_verts(body, font):
    """返回 (verts[mm], faces)，字号 1 单位 = 1 mm。"""
    cu = bpy.data.curves.new("tmp_text", 'FONT')
    cu.body = body
    if font:
        cu.font = font
    cu.size = 1.0
    cu.resolution_u = 4
    ob = bpy.data.objects.new("tmp_text", cu)
    col_env.objects.link(ob)
    me = bpy.data.meshes.new_from_object(ob)
    if len(me.vertices) == 0:
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    verts = [(v.co.x, v.co.y) for v in me.vertices]
    faces = [tuple(p.vertices) for p in me.polygons]
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    bpy.data.meshes.remove(me)
    return verts, faces


_hv, _ = text_verts("H", FONT)
H_HEIGHT = max(v[1] for v in _hv) - min(v[1] for v in _hv)


def make_legend(label, ztop, oy, w):
    if not label:
        return None
    sym = label.startswith("sym:")
    body = label[4:] if sym else label
    verts, faces = text_verts(body, FONT_SYM if sym else FONT)
    if not verts:
        return None
    xs, ys = [v[0] for v in verts], [v[1] for v in verts]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    bcx, bcy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    if sym:
        s = 3.3 / max(bw, bh)
        cy = bcy
    elif len(body) == 1 and body.isalnum():
        s = 4.3 / H_HEIGHT
        cy = H_HEIGHT / 2
    elif len(body) == 1:
        s = 4.3 / H_HEIGHT
        cy = bcy
    else:
        s = 2.55 / H_HEIGHT
        cy = H_HEIGHT / 2
    out = []
    for (x, y) in verts:
        X, Y = (x - bcx) * s, (y - cy) * s + oy
        out.append(Vector((X, Y, ztop(X, Y) + 0.02)) * MM)
    me = bpy.data.meshes.new("Legend_" + body)
    me.from_pydata(out, [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if sum(f.normal.z for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return me




# ----------------------------------------------------------------------------
# 轴体（MX 结构：下壳、透明上盖、轴心、弹簧）—— 坐标原点在定位板上表面的键位中心
# ----------------------------------------------------------------------------
def sw_ring(mb, hx, hy, r, z):
    return mb.ring(rring(hx, hy, r, 3, 2, 2), z)


def make_switch_bottom():
    mb = MB()
    rs = [sw_ring(mb, 6.9, 6.9, 0.5, -4.6), sw_ring(mb, 6.9, 6.9, 0.5, 0.0),
          sw_ring(mb, 7.8, 7.8, 0.6, 0.0), sw_ring(mb, 7.8, 7.8, 0.6, 0.9),
          sw_ring(mb, 7.2, 7.2, 0.8, 0.9), sw_ring(mb, 7.0, 7.0, 0.8, 2.4),
          sw_ring(mb, 6.2, 6.2, 0.5, 2.4), sw_ring(mb, 6.2, 6.2, 0.5, -3.8)]
    mb.cap(rs[0])
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.cap(rs[-1])
    return mb.build("SwitchBottom", sharp_deg=30)


def make_switch_top():
    mb = MB()
    rs = [sw_ring(mb, 7.0, 7.0, 0.8, 2.4), sw_ring(mb, 5.3, 5.6, 1.0, 6.0),
          sw_ring(mb, 3.5, 4.2, 0.3, 6.0), sw_ring(mb, 3.5, 4.2, 0.3, 5.2),
          sw_ring(mb, 4.6, 4.9, 0.8, 5.2), sw_ring(mb, 6.2, 6.2, 0.5, 2.4)]
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.bridge(rs[-1], rs[0])
    return mb.build("SwitchTop", sharp_deg=30)


def cross(mb, px, z0, z1):
    mb.box(px - 2.05, px + 2.05, -0.62, 0.62, z0, z1)
    mb.box(px - 0.62, px + 0.62, -2.05, 2.05, z0, z1)


def make_stem():
    mb = MB()
    mb.box(-3.2, 3.2, -3.9, 3.9, 2.8, 6.5)
    mb.box(-1.0, 1.0, -1.0, 1.0, -0.4, 2.8)
    cross(mb, 0.0, 6.5, 10.1)
    return mb.build("SwitchStem", smooth=False)


def make_spring(r=2.3, wire=0.27, h=6.6, turns=6, seg=14, sides=6):
    mb = MB()
    rings = []
    n = turns * seg
    for i in range(n + 1):
        a = 2 * pi * i / seg
        c = Vector((r * cos(a), r * sin(a), h * i / n))
        rad = Vector((cos(a), sin(a), 0))
        i0 = len(mb.v)
        for j in range(sides):
            b = 2 * pi * j / sides
            mb.v.append(tuple(c + rad * (wire * cos(b)) + Vector((0, 0, wire * sin(b)))))
        rings.append(list(range(i0, i0 + sides)))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b)
    mb.cap(rings[0])
    mb.cap(rings[-1])
    return mb.build("SwitchSpring", sharp_deg=80)


def stab_posts(w):
    if w >= 6:
        return [-50.0, 50.0]
    if w >= 2:
        return [-11.9, 11.9]
    return []


_stab_cache = {}


def make_stab(w):
    if w not in _stab_cache:
        hs, st = MB(), MB()
        for px in stab_posts(w):
            hs.box(px - 3.3, px + 3.3, -6.6, 5.4, -1.4, 4.6)
            hs.box(px - 4.2, px + 4.2, -5.0, 3.8, 0.0, 1.2)
            st.box(px - 2.6, px + 2.6, -2.9, 2.9, 3.0, 6.4)
            cross(st, px, 6.4, 10.1)
        _stab_cache[w] = (hs.build("StabHousing_%s" % w, smooth=False), st.build("StabStem_%s" % w, smooth=False))
    return _stab_cache[w]


# ----------------------------------------------------------------------------
# 外壳 / PCB / 定位板 / 编码器 / 旋钮
# ----------------------------------------------------------------------------
TT = tan(radians(TILT))
Z_PCB = -5.0        # PCB 上表面
Z_FLOOR = -6.6      # 外壳内腔底


def zbot(x, y):
    return -(DF + (OY + y) * TT)


def make_case():
    k, mx, my = 12, 24, 12
    RC, RF = 9.0, 1.6
    mb = MB()
    rs = []
    rs.append(mb.ring(rring(OX - 9, OY - 9, 3.0, k, mx, my), zbot))
    rs.append(mb.ring(rring(OX - 1.8, OY - 1.8, RC - 1.8, k, mx, my), zbot))
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), lambda x, y: zbot(x, y) + 1.8))
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), lambda x, y: zbot(x, y) + 2.4))
    # 上下盖之间的分缝
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), -3.9))
    rs.append(mb.ring(rring(OX - 0.55, OY - 0.55, RC - 0.55, k, mx, my), -3.55))
    rs.append(mb.ring(rring(OX - 0.55, OY - 0.55, RC - 0.55, k, mx, my), -2.85))
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), -2.5))
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), BEZ - RF - 0.5))
    for phi in (0, 22.5, 45, 67.5, 90):
        o = RF * (1 - cos(radians(phi)))
        rs.append(mb.ring(rring(OX - o, OY - o, RC - o, k, mx, my), BEZ - RF + RF * sin(radians(phi))))
    rs.append(mb.ring(rring(OX - RF - 0.5, OY - RF - 0.5, RC - RF - 0.5, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX + 1.1, PY + 1.1, 2.6, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX + 0.6, PY + 0.6, 2.1, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX, PY, 1.5, k, mx, my), BEZ - 0.6))
    rs.append(mb.ring(rring(PX, PY, 1.5, k, mx, my), Z_FLOOR))
    mb.cap(rs[0])
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.cap(rs[-1])
    return mb.build("Case", sharp_deg=32)


def flat_up(mb, name):
    me = mb.build(name, smooth=False)
    bm = bmesh.new()
    bm.from_mesh(me)
    flip = [f for f in bm.faces if f.normal.z < 0]
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)
    bm.to_mesh(me)
    bm.free()
    return me


def disc(mb, cx, cy, r, z, n=14):
    mb.cap(mb.ring([(x + cx, y + cy) for x, y in circle(r, n)], z))


def annulus(mb, cx, cy, r0, r1, z, n=18):
    a = mb.ring([(x + cx, y + cy) for x, y in circle(r1, n)], z)
    b = mb.ring([(x + cx, y + cy) for x, y in circle(r0, n)], z)
    mb.bridge(a, b)


def rect(mb, x0, x1, y0, y1, z):
    mb.cap(mb.ring([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z))


def make_pcb(layout):
    """返回 (板, 焊盘, 丝印, 孔) 四个网格，z 以 PCB 上表面为 0。"""
    board, pads, silk, holes = MB(), MB(), MB(), MB()
    a = board.ring(rring(PX - 0.25, PY - 0.25, 1.3, 4, 2, 2), Z_FLOOR - Z_PCB + 0.05)
    b = board.ring(rring(PX - 0.25, PY - 0.25, 1.3, 4, 2, 2), 0.0)
    board.cap(a)
    board.bridge(a, b)
    board.cap(b)
    zp, zs, zh = 0.04, 0.05, 0.07
    for k in layout:
        cx, cy = k["cx"], k["cy"]
        disc(holes, cx, cy, 2.0, zh, 18)
        annulus(pads, cx, cy, 2.0, 2.45, zp)
        for sx in (-5.08, 5.08):
            disc(holes, cx + sx, cy, 0.88, zh, 12)
        for (px, py) in ((-3.81, 2.54), (2.54, 5.08)):
            annulus(pads, cx + px, cy + py, 0.7, 1.55, zp)
            disc(holes, cx + px, cy + py, 0.72, zh, 12)
        # 热插拔座焊盘 + 二极管
        rect(pads, cx - 7.6, cx - 5.6, cy + 1.6, cy + 3.4, zp)
        rect(pads, cx + 4.6, cx + 6.6, cy + 4.2, cy + 6.0, zp)
        rect(silk, cx - 1.7, cx + 1.7, cy - 5.5, cy - 4.5, zs)
        rect(pads, cx - 2.6, cx - 1.9, cy - 5.5, cy - 4.5, zp)
        rect(pads, cx + 1.9, cx + 2.6, cy - 5.5, cy - 4.5, zp)
        # 键位角标
        L, T, E = 1.7, 0.22, 7.6
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0, y0 = cx + sx * E, cy + sy * E
                rect(silk, min(x0, x0 - sx * L), max(x0, x0 - sx * L), y0 - T / 2, y0 + T / 2, zs)
                rect(silk, x0 - T / 2, x0 + T / 2, min(y0, y0 - sy * L), max(y0, y0 - sy * L), zs)
        for px in stab_posts(k["w"]):
            disc(holes, cx + px, cy + 7.0, 1.55, zh, 14)
            disc(holes, cx + px, cy - 8.2, 2.0, zh, 14)
    # 丝印文字
    for (txt, tx, ty, size) in (("KB75  REV 2.0", -PX + 12.0, KEYS_H / 2 - 1.125 * U, 1.9),
                                ("HOT-SWAP  5-PIN", 20.0, KEYS_H / 2 - 1.125 * U, 1.9)):
        tv, tf = text_verts(txt, FONT)
        i0 = len(silk.v)
        s = size / H_HEIGHT
        silk.v += [(tx + x * s, ty + (y - H_HEIGHT / 2) * s, zs) for (x, y) in tv]
        silk.f += [tuple(i0 + i for i in f) for f in tf]
    return (board.build("PCB", sharp_deg=30), flat_up(pads, "PCB_Pads"),
            flat_up(silk, "PCB_Silk"), flat_up(holes, "PCB_Holes"))


KNOB_X, KNOB_Y = 15.75 * U - KEYS_W / 2, KEYS_H / 2 - 0.5 * U


def make_plate(layout):
    """带开孔的定位板：二维曲线填充 + 挤出 + 倒角。物体原点在板厚中心。"""
    cu = bpy.data.curves.new("PlateCurve", 'CURVE')
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'

    def poly(pts):
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for p, (x, y) in zip(sp.points, pts):
            p.co = (x * MM, y * MM, 0, 1)
        sp.use_cyclic_u = True

    poly(rring(PX - 0.35, PY - 0.35, 1.2, 4, 1, 1))
    for k in layout:
        poly(rring(7.0, 7.0, 0.45, 2, 1, 1, ox=k["cx"], oy=k["cy"]))
        for px in stab_posts(k["w"]):
            poly(rring(3.5, 6.2, 0.45, 2, 1, 1, ox=k["cx"] + px, oy=k["cy"] - 0.6))
    poly(rring(6.6, 6.6, 0.6, 2, 1, 1, ox=KNOB_X, oy=KNOB_Y))
    cu.extrude = 0.63 * MM
    cu.bevel_depth = 0.12 * MM
    cu.bevel_resolution = 1
    tmp = bpy.data.objects.new("PlateTmp", cu)
    col_kb.objects.link(tmp)
    bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    me.name = "Plate"
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    for p in me.polygons:
        p.use_smooth = False
    return me


def make_encoder():
    mb = MB()
    mb.box(-6.0, 6.0, -6.0, 6.0, Z_PCB, 3.2)
    prof = [(3.5, 3.2), (3.5, 5.6), (3.0, 5.6), (3.0, 12.0), (2.6, 12.4)]
    rs = [mb.ring(circle(r, 24), z) for (r, z) in prof]
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.fan(rs[-1], (0, 0, 12.4))
    return mb.build("Encoder", sharp_deg=30)


def make_knob():
    n = 120
    mb = MB()
    prof = [  # (r, z, knurl)
        (5.0, 0.6, 0), (8.9, 0.6, 0), (8.9, 1.6, 0), (8.6, 2.0, 0),
        (8.6, 2.4, 0.32), (8.6, 12.4, 0.32),
        (8.6, 12.8, 0), (8.9, 13.2, 0), (8.9, 14.2, 0), (8.2, 15.0, 0), (2.0, 15.0, 0),
    ]
    rs = [mb.ring(circle(r, n, kn), z) for (r, z, kn) in prof]
    mb.cap(rs[0])
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.fan(rs[-1], (0, 0, 15.0))
    mark = MB()
    mark.box(3.6, 7.4, -0.45, 0.45, 14.9, 15.06)
    return mb.build("Knob", sharp_deg=28), mark.build("KnobMark", smooth=False)


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------
th = radians(TILT)
root = bpy.data.objects.new("Keyboard", None)
col_kb.objects.link(root)
root.location = (0, 0, (DF * cos(th) + OY * sin(th)) * MM)
root.rotation_euler = (th, 0, 0)
ROOT_M = Matrix.Translation(root.location) @ Matrix.Rotation(th, 4, 'X')

layout = build_layout()
LAYOUT = {k["code"]: k for k in layout}

add_obj("Case", make_case(), root, mats=[M_CASE])
pcb_me, pads_me, silk_me, holes_me = make_pcb(layout)
pcb = add_obj("PCB", pcb_me, root, loc=(0, 0, Z_PCB), mats=[M_PCB])
add_obj("PCB_Pads", pads_me, pcb, mats=[M_PAD])
add_obj("PCB_Silk", silk_me, pcb, mats=[M_SILK])
add_obj("PCB_Holes", holes_me, pcb, mats=[M_HOLE])
add_obj("Encoder", make_encoder(), root, loc=(KNOB_X, KNOB_Y, 0), mats=[M_ENC])
plate = add_obj("Plate", make_plate(layout), root, loc=(0, 0, -0.75), mats=[M_PLATE])
knob_me, mark_me = make_knob()
knob = add_obj("Knob", knob_me, root, loc=(KNOB_X, KNOB_Y, 4.4), mats=[M_KNOB])
add_obj("KnobMark", mark_me, knob, mats=[M_KNOB_MARK])

bottom_me, top_me, stem_me, spring_me = make_switch_bottom(), make_switch_top(), make_stem(), make_spring()
bottom_me.materials.append(M_HOUSING_BOT)
top_me.materials.append(M_HOUSING_TOP)
stem_me.materials.append(M_STEM)
spring_me.materials.append(M_SPRING)

PARTS = {}   # code -> dict(switch, stem, cap, stab_stem)
for kdef in layout:
    code = kdef["code"]
    cap_me, ztop, oy = make_cap(kdef["w"], kdef["row"], code == "Space")
    sw = add_obj("Switch_" + code, bottom_me, root, loc=(kdef["cx"], kdef["cy"], 0))
    add_obj("SwTop_" + code, top_me, sw)
    add_obj("Spring_" + code, spring_me, sw, loc=(0, 0, -3.8))
    stem = add_obj("Stem_" + code, stem_me, sw)
    stab_stem = None
    if stab_posts(kdef["w"]):
        hs_me, st_me = make_stab(kdef["w"])
        stab = add_obj("Stab_" + code, hs_me, plate, loc=(kdef["cx"], kdef["cy"], 0.75), mats=[] if hs_me.materials else [M_STAB])
        stab_stem = add_obj("StabStem_" + code, st_me, stab, mats=[] if st_me.materials else [M_STAB])
    cap = add_obj("Key_" + code, cap_me, root, loc=(kdef["cx"], kdef["cy"], CAP_REST))
    cap["code"] = code
    cap["w"] = float(kdef["w"])
    cap["kind"] = kdef["kind"]
    # 键帽网格按 (宽度, 行) 共享，颜色放在对象槽位上
    if not cap_me.materials:
        cap_me.materials.append(None)
    cap.material_slots[0].link = 'OBJECT'
    cap.material_slots[0].material = KIND_MAT[kdef["kind"]]
    leg = make_legend(kdef["label"], ztop, oy, kdef["w"])
    if leg:
        add_obj("Legend_" + code, leg, cap, mats=[KIND_LEG[kdef["kind"]]])
    PARTS[code] = dict(switch=sw, stem=stem, cap=cap, stab_stem=stab_stem, cx=kdef["cx"], cy=kdef["cy"], row=kdef["y"], x=kdef["x"])

# ----------------------------------------------------------------------------
# 导出 GLB（静止的装配完成状态；网页里的动画由 JS 驱动）
# ----------------------------------------------------------------------------
bpy.context.view_layer.update()
if DO_EXPORT:
    out = os.path.join(ROOT, "public", "models", "keyboard.glb")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in col_kb.objects:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', use_selection=True, export_yup=True,
                              export_apply=False, export_extras=True, export_cameras=False,
                              export_lights=False, export_animations=False)
    print("[kb] exported", out, os.path.getsize(out) // 1024, "KB")


def glassify(m, shadow=0.8):
    """Cycles 默认不算焦散，玻璃会投下死黑的影子；让阴影光线大部分直接穿过去。"""
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    lp = nt.nodes.new("ShaderNodeLightPath")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = shadow
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Shadow Ray"], mul.inputs[0])
    nt.links.new(mul.outputs[0], mix.inputs[0])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


glassify(M_HOUSING_TOP)
glassify(M_HOUSING_BOT)

# ----------------------------------------------------------------------------
# 摄影棚：无缝背景、灯光
# ----------------------------------------------------------------------------
def make_cyc():
    mb = MB()
    prof = [(-4000.0, 0.0), (900.0, 0.0)]
    R = 600.0
    for i in range(1, 17):
        a = radians(90.0 * i / 16)
        prof.append((900.0 + R * sin(a), R * (1 - cos(a))))
    prof.append((900.0 + R, 4000.0))
    prev = None
    for (y, z) in prof:
        i = len(mb.v)
        mb.v += [(-5000.0, y, z), (5000.0, y, z)]
        if prev is not None:
            mb.f.append((prev, prev + 1, i + 1, i))
        prev = i
    return mb.build("Backdrop", sharp_deg=60)


add_obj("Backdrop", make_cyc(), None, col=col_env, mats=[M_FLOOR])

world = bpy.data.worlds.new("World")
scene.world = world
try:
    world.use_nodes = True
except Exception:
    pass
wnt = world.node_tree
wnt.nodes.clear()
w_out = wnt.nodes.new("ShaderNodeOutputWorld")
w_bg = wnt.nodes.new("ShaderNodeBackground")
wnt.links.new(w_bg.outputs[0], w_out.inputs[0])
w_bg.inputs[0].default_value = (1.0, 0.93, 0.84, 1.0)
w_bg.inputs[1].default_value = WORLD_STRENGTH


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return d.length


def area_light(name, loc, target, size, power, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.shape = 'RECTANGLE'
    ld.size, ld.size_y = size
    ld.energy = power
    ld.color = color
    o = bpy.data.objects.new(name, ld)
    col_env.objects.link(o)
    o.location = loc
    look_at(o, target)
    return o


area_light("Key", (-0.55, 0.50, 0.95), (0, 0, 0.0), (1.1, 1.1), 95 * LIGHT_GAIN, (1.0, 0.95, 0.88))
area_light("Fill", (0.75, -0.55, 0.45), (0, 0, 0.02), (0.9, 0.7), 16 * LIGHT_GAIN, (0.93, 0.95, 1.0))
area_light("Rim", (0.25, 0.80, 0.30), (0, 0.02, 0.03), (1.2, 0.18), 22 * LIGHT_GAIN, (1.0, 0.93, 0.84))
area_light("Front", (-0.15, -0.85, 0.30), (0, 0, 0.02), (1.0, 0.25), 9 * LIGHT_GAIN, (1.0, 0.96, 0.92))

# ----------------------------------------------------------------------------
# 装配动画
# ----------------------------------------------------------------------------
import random
from mathutils import Euler

FPS = 30
END = 690
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, END
try:
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
except Exception as e:
    print("[kb] interp pref:", e)


def fcurves_of(idb):
    ad = idb.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    try:
        return list(act.fcurves)
    except Exception:
        pass
    try:
        from bpy_extras import anim_utils
        cb = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        return list(cb.fcurves) if cb else []
    except Exception:
        return list(act.layers[0].strips[0].channelbag(ad.action_slot).fcurves)


def appear(o, f):
    o.scale = (0, 0, 0)
    o.keyframe_insert("scale", frame=f - 1)
    o.scale = (1, 1, 1)
    o.keyframe_insert("scale", frame=f)


def drop(o, f_land, height, dur, tilt=(0.0, 0.0, 0.0), land_off=0.0, after=()):
    """从 height(mm) 高处加速落下，f_land 帧着陆在 rest+land_off，之后按 after=[(帧偏移, z偏移mm)] 走。"""
    rest = o.location.copy()
    f0 = f_land - dur
    appear(o, f0)
    for i in range(dur + 1):
        u = i / dur
        o.location = rest + Vector((0, 0, (land_off + height * (1 - u * u)) * MM))
        o.rotation_euler = Euler([t * (1 - u) for t in tilt])
        o.keyframe_insert("location", frame=f0 + i)
        o.keyframe_insert("rotation_euler", frame=f0 + i)
    for df, dz in after:
        o.location = rest + Vector((0, 0, dz * MM))
        o.keyframe_insert("location", frame=f_land + df)
    o.location = rest
    o.rotation_euler = (0, 0, 0)


def press(code, f, depth=3.7):
    p = PARTS[code]
    for o in (p["cap"], p["stem"], p["stab_stem"]):
        if o is None:
            continue
        base = o.location.copy()
        for df, d in ((0, 0.0), (2, depth), (3, depth), (6, 0.0)):
            o.location = base - Vector((0, 0, d * MM))
            o.keyframe_insert("location", index=2, frame=f + df)
        o.location = base


rnd = random.Random(7)
F_PLATE = 50
drop(plate, F_PLATE, 260.0, 14, tilt=(0.02, -0.015, 0.0), after=((3, 1.6), (6, 0.0)))

# 轴体：先在特写里落三颗，然后整片下雨
FIRST = {"KeyX": 96, "KeyS": 112, "KeyC": 122, "KeyD": 128, "KeyZ": 132}
sw_time = dict(FIRST)
rest_codes = [c for c in PARTS if c not in FIRST]
rest_codes.sort(key=lambda c: PARTS[c]["cx"] * 0.55 - PARTS[c]["cy"] * 0.3 + rnd.uniform(-60, 60))
for i, c in enumerate(rest_codes):
    sw_time[c] = 146 + round(96 * i / (len(rest_codes) - 1))
for c, f in sw_time.items():
    drop(PARTS[c]["switch"], f, 230.0, 10, tilt=(rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3), rnd.uniform(-0.5, 0.5)),
         land_off=2.4, after=((3, 2.4), (5, 0.0)))

# 键帽：从后排往前排铺
cap_time = {}
order = sorted(PARTS, key=lambda c: (PARTS[c]["row"], PARTS[c]["x"]))
for i, c in enumerate(order):
    cap_time[c] = 272 + round(92 * i / (len(order) - 1)) + rnd.randint(-2, 2)
for c, f in cap_time.items():
    drop(PARTS[c]["cap"], f, 240.0, 10, tilt=(rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), rnd.uniform(-0.6, 0.6)),
         land_off=2.6, after=((2, 2.6), (4, -2.2), (7, 0.25), (9, 0.0)))

# 旋钮
F_KNOB = 402
drop(knob, F_KNOB, 200.0, 11, land_off=1.5, after=((3, 1.5), (5, 0.0)))
for i in range(0, 46):
    u = i / 45
    knob.rotation_euler = (0, 0, -2.6 * (1 - (1 - u) ** 3))
    knob.keyframe_insert("rotation_euler", index=2, frame=F_KNOB + 8 + i)
knob.rotation_euler = (0, 0, 0)

# 敲击波纹
for c, p in PARTS.items():
    press(c, 462 + round((p["cx"] + 160) / 320 * 58 + (p["row"] % 2) * 3))
for c, p in PARTS.items():
    d = ((p["cx"] - 20) ** 2 + (p["cy"] + 5) ** 2) ** 0.5
    press(c, 580 + round(d * 0.16))
for i, c in enumerate(["KeyH", "KeyE", "KeyL", "KeyL", "KeyO", "Enter"]):
    press(c, 640 + i * 5)

# scale 关键帧改成跳变，避免“长出来”
for o in bpy.data.objects:
    for fc in fcurves_of(o):
        if fc.data_path == "scale":
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'

# ----------------------------------------------------------------------------
# 相机：每个镜头一台，逐帧打关键帧，时间线标记负责切镜头
# ----------------------------------------------------------------------------
def W(code, z=0.0, dx=0.0, dy=0.0):
    p = PARTS[code]
    return ROOT_M @ (Vector((p["cx"] + dx, p["cy"] + dy, z)) * MM)


KNOB_W = ROOT_M @ (Vector((KNOB_X, KNOB_Y, 12.0)) * MM)
SHOTS_DEF = [
    # name, f0, f1, 相机起止位置, 注视点起止, 焦段, 光圈, 对焦点起止
    ("A_case", 1, 80, (-0.36, -0.40, 0.42), (-0.31, -0.35, 0.36), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 50, 11.0,
     (-0.05, -0.03, 0.01), (-0.05, -0.03, 0.01)),
    ("B_first", 81, 138, (-0.250, -0.175, 0.085), (-0.235, -0.180, 0.078), W("KeyD", 3), W("KeyD", 3), 85, 6.3,
     W("KeyX", 4), W("KeyX", 4)),
    ("C_switches", 139, 258, (-0.29, -0.30, 0.27), (-0.24, -0.31, 0.24), (-0.02, -0.005, 0.01), (-0.015, -0.005, 0.012), 62, 9.0,
     (-0.06, -0.04, 0.02), (-0.06, -0.04, 0.02)),
    ("D_caps", 259, 380, (-0.27, -0.27, 0.15), (-0.21, -0.28, 0.16), (-0.03, 0.0, 0.02), (-0.02, 0.0, 0.02), 65, 8.0,
     (-0.07, -0.02, 0.03), (-0.05, -0.03, 0.03)),
    ("E_knob", 381, 452, (0.020, -0.085, 0.105), (0.040, -0.077, 0.097), KNOB_W + Vector((-0.028, -0.014, -0.004)),
     KNOB_W + Vector((-0.024, -0.012, -0.004)), 95, 9.0, KNOB_W, KNOB_W),
    ("F_alphas", 453, 545, (-0.075, -0.255, 0.125), (-0.005, -0.255, 0.115), (0.000, -0.012, 0.020), (0.050, -0.012, 0.020), 100, 5.6,
     W("KeyJ", 13), W("KeyL", 13)),
    ("G_hero", 546, END, (0.29, -0.15, 0.15), (0.56, -0.29, 0.385), (0.025, 0.0, 0.014), (0.04, -0.012, 0.0), 60, 11.0,
     (0.05, -0.04, 0.03), (0.05, -0.04, 0.03)),
]
cams = {}
for (name, f0, f1, p0, p1, t0, t1, lens, fstop, fc0, fc1) in SHOTS_DEF:
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start, cd.clip_end = 0.01, 50
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    co = bpy.data.objects.new("Cam_" + name, cd)
    col_env.objects.link(co)
    p0, p1, t0, t1, fc0, fc1 = (Vector(v) for v in (p0, p1, t0, t1, fc0, fc1))
    for f in range(f0, f1 + 1):
        u = (f - f0) / max(1, f1 - f0)
        e = 0.5 * u + 0.5 * u * (2 - u)            # 轻微减速
        co.location = p0.lerp(p1, e)
        tgt = t0.lerp(t1, e)
        look_at(co, tgt)
        view = (tgt - co.location).normalized()
        cd.dof.focus_distance = (fc0.lerp(fc1, e) - co.location).dot(view)
        co.keyframe_insert("location", frame=f)
        co.keyframe_insert("rotation_euler", frame=f)
        cd.keyframe_insert("dof.focus_distance", frame=f)
    mk = scene.timeline_markers.new(name, frame=f0)
    mk.camera = co
    cams[name] = co
scene.camera = cams["A_case"]

# ----------------------------------------------------------------------------
# 渲染设置
# ----------------------------------------------------------------------------
scene.render.engine = 'CYCLES'
scene.render.resolution_x, scene.render.resolution_y = RES
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.max_bounces = 16
scene.cycles.transmission_bounces = 16
scene.cycles.transparent_max_bounces = 24
scene.cycles.glossy_bounces = 6
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.5
try:
    scene.cycles.motion_blur_position = 'START'   # 快门只往后开，物体出现的那一帧不会被前一帧的“零缩放”拖影
except Exception:
    scene.render.motion_blur_position = 'START'
scene.render.use_persistent_data = True
scene.render.image_settings.file_format = 'PNG'
try:
    scene.view_settings.view_transform = VIEW
    scene.view_settings.look = LOOK
    scene.view_settings.exposure = EXPOSURE
except Exception as e:
    print("[kb] view transform:", e)
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for t in ('OPTIX', 'CUDA'):
        prefs.compute_device_type = t
        try:
            prefs.refresh_devices()
        except Exception:
            prefs.get_devices()
        if any(d.type == t for d in prefs.devices):
            for d in prefs.devices:
                d.use = (d.type == t)
            scene.cycles.device = 'GPU'
            print("[kb] cycles device:", t, [d.name for d in prefs.devices if d.use])
            break
except Exception as e:
    print("[kb] GPU setup failed, using CPU:", e)

if DO_SAVE:
    blend = os.path.join(ROOT, "blender", "keyboard.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("[kb] saved", blend)


def render_frame(f, path):
    for (name, f0, f1, *_r) in SHOTS_DEF:
        if f0 <= f <= f1:
            scene.camera = cams[name]
    scene.frame_set(f)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("[kb] rendered", f, path, flush=True)


for item in STILLS:
    name, _, fr = item.partition(":")
    render_frame(int(fr or name), os.path.join(OUT_DIR, name + ".png"))

if ANIM:
    a, b = (int(v) for v in ANIM.split("-"))
    os.makedirs(ANIM_DIR, exist_ok=True)
    for f in range(a, b + 1):
        path = os.path.join(ANIM_DIR, "%04d.png" % f)
        if os.path.exists(path) and not arg("--force", False):
            continue
        render_frame(f, path)

print("[kb] done: %d keys" % len(layout))
