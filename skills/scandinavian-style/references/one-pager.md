# 密集单页（one-pager）

标准内容页只讲一件事，正文上限 11.93 cm，放不下就拆页。**密集单页是这条规则的唯一例外**：
把一整个主题——一本书、一次调研、一个系统——的全部要点压进一页，靠结构与层级维持可读性。

只在两种情况下用它：

1. 用户明确要求「一页纸」「one-pager」「保证内容都在里面」；
2. 用户抱怨「篇幅太长了」，而内容本身不该砍——他要的是密度，不是删减。

其余情况回退到标准内容页。**默认不缩字号**；缩字号是用户授权后才做的事。

## 与标准内容页的差异

| | 标准内容页 | 密集单页 |
| --- | --- | --- |
| 分栏 | 双栏（纵向分割线 21.05 cm） | 三栏（11.458 / 22.441 cm） |
| 内容带 | 4.40 → 16.33 cm | 4.40 → **17.00 cm** |
| 安静带 | 1.17 cm | 0.50 cm |
| 正文字号 | 16 / 14 / 12 / 11 pt | **10 / 9 / 8.5 / 7.6 pt** |
| 正文高度上限 | 11.93 cm | 12.60 cm |
| 收尾 | 自然结束 | 三栏必须齐平 |

分割线（1.55 / 17.50 cm，全出血 0.25pt）与页脚四元素**一条都不放松**。密度靠字号和分栏去换，
不许动骨架。

## 三栏坐标

内容区仍是 0.99 → 32.89 cm（31.90 cm 宽）。三栏等宽，沟槽 1.05 cm：

| 栏 | X | 宽 |
| --- | --- | --- |
| 第一栏 | 0.99 cm | 9.933 cm |
| 第二栏 | 11.973 cm | 9.933 cm |
| 第三栏 | 22.956 cm | 9.933 cm |

纵向细分隔线落在沟槽中心：`x = 11.458` 与 `x = 22.441`，**只跨内容区**（y 4.40 → 17.00），
不要像双栏那样从 1.56 cm 拉到 17.50 cm——三栏时那两条线会穿过副标题。

栏宽 9.933 cm，中文每行 30–37 字，仍在可读区间内。**不要为了多塞内容做成四栏**：栏宽掉到
7 cm 以下，中文会大量出现孤字和断词，读起来比多一页更糟。

## 字号下限

允许在标准层级上再降一档，但不能再低：

| 用途 | 字号 | `calc()` 系数 | 行高 |
| --- | --- | --- | --- |
| 标题 | 32 pt | `1.1289` | 1.06 |
| 眉标 · 页脚 | 9 pt | `0.3175` | 1.1 |
| 导语 lede | 10 pt | `0.3457` | 1.48 |
| 小节标题 | 9 pt | `0.3175` | 1.28 |
| 正文 | 8.5 pt | `0.2823` | 1.50 |
| 列表／次要正文 | 7.6 pt | `0.2682` | 1.46 |
| 栏目标签 · 出处注 | 7.2 pt | `0.2540` | 1.2 / 1.44 |

- **标题与页脚不参与降级**，它们是骨架。
- 正文到 8.5 pt 为止。再小打印后没法读，用户会看出你在逃避取舍。
- 层级仍要 ≥ 4 档。密度越高越依赖层级，密集不等于扁平。

## 收尾齐平

三栏都设 `justify-content:space-between`，让每栏最后一个元素贴住 y = 17.00 cm，形成一条干净的底边。

代价是栏内间距被撑开。**某一栏富余超过 2.5 cm 就是分配不均**——把一两个小节挪到富余最小的那栏，
而不是让间距继续变大。

## 必备构件

