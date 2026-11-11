# -*- coding: utf-8 -*-
"""
程序化建模一把 75% 机械键盘（Blender 5.x）。

用法（在项目根目录）:
  blender -b -P blender/build_keyboard.py -- [--shots hero,detail,top] [--samples 256]
                                             [--no-export] [--no-save] [--res 1920x1080]

产物:
  blender/keyboard.blend              完整场景
  public/models/keyboard.glb          给网页用的模型
  renders/<shot>.png                  Cycles 渲染图
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
SHOTS = [s for s in str(arg("--shots", "")).split(",") if s and s != "True"]
SAMPLES = int(arg("--samples", 256))
RES = tuple(int(v) for v in str(arg("--res", "1920x1080")).split("x"))
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
COL_ALPHA = (0.70, 0.66, 0.57)
COL_MOD = (0.030, 0.065, 0.085)
COL_ACCENT = (0.80, 0.17, 0.035)
COL_CASE = (0.72, 0.73, 0.74)

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


def principled(name, color, rough=0.5, metal=0.0, bump=None, coat=0.0, emission=None):
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


M_ALPHA = principled("Keycap_Alpha", COL_ALPHA, rough=0.46, bump=(5200.0, 0.10))
M_MOD = principled("Keycap_Mod", COL_MOD, rough=0.44, bump=(5200.0, 0.10))
M_ACCENT = principled("Keycap_Accent", COL_ACCENT, rough=0.44, bump=(5200.0, 0.10))
M_LEG_DARK = principled("Legend_Dark", (0.022, 0.045, 0.060), rough=0.5)
M_LEG_LIGHT = principled("Legend_Light", (0.80, 0.77, 0.68), rough=0.5)
M_CASE = principled("Case_Aluminum", COL_CASE, rough=0.40, metal=1.0, bump=(9000.0, 0.03))
M_PLATE = principled("Plate", (0.012, 0.013, 0.015), rough=0.55, metal=0.7)
M_HOUSING = principled("Switch_Housing", (0.014, 0.014, 0.016), rough=0.30)
M_STEM = principled("Switch_Stem", (0.85, 0.50, 0.05), rough=0.35)
M_KNOB = principled("Knob", (0.60, 0.61, 0.63), rough=0.30, metal=1.0)
M_MAT = principled("DeskMat", (0.020, 0.023, 0.027), rough=0.95, bump=(2600.0, 0.5))
M_CABLE = principled("Cable", (0.62, 0.58, 0.50), rough=0.85, bump=(1500.0, 0.6))
M_PLUG = principled("Plug", (0.35, 0.36, 0.38), rough=0.35, metal=1.0)

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
    row(0, 0, [("Escape", "Esc", 1, X), .25,
               ("F1", "F1", 1, A), ("F2", "F2", 1, A), ("F3", "F3", 1, A), ("F4", "F4", 1, A), .25,
               ("F5", "F5", 1, M), ("F6", "F6", 1, M), ("F7", "F7", 1, M), ("F8", "F8", 1, M), .25,
               ("F9", "F9", 1, A), ("F10", "F10", 1, A), ("F11", "F11", 1, A), ("F12", "F12", 1, A), .25,
               ("Delete", "Del", 1, M)])
    nums = [("Backquote", "`")] + [("Digit%d" % (i % 10), str(i % 10)) for i in range(1, 11)] + \
           [("Minus", "-"), ("Equal", "=")]
    row(1.25, 1, [(c, l, 1, A) for c, l in nums] + [("Backspace", "Back", 2, M), .25, ("PageUp", "PgUp", 1, M)])
    row(2.25, 2, [("Tab", "Tab", 1.5, M)] + [("Key" + ch, ch, 1, A) for ch in "QWERTYUIOP"] +
        [("BracketLeft", "[", 1, A), ("BracketRight", "]", 1, A), ("Backslash", "\\", 1.5, A), .25,
         ("PageDown", "PgDn", 1, M)])
    row(3.25, 3, [("CapsLock", "Caps", 1.75, M)] + [("Key" + ch, ch, 1, A) for ch in "ASDFGHJKL"] +
        [("Semicolon", ";", 1, A), ("Quote", "'", 1, A), ("Enter", "Enter", 2.25, X), .25,
         ("Home", "Home", 1, M)])
    row(4.25, 4, [("ShiftLeft", "Shift", 2.25, M)] + [("Key" + ch, ch, 1, A) for ch in "ZXCVBNM"] +
        [("Comma", ",", 1, A), ("Period", ".", 1, A), ("Slash", "/", 1, A), ("ShiftRight", "Shift", 1.75, M)])
    row(5.25, 5, [("ControlLeft", "Ctrl", 1.25, M), ("MetaLeft", "Win", 1.25, M), ("AltLeft", "Alt", 1.25, M),
                  ("Space", "", 6.25, A), ("AltRight", "Alt", 1, M), ("Fn", "Fn", 1, M),
                  ("ControlRight", "Ctrl", 1, M)])
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
# 轴体
# ----------------------------------------------------------------------------
def make_switch_housing():
    mb = MB()
    a = mb.ring(rring(7.8, 7.8, 0.6, 3, 2, 2), 0.0)
    b = mb.ring(rring(7.8, 7.8, 0.6, 3, 2, 2), 0.8)
    c = mb.ring(rring(7.0, 7.0, 0.9, 3, 2, 2), 0.8)
    d = mb.ring(rring(5.6, 5.9, 1.1, 3, 2, 2), 5.2)
    mb.cap(a)
    mb.bridge(a, b)
    mb.bridge(b, c)
    mb.bridge(c, d)
    mb.cap(d)
    return mb.build("SwitchHousing", sharp_deg=30)


def make_stem():
    mb = MB()
    z = -CAP_REST
    mb.box(-2.9, 2.9, -3.7, 3.7, z + 3.9, z + 5.7)
    mb.box(-2.05, 2.05, -0.65, 0.65, z + 5.7, z + 9.2)
    mb.box(-0.58, 0.58, -2.05, 2.05, z + 5.7, z + 9.2)
    return mb.build("SwitchStem", smooth=False)


# ----------------------------------------------------------------------------
# 外壳 / 定位板 / 旋钮
# ----------------------------------------------------------------------------
TT = tan(radians(TILT))


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
    rs.append(mb.ring(rring(OX, OY, RC, k, mx, my), BEZ - RF - 0.5))
    for phi in (0, 22.5, 45, 67.5, 90):
        o = RF * (1 - cos(radians(phi)))
        rs.append(mb.ring(rring(OX - o, OY - o, RC - o, k, mx, my), BEZ - RF + RF * sin(radians(phi))))
    rs.append(mb.ring(rring(OX - RF - 0.5, OY - RF - 0.5, RC - RF - 0.5, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX + 1.1, PY + 1.1, 2.6, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX + 0.6, PY + 0.6, 2.1, k, mx, my), BEZ))
    rs.append(mb.ring(rring(PX, PY, 1.5, k, mx, my), BEZ - 0.6))
    rs.append(mb.ring(rring(PX, PY, 1.5, k, mx, my), -0.3))
    mb.cap(rs[0])
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.cap(rs[-1])
    return mb.build("Case", sharp_deg=32)


def make_plate():
    mb = MB()
    mb.cap(mb.ring(rring(PX - 0.02, PY - 0.02, 1.48, 4, 2, 2), 0.0))
    me = mb.build("Plate", smooth=False)
    return me


def make_knob():
    n = 96
    mb = MB()
    prof = [  # (r, z, knurl)
        (5.0, 1.0, 0), (8.5, 1.0, 0), (8.5, 2.4, 0), (8.2, 2.9, 0),
        (8.2, 3.3, 0.36), (8.2, 14.6, 0.36),
        (8.2, 15.0, 0), (7.5, 15.9, 0), (6.6, 15.9, 0), (6.2, 15.5, 0), (2.0, 15.4, 0),
    ]
    rs = [mb.ring(circle(r, n, kn), z) for (r, z, kn) in prof]
    mb.cap(rs[0])
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b)
    mb.fan(rs[-1], (0, 0, 15.4))
    return mb.build("Knob", sharp_deg=28)


def make_mat():
    mb = MB()
    a = mb.ring(rring(450, 210, 10, 10, 2, 2), -3.0)
    b = mb.ring(rring(450, 210, 10, 10, 2, 2), -0.7)
    c = mb.ring(rring(449.3, 209.3, 9.3, 10, 2, 2), 0.0)
    mb.cap(a)
    mb.bridge(a, b)
    mb.bridge(b, c)
    mb.cap(c)
    return mb.build("DeskMat", sharp_deg=60)


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------
th = radians(TILT)
root = bpy.data.objects.new("Keyboard", None)
col_kb.objects.link(root)
root.location = (0, 0, (DF * cos(th) + OY * sin(th)) * MM)
root.rotation_euler = (th, 0, 0)
ROOT_M = Matrix.Translation(root.location) @ Matrix.Rotation(th, 4, 'X')

add_obj("Case", make_case(), root, mats=[M_CASE])
add_obj("Plate", make_plate(), root, mats=[M_PLATE])
knob = add_obj("Knob", make_knob(), root, loc=(15.75 * U - KEYS_W / 2, KEYS_H / 2 - 0.5 * U, 0), mats=[M_KNOB])

housing_me = make_switch_housing()
stem_me = make_stem()
layout = build_layout()
for kdef in layout:
    code = kdef["code"]
    cap_me, ztop, oy = make_cap(kdef["w"], kdef["row"], code == "Space")
    add_obj("Switch_" + code, housing_me, root, loc=(kdef["cx"], kdef["cy"], 0), mats=[])
    cap = add_obj("Key_" + code, cap_me, root, loc=(kdef["cx"], kdef["cy"], CAP_REST))
    cap["code"] = code
    cap["w"] = float(kdef["w"])
    cap["kind"] = kdef["kind"]
    # 键帽网格按 (宽度, 行) 共享，颜色放在对象槽位上
    if not cap_me.materials:
        cap_me.materials.append(None)
    cap.material_slots[0].link = 'OBJECT'
    cap.material_slots[0].material = KIND_MAT[kdef["kind"]]
    add_obj("Stem_" + code, stem_me, cap)
    leg = make_legend(kdef["label"], ztop, oy, kdef["w"])
    if leg:
        add_obj("Legend_" + code, leg, cap, mats=[KIND_LEG[kdef["kind"]]])
housing_me.materials.append(M_HOUSING)
stem_me.materials.append(M_STEM)

add_obj("DeskMat", make_mat(), None, loc=(0, 15, 0), mats=[M_MAT])

# 线材 + 插头
p0 = ROOT_M @ (Vector((-95.0, OY, -3.5)) * MM)
plug_mb = MB()
a = plug_mb.ring(rring(5.6, 3.2, 3.0, 6, 2, 2), 0.0)
b = plug_mb.ring(rring(5.6, 3.2, 3.0, 6, 2, 2), 15.0)
c = plug_mb.ring(rring(3.0, 2.2, 2.0, 6, 2, 2), 19.0)
plug_mb.cap(a)
plug_mb.bridge(a, b)
plug_mb.bridge(b, c)
plug_mb.cap(c)
plug = add_obj("Plug", plug_mb.build("Plug", sharp_deg=35), None, mats=[M_PLUG])
plug.location = p0
plug.rotation_euler = (radians(-90), 0, 0)   # 局部 +Z 指向世界 +Y（朝后伸出）

cu = bpy.data.curves.new("CableCurve", 'CURVE')
cu.dimensions = '3D'
cu.bevel_depth = 1.9 * MM
cu.bevel_resolution = 4
cu.resolution_u = 16
sp = cu.splines.new('BEZIER')
pts = [p0 + Vector((0, 0.017, 0)),
       p0 + Vector((0, 0.045, -0.003)),
       Vector((p0.x - 0.03, p0.y + 0.10, 0.0019)),
       Vector((p0.x - 0.13, p0.y + 0.135, 0.0019)),
       Vector((p0.x - 0.27, p0.y + 0.10, 0.0019)),
       Vector((p0.x - 0.42, p0.y + 0.14, 0.0019)),
       Vector((p0.x - 0.62, p0.y + 0.13, 0.0019))]
sp.bezier_points.add(len(pts) - 1)
for bp, p in zip(sp.bezier_points, pts):
    bp.co = p
    bp.handle_left_type = bp.handle_right_type = 'AUTO'
tmp = bpy.data.objects.new("CableTmp", cu)
col_kb.objects.link(tmp)
bpy.context.view_layer.update()
cable_me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
cable_me.name = "Cable"
for p in cable_me.polygons:
    p.use_smooth = True
bpy.data.objects.remove(tmp)
add_obj("Cable", cable_me, None, mats=[M_CABLE])

# ----------------------------------------------------------------------------
# 导出 GLB
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

# ----------------------------------------------------------------------------
# 摄影棚：桌面、灯光、相机
# ----------------------------------------------------------------------------
desk_me = bpy.data.meshes.new("Desk")
desk_me.from_pydata([(-3, -3, -0.003), (3, -3, -0.003), (3, 3, -0.003), (-3, 3, -0.003)], [], [(0, 1, 2, 3)])
add_obj("Desk", desk_me, None, col=col_env, mats=[wood_material()])

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
hdr = os.path.join(bpy.utils.resource_path('LOCAL'), "datafiles", "studiolights", "world", "interior.exr")
if os.path.exists(hdr):
    w_env = wnt.nodes.new("ShaderNodeTexEnvironment")
    w_env.image = bpy.data.images.load(hdr)
    w_tc = wnt.nodes.new("ShaderNodeTexCoord")
    w_map = wnt.nodes.new("ShaderNodeMapping")
    w_map.inputs["Rotation"].default_value = (0, 0, radians(110))
    wnt.links.new(w_tc.outputs["Generated"], w_map.inputs[0])
    wnt.links.new(w_map.outputs[0], w_env.inputs[0])
    wnt.links.new(w_env.outputs[0], w_bg.inputs[0])
w_bg.inputs[1].default_value = 0.22


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


area_light("Key", (-0.45, 0.30, 0.70), (0, 0, 0.02), (0.9, 0.6), 14, (1.0, 0.96, 0.90))
area_light("Fill", (0.55, -0.45, 0.35), (0, 0, 0.02), (0.6, 0.4), 3.0, (0.86, 0.92, 1.0))
area_light("Rim", (0.25, 0.62, 0.22), (0, 0.02, 0.03), (0.9, 0.12), 9, (1.0, 0.93, 0.85))

CAMS = {
    #  name: (location, target, lens, fstop, focus_target)
    "hero": ((-0.27, -0.47, 0.34), (0.012, -0.005, 0.012), 55, 9.0, (-0.03, -0.04, 0.03)),
    "detail": ((0.27, -0.31, 0.135), (0.035, -0.012, 0.02), 75, 6.3, (0.085, -0.055, 0.03)),
    "top": ((0.0, -0.06, 0.78), (0.0, 0.003, 0.0), 80, 16.0, (0, 0, 0.02)),
    "side": ((-0.42, -0.16, 0.07), (-0.05, 0.0, 0.022), 70, 4.0, (-0.16, -0.05, 0.03)),
}
cams = {}
for name, (loc, tgt, lens, fstop, ftgt) in CAMS.items():
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start, cd.clip_end = 0.01, 50
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    co = bpy.data.objects.new("Cam_" + name, cd)
    col_env.objects.link(co)
    co.location = loc
    look_at(co, tgt)
    cd.dof.focus_distance = (Vector(ftgt) - co.location).length
    cams[name] = co
scene.camera = cams["hero"]

# 渲染设置
scene.render.engine = 'CYCLES'
scene.render.resolution_x, scene.render.resolution_y = RES
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.use_adaptive_sampling = True
try:
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
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

for shot in SHOTS:
    if shot not in cams:
        print("[kb] unknown shot", shot)
        continue
    scene.camera = cams[shot]
    scene.render.filepath = os.path.join(ROOT, "renders", shot + ".png")
    bpy.ops.render.render(write_still=True)
    print("[kb] rendered", scene.render.filepath)

print("[kb] done: %d keys" % len(layout))
