# 单页 HTML 实现

把版式网格落到 HTML 上时，有三个坑会让页面看起来"差不多但不对"。
`assets/slide.html` 已经处理好这些，直接改内容即可。

## 1. 坐标随容器缩放

网格坐标都是厘米。如果写死 `px`，页面在窄窗口里会溢出；如果写死 `cm`，
浏览器按 96 dpi 换算，页面不会跟着窗口缩放。

**做法**：把幻灯片设成容器，用 `cqw`（容器宽度的 1%）定义"1 厘米"，所有坐标从它推导。

```css
.slide {
  container-type: inline-size;
  position: relative;
  width: min(100%, 1280px);   /* 1280px = 33.867cm @96dpi */
  aspect-ratio: 16 / 9;
  overflow: hidden;
  --u: 2.95273cqw;            /* 1cm = 100 / 33.867 cqw */
}
.slide-title {
  position: absolute;
  left: calc(var(--u) * 0.99);
  top:  calc(var(--u) * 2.03);
  font-size: calc(var(--u) * 1.1289);   /* 32pt */
}
```

字号同理：`1pt = 0.0352778cm`，所以 `32pt` 就是 `calc(var(--u) * 32 * 0.0352778)`。

注意 `cqw` 只在容器**内部**的元素上生效——容器自己不能用。所以分割线、页脚都必须是
`.slide` 的子元素。

容器查询单位在 Chrome 105+、Safari 16+、Firefox 110+ 都支持，可以放心用。

## 2. 分割线要在屏幕上看得见

规范要求 0.25pt（约 0.33px），在屏幕上可能直接消失。用一个带下限的值：

```css
--hairline: max(1px, calc(var(--u) * 0.00882));   /* 0.25pt */
```

打印时再回到精确值，保证和 PPT/PDF 规范一致：

```css
@media print { .slide { --hairline: 0.25pt; } }
```

## 3. 打印／导出成恰好一页

```css
@page { size: 33.867cm 19.05cm; margin: 0; }
@media print {
  body { background: var(--white); }
  .stage { display: block; min-height: 0; padding: 0; }
  .slide { width: 33.867cm; height: 19.05cm; border: 0; box-shadow: none; }
}
```

设置页边距为 0、页面尺寸等于画布，⌘P → 存为 PDF 就是一页标准 16:9。
如果输出有白边，检查浏览器打印对话框里"边距"是否被设回了默认值。

## 4. 不要依赖 JavaScript

滚动渐显、入场动画、"进入视口才显示"这类效果在另一种渲染路径下会失效：

- 打印／导出 PDF 时
- 生成缩略图或截图时
- 禁用 JS 时
- 邮件／预览客户端里

**正文必须在不运行 JS 的情况下完整可见。** 动画可以用，但初始状态必须是可见的
（不要用 `animation-fill-mode: backwards` 把元素先藏起来）。

## 5. 交付前验证渲染

版式很脆，靠读代码看不出问题。至少做两步：

```bash
# 静态检查：CSS 括号配平、HTML 标签闭合
# 渲染检查：生成缩略图后用肉眼和像素确认
qlmanage -t -s 1600 -o /tmp/shot page.html
```

然后用脚本量出关键位置是否落在规范值上（幻灯片宽高比、两条分割线的 y、纵向分割线 x）。
误差应在 0.05cm 以内。示例：

```python
# 找出白色画布包围盒，把像素换算成厘米，再核对分割线位置
cm = (x1 - x0) / 33.867
print("top divider", (y - y0) / cm, "cm (spec 1.55)")
```

如果环境里同时有 WebKit 和 Chromium，两边都渲染一次。
容器查询单位、字体回退、`max()` 在不同引擎下的表现可能不同。

## 6. 文件约定

- 单文件、零外部依赖、离线可用。字体用系统栈，不要引外部 CSS 或字体文件。
- 中文字体放在拉丁字体**之后**，让西文用系统无衬线、中文正确回退。
- 页面 `<title>` 用真实标题，方便导出 PDF 时得到正确的文件名。