| 构件 | 类名 | 作用 |
| --- | --- | --- |
| 眉标 | `.kicker-l` / `.kicker-r` | 左：文件性质；右：主体＋年份 |
| 导语 | `.lede` | 全页最大字号，2–3 行说清「这页在讲什么」 |
| 栏目标签 | `.lab` | 字距 `.16em` 的小标签，不靠加粗 |
| 小节标题 | `.h` | 500 字重，只用于建立层级 |
| 破折号列表 | `.li` | 并列条目（人／流派／要点），每条要短 |
| 比例数据条 | `.bar` | 见下节 |
| 出处注 | `.kv` | 灰阶 03 最小字号，**放在被注释内容同一栏的末尾** |

副标题可以写到两行，但必须完全落在 y = 4.40 cm 以上，不能压进内容区。

## 比例数据条

要在极小高度里表达占比，用一条 `flex` 数据条，而不是画图：

```css
.bar{display:flex;height:calc(var(--u)*0.14);margin:calc(var(--u)*0.12) 0 calc(var(--u)*0.18);}
.bar i{display:block;background:var(--grey-05);}
.bar i.core{background:var(--signal);}
.bar i+i{margin-left:1px;}
```

```html
<div class="bar" role="img" aria-label="共 13 篇的篇幅占比，核心部分占 42%">
  <i style="flex:13 1 0"></i><i style="flex:9 1 0"></i>
  <i class="core" style="flex:21 1 0"></i>
  <!-- 其余段同理 -->
</div>
```

- `flex` 数值就是原始量（页数、字数、条目数），不必换算成百分比。
- **只给需要指出的区段上强调色**，其余留灰。整条染色等于没有强调。
- 必须有 `aria-label` 说明它表达什么——颜色不是唯一的信息载体。

## 验证：必须实测，不能靠看

密集单页的容错只有几毫米，肉眼不可靠，而 `overflow:hidden` 会**静默裁掉**溢出。交付前用探针
量每栏富余：

```bash
python3 - <<'PY'
src=open('page.html',encoding='utf-8').read()   # <- 换成你的交付文件
probe = """
<script>
window.addEventListener('load',function(){
  var r=[];var s=document.querySelector('.slide').getBoundingClientRect();var u=s.width/33.867;
  document.querySelectorAll('.col').forEach(function(c,i){
    var box=c.getBoundingClientRect(), inner=0;
    Array.prototype.forEach.call(c.children,function(el){inner+=el.getBoundingClientRect().height;});
    r.push('col'+(i+1)+' headroom='+((box.height-inner)/u).toFixed(2)+'cm');
  });
  document.documentElement.innerHTML='<body><pre id=out>'+r.join(' | ')+'</pre></body>';
});
</script>
"""
open('/tmp/measure.html','w',encoding='utf-8').write(src.replace('</body>',probe+'</body>'))
PY
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --virtual-time-budget=3000 --window-size=1280,720 --dump-dom file:///tmp/measure.html \
  2>/dev/null | sed -n '/<pre/,/<\/pre>/p'
```

判读：

- 每栏富余 **≥ 0.5 cm** 才算通过；归零或负数就是溢出。
- 富余普遍大于 2.5 cm → 分配不均，回去调栏。
- 探针会替换掉 `document.documentElement`，所以**永远在副本上跑**（上面的脚本写 `/tmp/measure.html`），
  不要指向交付文件。

然后照 [`web-artifacts.md`](web-artifacts.md) 做双引擎渲染确认（WebKit + Chromium）。两个引擎的字体
回退不同，中文换行点会差 1–3%——这正是必须留 0.5 cm 富余的原因。

## 交付前检查清单

在标准检查清单之外，密集单页再确认：

- [ ] 用户确实要求了一页纸／密度，而不是我自作主张缩了字号
- [ ] 三栏坐标正确，两条纵向分割线只在内容区内
- [ ] 正文不小于 8.5 pt，标题仍是 32 pt，页脚仍是 9 pt
- [ ] 字号层级仍 ≥ 4 档，没有退化成一大片同号文本
- [ ] 三栏收尾齐平，每栏富余都 ≥ 0.5 cm
- [ ] 数据条只给关键区段上色，且有 `aria-label`
- [ ] 出处与可信度注没有被挤掉
- [ ] 上下分割线与页脚四元素完全符合标准页规范
