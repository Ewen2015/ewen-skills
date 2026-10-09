#!/usr/bin/env python3
"""生成封面的「主题插画装饰层」——画在书封四周的手绘感扁平线稿。

    python3 cover_deco.py --list
    python3 cover_deco.py --preset garland --out build/deco.svg
    python3 cover_deco.py --preset garland > /tmp/deco.svg      # 直接贴进 cover.html

为什么是"直接画"而不是跑图模型：装饰层要能复现、要能按书改、还必须是**矢量**的，
缩到任何尺寸都锐利。所有产出都是 SVG 路径，配色走 card.css 的 --deco-* 令牌
（线是深暖褐不是纯黑、大面积平涂、低饱和暖调）——这就是 illustration-style 的
「风格指纹」落到矢量上的写法：勾线在前、平涂在后、颜色收着。

## 三条硬规矩（别改）

1. **书封原版完整。** 装饰永远画在书封矩形之外（BOOK_L / BOOK_R 两侧的栏里），
   `col_bounds()` + `leaf()` / `bud()` 里的收缩循环负责这件事。书本身留给 cover.html
   里那张 `<img>`，不加工、不裁切、不叠色。
2. **所有花叶必须完整落在画面内**，不能被画布边缘切一半；只有藤蔓的末端允许伸出画面。
3. **强调色只做信号。** `--accent`（#FD6408）在装饰里最多出现一两处小花小苞；
   大面积铺色一律用 --deco-terra / olive / gold / rose。

## 加一本新书

`garland()` 是《The Beauty of the Husband》那一版的构图，也是模板：四个角各一簇
`spri`（花枝）→ 中段用一条向外弯的 `sprig` 当垂花彩带把上下连起来 → 再散几个音符/小果。
换书就换 motif：把主题拆成 2–3 个能画成图形的东西（这本书是"29 首探戈 → 音符"、
"美与伤口 → 玫瑰与刺"、"画布龟裂 → 裂纹"），照着改坐标即可。
"""

import math, random

INK='var(--deco-line)'; TERRA='var(--deco-terra)'; OLIVE='var(--deco-olive)'
GOLD='var(--deco-gold)'; ROSE='var(--deco-rose)'; CREAM='var(--deco-cream)'
ACC='var(--accent)'
# 内圈花瓣用同色系浅调，避免出现"白色星芒"的观感
INNER={TERRA:'#E3C2AB', ROSE:'#EBD6C8', GOLD:'#EADCB6', OLIVE:'#CFCBA8', ACC:'#FBC9A3', CREAM:'#F3E9DA'}

X0,X1,Y0,Y1 = 8, 1072, 8, 837      # 画面边界
BOOK_L, BOOK_R = 282, 798          # 书封左右边界（装饰不得越界，书封必须原版完整）

def col_bounds(cx):
    """按中心落在哪一栏，返回该栏允许的 x 范围——保证装饰永不压到书封。"""
    return (X0, BOOK_L) if cx < 540 else (BOOK_R, X1)

def f(v): return f'{v:.1f}'
def dirv(a): return (math.cos(a), math.sin(a))

def petal(cx,cy,r,ang):
    a=math.radians(ang); ux,uy=dirv(a); px,py=-uy,ux
    bw=r*0.46; tx,ty=cx+ux*r, cy+uy*r
    c1=(cx+ux*r*0.42+px*bw, cy+uy*r*0.42+py*bw); c2=(tx+px*bw*0.30, ty+py*bw*0.30)
    c3=(tx-px*bw*0.30, ty-py*bw*0.30); c4=(cx+ux*r*0.42-px*bw, cy+uy*r*0.42-py*bw)
    return (f"M{f(cx)},{f(cy)} C{f(c1[0])},{f(c1[1])} {f(c2[0])},{f(c2[1])} {f(tx)},{f(ty)} "
            f"C{f(c3[0])},{f(c3[1])} {f(c4[0])},{f(c4[1])} {f(cx)},{f(cy)}Z")

def spiral(cx,cy,r0,r1,turns=2.0,steps=64):
    pts=[]
    for i in range(steps+1):
        t=i/steps; th=t*turns*2*math.pi; r=r0+(r1-r0)*t
        pts.append((cx+r*math.cos(th), cy+r*math.sin(th)))
    return 'M'+' L'.join(f'{f(x)},{f(y)}' for x,y in pts)

def rose(cx,cy,r,rot_deg=0,fill=TERRA,sw=3.6):
    bx0,bx1=col_bounds(cx)
    cx=max(bx0+r*1.02, min(bx1-r*1.02, cx)); cy=max(Y0+r*1.02, min(Y1-r*1.02, cy))
    inner=INNER.get(fill, CREAM)
    return (f'<path d="{"".join(petal(cx,cy,r,rot_deg+i*72) for i in range(5))}" fill="{fill}" '
            f'stroke="{INK}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'<path d="{"".join(petal(cx,cy,r*0.50,rot_deg+36+i*120) for i in range(3))}" fill="{inner}" '
            f'stroke="{INK}" stroke-width="{sw*0.72:.1f}" stroke-linejoin="round"/>'
            f'<path d="{spiral(cx,cy,r*0.05,r*0.30,2.0,58)}" fill="none" '
            f'stroke="{INK}" stroke-width="{sw*0.62:.1f}" stroke-linecap="round"/>')

def _bbox(pts):
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)

def leaf(x,y,L,ang,fill=OLIVE,sw=2.3):
    a=math.radians(ang); ux,uy=dirv(a); px,py=-uy,ux
    bx0,bx1=col_bounds(x)
    for _ in range(20):                       # 逐步缩到画面内、且不压书封
        w=L*0.38; tx,ty=x+ux*L, y+uy*L
        c1=(x+ux*L*0.34+px*w, y+uy*L*0.34+py*w); c2=(tx-ux*L*0.34+px*w, ty-uy*L*0.34+py*w)
        c3=(tx-ux*L*0.34-px*w, ty-uy*L*0.34-py*w); c4=(x+ux*L*0.34-px*w, y+uy*L*0.34-py*w)
        _x0,by0,_x1,by1=_bbox([(x,y),c1,c2,(tx,ty),c3,c4])
        if _x0>=bx0 and _x1<=bx1 and by0>=Y0 and by1<=Y1: break
        L*=0.85
    d=(f"M{f(x)},{f(y)} C{f(c1[0])},{f(c1[1])} {f(c2[0])},{f(c2[1])} {f(tx)},{f(ty)} "
       f"C{f(c3[0])},{f(c3[1])} {f(c4[0])},{f(c4[1])} {f(x)},{f(y)}Z")
    v=f"M{f(x+ux*L*0.18)},{f(y+uy*L*0.18)} L{f(tx-ux*L*0.12)},{f(ty-uy*L*0.12)}"
    return (f'<path d="{d}" fill="{fill}" stroke="{INK}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'<path d="{v}" fill="none" stroke="{INK}" stroke-width="1.4" stroke-linecap="round"/>')

def bud(x,y,L,ang,fill=ACC,sw=2.2):
    a=math.radians(ang); ux,uy=dirv(a); px,py=-uy,ux
    bx0,bx1=col_bounds(x)
    for _ in range(16):
        w=L*0.44; tx,ty=x+ux*L, y+uy*L
        c1=(x+ux*L*0.5+px*w, y+uy*L*0.5+py*w); c2=(x+ux*L*0.5-px*w, y+uy*L*0.5-py*w)
        _x0,by0,_x1,by1=_bbox([(x,y),c1,c2,(tx,ty)])
        if _x0>=bx0 and _x1<=bx1 and by0>=Y0 and by1<=Y1: break
        L*=0.85
    return (f'<path d="M{f(x)},{f(y)} C{f(c1[0])},{f(c1[1])} {f(tx)},{f(ty)} '
            f'C{f(c2[0])},{f(c2[1])} {f(x)},{f(y)}Z" fill="{fill}" stroke="{INK}" '
            f'stroke-width="{sw}" stroke-linejoin="round"/>')

def thorn(x,y,ang,side,size=13):
    a=math.radians(ang); ux,uy=dirv(a); px,py=-uy,ux
    b1=(x+ux*size*0.5, y+uy*size*0.5); b2=(x-ux*size*0.5, y-uy*size*0.5)
    tip=(x+px*side*size*1.25, y+py*side*size*1.25)
    return (f'<path d="M{f(b1[0])},{f(b1[1])} L{f(tip[0])},{f(tip[1])} L{f(b2[0])},{f(b2[1])}Z" '
            f'fill="{INK}" stroke="{INK}" stroke-width="1.1" stroke-linejoin="round"/>')

def note(cx,cy,s=1.0,flip=False):
    hx,hy=cx,cy; stem=hx+8*s; top=hy-38*s
    head=f"M{f(hx-8.5*s)},{f(hy)} a{f(8.5*s)},{f(6.4*s)} 0 1 0 {f(17*s)},0 a{f(8.5*s)},{f(6.4*s)} 0 1 0 {f(-17*s)},0Z"
    k=1 if not flip else -1
    tail=f"M{f(stem)},{f(top)} c{f(9*s*k)},{f(7*s)} {f(12*s*k)},{f(15*s)} {f(5*s*k)},{f(24*s)}"
    return (f'<path d="{head}" fill="{INK}"/>'
            f'<path d="M{f(stem)},{f(hy-1*s)} L{f(stem)},{f(top)}" stroke="{INK}" '
            f'stroke-width="{f(3.2*s)}" stroke-linecap="round" fill="none"/>'
            f'<path d="{tail}" fill="none" stroke="{INK}" stroke-width="2.8" stroke-linecap="round"/>')

def bez(p0,p1,p2,t):
    return ((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0],
            (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1])

def sprig(x0,y0,x1,y1,bend,leaves,L0,L1,rose_r=0,rose_fill=TERRA,leaf_fill=OLIVE,
          side0=1,thorns=False,sw=3.6,t0=0.16):
    dx,dy=x1-x0,y1-y0; D=math.hypot(dx,dy) or 1
    nx,ny=-dy/D,dx/D; mx,my=(x0+x1)/2,(y0+y1)/2
    c=(mx+nx*bend, my+ny*bend)
    N=140; pts=[bez((x0,y0),c,(x1,y1),i/N) for i in range(N+1)]
    out=[f'<path d="M{f(x0)},{f(y0)} Q{f(c[0])},{f(c[1])} {f(x1)},{f(y1)}" fill="none" '
         f'stroke="{INK}" stroke-width="{sw}" stroke-linecap="round"/>']
    for k in range(leaves):
        t=t0+(0.94-t0)*(k+0.5)/leaves
        i=min(int(t*N),N-2); x,y=pts[i]; x2,y2=pts[min(i+3,N)]
        ang=math.degrees(math.atan2(y2-y,x2-x))
        side=side0 if k%2==0 else -side0
        a=ang+side*(54+(9 if k%3==0 else -6))+math.sin(k*1.9)*6
        L=L0+(L1-L0)*((k*53)%7)/6
        out.append(leaf(x,y,L,a,leaf_fill))
    if thorns:
        for k in range(3):
            t=0.26+0.24*k
            i=min(int(t*N),N-1); x,y=pts[i]; x2,y2=pts[min(i+4,N)]
            out.append(thorn(x,y,math.degrees(math.atan2(y2-y,x2-x)),-side0,12))
    if rose_r: out.append(rose(x1,y1,rose_r,0,rose_fill))
    return ''.join(out)

def cracks(seed=11,count=9,w=1080,h=845):
    rnd=random.Random(seed); out=[]
    for _ in range(count):
        x=rnd.uniform(-30,w); y=rnd.uniform(-30,h); a=rnd.uniform(0,2*math.pi); pts=[(x,y)]
        for _ in range(rnd.randint(4,7)):
            a+=rnd.uniform(-0.85,0.85); s=rnd.uniform(60,150)
            x+=math.cos(a)*s; y+=math.sin(a)*s; pts.append((x,y))
        out.append('<path d="M'+' L'.join(f'{f(px)},{f(py)}' for px,py in pts)+f'" fill="none" '
                   f'stroke="{INK}" stroke-width="1.2" stroke-linecap="round" opacity="0.11"/>')
    return ''.join(out)

def build():
    S=[f'<g>{cracks()}</g>']

    # ============ 左上角 ============
    S.append(sprig(56,44, 246,132, 26, 5, 42, 68, rose_r=46, rose_fill=TERRA, leaf_fill=OLIVE, side0=-1, thorns=True))
    S.append(sprig(40,110, 158,276, -30, 5, 34, 54, rose_r=30, rose_fill=ROSE, leaf_fill=OLIVE, side0=1))
    S.append(sprig(120,30, 236,182, 10, 3, 26, 40, leaf_fill=TERRA, side0=-1))
    S.append(bud(72,214,28,110,GOLD)); S.append(bud(196,64,24,150,ACC))

    # ============ 右上角 ============
    S.append(sprig(1024,46, 838,138, -26, 5, 40, 66, rose_r=44, rose_fill=GOLD, leaf_fill=TERRA, side0=1, thorns=True))
    S.append(sprig(1040,112, 926,280, 30, 5, 32, 52, rose_r=0, leaf_fill=OLIVE, side0=-1))
    S.append(bud(930,282,30,-30,OLIVE))
    S.append(sprig(962,32, 850,186, -10, 3, 26, 40, leaf_fill=OLIVE, side0=1))
    S.append(bud(1012,216,26,-110,ROSE)); S.append(bud(892,66,22,-150,GOLD))

    # ============ 左下角 ============
    S.append(sprig(44,800, 246,714, -26, 5, 40, 66, rose_r=44, rose_fill=ROSE, leaf_fill=OLIVE, side0=1, thorns=True))
    S.append(sprig(34,742, 156,566, 30, 5, 32, 54, rose_r=24, rose_fill=ACC, leaf_fill=TERRA, side0=-1))
    S.append(sprig(112,824, 214,676, -8, 3, 26, 40, leaf_fill=OLIVE, side0=1))
    S.append(bud(64,660,28,-70,TERRA)); S.append(bud(188,796,24,20,ROSE))

    # ============ 右下角 ============
    S.append(sprig(1032,802, 838,716, 26, 5, 38, 64, rose_r=42, rose_fill=TERRA, leaf_fill=OLIVE, side0=-1, thorns=True))
    S.append(sprig(1046,744, 932,568, -30, 5, 32, 52, rose_r=26, rose_fill=GOLD, leaf_fill=TERRA, side0=1))
    S.append(sprig(966,826, 868,682, 8, 3, 24, 38, leaf_fill=OLIVE, side0=-1))
    S.append(bud(1010,662,26,70,ROSE)); S.append(bud(888,800,22,-20,ACC))

    # ============ 两侧中段：把上下花簇连成一圈 ============
    S.append(sprig(96,286, 92,584, -96, 7, 30, 50, leaf_fill=OLIVE, side0=-1, sw=2.9, t0=0.10, thorns=True))
    S.append(bud(24,436,26,150,TERRA))
    S.append(sprig(988,290, 992,580, 96, 7, 30, 50, leaf_fill=TERRA, side0=1, sw=2.9, t0=0.10, thorns=True))
    S.append(bud(1058,440,26,-150,OLIVE))

    # ============ 音符：29 首探戈 ============
    S.append(note(232,404,0.95)); S.append(note(180,470,0.78,flip=True))
    S.append(note(852,392,0.9,flip=True)); S.append(note(892,486,0.74))
    for bx,by,r in [(178,150,4.5),(120,340,3.6),(168,644,4.2),(60,472,3.4),
                    (900,158,4.4),(958,352,3.5),(910,646,4.2),(1020,468,3.3)]:
        S.append(f'<circle cx="{bx}" cy="{by}" r="{r}" fill="{GOLD}"/>')
    return '\n'.join(S)


# ============================ 预设构图 ============================

def _frame(corner_rose, leaf_a, leaf_b, note_pos, berry_pos):
    """四角花簇 + 两侧垂花彩带的通用外框；换色/换花就是换参数。"""
    S=[f'<g>{cracks()}</g>']
    tl,tr,bl,br = corner_rose
    S.append(sprig(56,44, 246,132, 26, 5, 42, 68, rose_r=tl[0], rose_fill=tl[1], leaf_fill=leaf_a, side0=-1, thorns=True))
    S.append(sprig(40,110, 158,276, -30, 5, 34, 54, rose_r=30, rose_fill=ROSE, leaf_fill=leaf_a, side0=1))
    S.append(sprig(120,30, 236,182, 10, 3, 26, 40, leaf_fill=leaf_b, side0=-1))
    S.append(bud(72,214,28,110,GOLD)); S.append(bud(196,64,24,150,ACC))

    S.append(sprig(1024,46, 838,138, -26, 5, 40, 66, rose_r=tr[0], rose_fill=tr[1], leaf_fill=leaf_b, side0=1, thorns=True))
    S.append(sprig(1040,112, 926,280, 30, 5, 32, 52, rose_r=0, leaf_fill=leaf_a, side0=-1))
    S.append(bud(930,282,30,-30,OLIVE))
    S.append(sprig(962,32, 850,186, -10, 3, 26, 40, leaf_fill=leaf_a, side0=1))
    S.append(bud(1012,216,26,-110,ROSE)); S.append(bud(892,66,22,-150,GOLD))

    S.append(sprig(44,800, 246,714, -26, 5, 40, 66, rose_r=bl[0], rose_fill=bl[1], leaf_fill=leaf_a, side0=1, thorns=True))
    S.append(sprig(34,742, 156,566, 30, 5, 32, 54, rose_r=24, rose_fill=ACC, leaf_fill=leaf_b, side0=-1))
    S.append(sprig(112,824, 214,676, -8, 3, 26, 40, leaf_fill=leaf_a, side0=1))
    S.append(bud(64,660,28,-70,TERRA)); S.append(bud(188,796,24,20,ROSE))

    S.append(sprig(1032,802, 838,716, 26, 5, 38, 64, rose_r=br[0], rose_fill=br[1], leaf_fill=leaf_a, side0=-1, thorns=True))
    S.append(sprig(1046,744, 932,568, -30, 5, 32, 52, rose_r=26, rose_fill=GOLD, leaf_fill=leaf_b, side0=1))
    S.append(sprig(966,826, 868,682, 8, 3, 24, 38, leaf_fill=leaf_a, side0=-1))
    S.append(bud(1010,662,26,70,ROSE)); S.append(bud(888,800,22,-20,ACC))

    S.append(sprig(96,286, 92,584, -96, 7, 30, 50, leaf_fill=leaf_a, side0=-1, sw=2.9, t0=0.10, thorns=True))
    S.append(bud(24,436,26,150,TERRA))
    S.append(sprig(988,290, 992,580, 96, 7, 30, 50, leaf_fill=leaf_b, side0=1, sw=2.9, t0=0.10, thorns=True))
    S.append(bud(1058,440,26,-150,OLIVE))

    for cx,cy,s,flip in note_pos:
        S.append(note(cx,cy,s,flip))
    for bx,by,r in berry_pos:
        S.append(f'<circle cx="{bx}" cy="{by}" r="{r}" fill="{GOLD}"/>')
    return '\n'.join(S)


def garland():
    """《The Beauty of the Husband》用的那版：玫瑰与刺 + 探戈音符 + 画布龟裂。"""
    return _frame(
        corner_rose=((46,TERRA),(44,GOLD),(44,ROSE),(42,TERRA)),
        leaf_a=OLIVE, leaf_b=TERRA,
        note_pos=[(232,404,0.95,False),(180,470,0.78,True),(852,392,0.9,True),(892,486,0.74,False)],
        berry_pos=[(178,150,4.5),(120,340,3.6),(168,644,4.2),(60,472,3.4),
                   (900,158,4.4),(958,352,3.5),(910,646,4.2),(1020,468,3.3)],
    )


def notes():
    """更轻的一版：只有音符与裂纹，适合音乐/节奏类的书。"""
    S=[f'<g>{cracks()}</g>',
       sprig(70,60, 236,150, 24, 4, 34, 56, rose_r=0, leaf_fill=OLIVE, side0=-1, thorns=True),
       sprig(1010,62, 848,152, -24, 4, 34, 56, rose_r=0, leaf_fill=TERRA, side0=1, thorns=True),
       sprig(70,790, 236,700, -24, 4, 34, 56, rose_r=0, leaf_fill=OLIVE, side0=1, thorns=True),
       sprig(1010,788, 848,698, 24, 4, 34, 56, rose_r=0, leaf_fill=TERRA, side0=-1, thorns=True)]
    for cx,cy,s,flip in [(226,300,1.15,False),(196,520,1.0,True),(196,700,0.9,False),
                         (856,296,1.1,True),(886,514,0.95,False),(884,690,0.85,True)]:
        S.append(note(cx,cy,s,flip))
    return '\n'.join(S)


PRESETS = {"garland": garland, "notes": notes}


def main(argv=None):
    import argparse, sys
    ap = argparse.ArgumentParser(description="生成封面主题插画装饰层的 SVG")
    ap.add_argument("--preset", default="garland", help="构图预设：" + "、".join(PRESETS))
    ap.add_argument("--out", help="写到这里；不给就打到 stdout")
    ap.add_argument("--list", action="store_true", help="列出可用预设")
    a = ap.parse_args(argv)
    if a.list:
        for name in PRESETS: print(name)
        return 0
    if a.preset not in PRESETS:
        sys.exit(f"没有这个预设：{a.preset}（可选：{'、'.join(PRESETS)}）")
    svg = PRESETS[a.preset]()
    if a.out:
        import pathlib
        pathlib.Path(a.out).write_text(svg, encoding="utf-8")
        print(f"写入 {a.out}（{len(svg)} 字节）")
    else:
        print(svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
