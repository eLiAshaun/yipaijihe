# 一拍迹合 — 修改日志

> 本文档记录每次对项目的改动细节，供协作者和 AI Agent 快速理解变更内容。
> 阅读本文档后，应能直接定位到需要修改的文件和代码位置。

---

## 2026-06-07 | 图文海报功能修复 & 导出分享页优化

### 背景

导出分享页（Step 7）有三种导出方式：PDF、图文海报、详细文档。其中**图文海报功能完全不可用**——代码中调用了 `html2canvas` 库来将 HTML 截图为 PNG 图片，但 `index.html` 中从未引入该库的 CDN，导致始终走降级路径（下载 HTML 文件而非图片）。此外，海报模板质量低（纯文字堆叠），分享链接功能是假的（无后端存储），复制链接用了废弃 API。

### 改动概览

| # | 改动 | 文件 | 类型 |
|---|------|------|------|
| 1 | 引入 html2canvas CDN | `frontend/index.html` | 新增 |
| 2 | 重写 `exportAsImage()` 截图函数 | `frontend/js/app.js` | 重写 |
| 3 | 重写 `buildPosterHTML()` 海报模板 | `frontend/js/app.js` | 重写 |
| 4 | 新增 `getCategoryEmoji()` 辅助函数 | `frontend/js/app.js` | 新增 |
| 5 | 新增导出卡片 loading 动画样式 | `frontend/css/style.css` | 新增 |
| 6 | 移除假的分享链接功能（HTML + JS + CSS） | 三个文件均有 | 删除 |

---

### 改动 1：引入 html2canvas CDN

**文件**：`frontend/index.html`，第 14-16 行

**做了什么**：在高德地图 script 标签之后，新增一行 html2canvas 的 CDN 引用。

**改动前**（第 14-15 行）：
```html
  <script src="https://webapi.amap.com/maps?v=2.0&key=f82fd3115909f6cda7b1378ff7b2e3cb"></script>
</head>
```

**改动后**（第 14-16 行）：
```html
  <script src="https://webapi.amap.com/maps?v=2.0&key=f82fd3115909f6cda7b1378ff7b2e3cb"></script>
  <!-- html2canvas: 图文海报截图 -->
  <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
</head>
```

**原因**：原代码 `exportAsImage()` 中检查 `typeof html2canvas !== "undefined"`，但从未加载该库，导致永远走降级路径。

---

### 改动 2：重写 `exportAsImage()` 截图函数

**文件**：`frontend/js/app.js`，第 2279-2332 行

**做了什么**：将原来的同步 `.then()` 链式调用改为 `async/await`，增加 loading 状态、错误处理、finally 清理。

**原函数逻辑**（已删除）：
- 创建临时 div → `position:fixed; left:-9999px` 移出视口
- 检查 html2canvas 是否可用 → 可用则 `.then()` 截图下载 PNG
- 不可用则降级下载 HTML 文件
- **无错误处理**，**无 loading 状态**

**新函数逻辑**：
1. 检查 `state.itinerary` 是否存在
2. 给导出卡片（`.export-card:nth-child(2)`）添加 `loading` CSS 类（半透明 + 呼吸动画）
3. 创建临时 div，设置 `position:fixed; left:-9999px; z-index:-1; pointer-events:none`
4. 调用 `buildPosterHTML()` 填充内容，append 到 `document.body`
5. `try`：调用 `html2canvas(el, { scale: 2, useCORS: true, allowTaint: true, backgroundColor: null, logging: false })` → 生成 canvas → `toDataURL("image/png")` → 创建 `<a>` 标签触发下载
6. `catch`：降级下载 HTML 文件（完整 `<!DOCTYPE html>` 包装），toast 提示失败
7. `finally`：移除临时 div，移除 loading CSS 类

**关键参数说明**：
- `scale: 2`：生成 2 倍分辨率图片，适合 Retina 屏和手机分享
- `useCORS: true` + `allowTaint: true`：允许加载跨域图片（高德静态地图）
- `backgroundColor: null`：不覆盖海报自身的背景色

---

### 改动 3：重写 `buildPosterHTML()` 海报模板

**文件**：`frontend/js/app.js`，第 2379-2528 行

**做了什么**：将原来的 420px 纯文字堆叠模板，替换为 750px 卡片式海报布局。

**原模板**（已删除）：
- 420px 宽，橙色渐变背景
- 只有标题 + 摘要 + 每天的地点名称列表
- 无地图、无人格信息、无信息条、无小贴士区域

**新模板结构**（全部内联样式，确保 html2canvas 能正确渲染）：

```
┌─────────────────────────────────┐
│  渐变头部（#FF6B35 → #E85D75）    │  ✈️ 一拍迹合 + 行程摘要 + 旅行人格徽章
├─────────────────────────────────┤
│  信息条（#FFF8F0 背景）           │  📍目的地 | 📅天数 | 💰预算 | 📍景点数
├─────────────────────────────────┤
│  路线地图（高德静态图 API）        │  750×300px，带编号标记点，自动居中
├─────────────────────────────────┤
│  🗓️ 行程安排                     │  按天分组，每天不同颜色圆形序号
│    Day 1 (橙色)                  │    🕐时间 + 💡备注 + 分类emoji
│      📍 景点名                    │
│      🍜 美食名                    │
│    Day 2 (玫红)                  │
│      ...                        │
├─────────────────────────────────┤
│  💡 旅行小贴士（橙色卡片）         │  itin.tips[] 列表
├─────────────────────────────────┤
│  底部水印（#f8f8f8）             │  生成日期 + yipaijihe.com
└─────────────────────────────────┘
```

**数据来源**：
- `state.tripConfig.city` / `.days` / `.budget` → 信息条
- `state.mbtiResult.personality.name` / `.emoji` / `state.mbtiResult.mbti` → 人格徽章
- `state.itinerary.days[].items[].location.lat/lng` → 高德静态图 markers
- `state.itinerary.days[].items[].time` / `.location.name` / `.notes` / `.location.category` → 时间线
- `state.itinerary.tips[]` → 小贴士

**高德静态图 API 调用**：
```
https://restapi.amap.com/v3/staticmap?location={中心经度},{中心纬度}&zoom=12&size=710*280&markers=large,0xFF6B35,{序号}:{经度},{纬度}|...&key={高德key}&scale=2
```
- 自动计算所有景点的中心经纬度
- 最多取前 20 个景点生成标记点
- 如果没有经纬度数据，地图区域自动隐藏（`onerror="this.style.display='none'"`）

**天数配色方案**：
```javascript
const dayColors = ["#FF6B35", "#E85D75", "#7B68EE", "#20B2AA", "#FF8C42", "#6C5CE7", "#00B894"];
```

---

### 改动 4：新增 `getCategoryEmoji()` 辅助函数

**文件**：`frontend/js/app.js`，第 2531-2549 行

**做了什么**：根据地点分类字符串返回对应的 emoji 图标，用于海报时间线中每个景点的图标展示。

**函数签名**：`function getCategoryEmoji(category: string): string`

**内置映射**：
```javascript
{
  景点: "🏛️", 美食: "🍜", 餐厅: "🍽️", 咖啡: "☕", 购物: "🛍️",
  酒店: "🏨", 交通: "🚇", 公园: "🌳", 寺庙: "🛕", 海滩: "🏖️",
  夜景: "🌃", 博物馆: "🏛️", 商圈: "🏬", 文创: "🎨", 拍照: "📸",
  甜品: "🍰", 酒吧: "🍸", 书店: "📚", 市场: "🛒", 地标: "🗼"
}
```

**匹配逻辑**：遍历 map 的 key，用 `category.includes(key)` 模糊匹配。无匹配时返回 "📍"。

---

### 改动 5：新增导出卡片 loading 动画样式

**文件**：`frontend/css/style.css`，第 3000-3011 行

**做了什么**：在 `.export-card:hover` 样式之后，新增 `.export-card.loading` 状态样式。

**新增 CSS**：
```css
.export-card.loading {
  pointer-events: none;    /* 防止重复点击 */
  opacity: 0.6;            /* 半透明表示不可交互 */
}

.export-card.loading .export-card-icon {
  animation: pulse-spin 1s ease-in-out infinite;  /* icon 呼吸旋转动画 */
}

@keyframes pulse-spin {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15) rotate(5deg); }
}
```

**触发时机**：`exportAsImage()` 函数开头给图文海报卡片（`.export-card:nth-child(2)`）加 `loading` 类，`finally` 块中移除。

---

### 改动 6：移除假的分享链接功能

**做了什么**：删除整个分享链接功能（生成假链接 + 复制到剪贴板），因为该功能无后端支持，生成的链接打开是 404。

**涉及文件和位置**：

#### 6a. `frontend/index.html` — 删除 HTML 区块

**删除位置**：原第 366-372 行（在 `.export-options` 和 `.export-footer` 之间）

**删除内容**：
```html
<div class="export-share">
  <h3>分享给朋友</h3>
  <div class="share-link-box">
    <input type="text" id="share-link" readonly placeholder="生成中...">
    <button class="btn-copy" onclick="copyShareLink()">复制链接</button>
  </div>
</div>
```

#### 6b. `frontend/js/app.js` — 删除两个函数 + 一个调用

**删除函数 1**：`generateShareLink()`（原第 2575-2579 行）
```javascript
function generateShareLink() {
  const linkInput = document.getElementById("share-link");
  const shareId = Math.random().toString(36).substring(2, 10);
  linkInput.value = `${window.location.origin}/share/${shareId}`;
}
```

**删除函数 2**：`copyShareLink()`（原第 2581-2596 行）
```javascript
async function copyShareLink() {
  const linkInput = document.getElementById("share-link");
  const text = linkInput.value;
  if (!text) { showToast("请先生成分享链接", true); return; }
  try {
    await navigator.clipboard.writeText(text);
    showToast("链接已复制到剪贴板！");
  } catch {
    linkInput.select();
    document.execCommand("copy");
    showToast("链接已复制到剪贴板！");
  }
}
```

**删除调用**：`initButtons()` 中的 `generateShareLink()` 调用（原第 3972 行）

**改动前**：
```javascript
document.getElementById("btn-to-export").addEventListener("click", () => {
  generateShareLink();
  showPage("export");
});
```

**改动后**：
```javascript
document.getElementById("btn-to-export").addEventListener("click", () => {
  showPage("export");
});
```

#### 6c. `frontend/css/style.css` — 删除相关样式

**删除位置**：原 `.export-card:hover` 和 `.export-footer` 之间

**删除内容**：
```css
.export-share { max-width: 560px; margin: 0 auto 40px; text-align: center; }
.export-share h3 { font-size: 18px; margin-bottom: 16px; }
.share-link-box { display: flex; gap: 12px; }
.share-link-box input { flex: 1; padding: 12px 16px; border: 2px solid var(--border); ... }
.btn-copy { padding: 12px 24px; background: var(--accent); color: white; ... }
.btn-copy:hover { background: var(--accent-dark); }
```

---

### 已知限制 & 后续可优化

1. **高德静态图跨域**：html2canvas 截图时，地图图片可能因跨域策略显示为空白。已设置 `useCORS: true` + `allowTaint: true` + `crossorigin="anonymous"`，但高德静态图 API 的跨域 Header 不一定支持。如遇此问题，可考虑后端代理图片或使用 Canvas 手动绘制路线。

2. **长行程海报**：如果行程天数很多（>5天）或每天景点很多，海报会非常长。可考虑加截断逻辑（如最多展示 3 天 + "更多请查看完整攻略"提示）。

3. **分享链接**：如需恢复分享功能，需要后端增加存储接口（保存行程数据到数据库，返回 share_id），以及前端增加一个 `/share/:id` 页面来读取并展示共享的行程。

4. **PDF 导出**：当前是 `window.open` + `win.print()` 浏览器打印方案，体验一般。可考虑引入 `jsPDF` 或后端生成 PDF。

---

### 项目文件结构参考

```
黑客松/
├── frontend/
│   ├── index.html          ← 主页面（单页应用）
│   ├── js/
│   │   └── app.js          ← 全部前端逻辑（~4000 行）
│   └── css/
│       └── style.css       ← 全部样式（~3000 行）
├── backend/
│   ├── routes/
│   │   ├── auth.py         ← 登录注册
│   │   ├── buddy.py        ← 搭子同步
│   │   ├── chat.py         ← AI 聊天
│   │   ├── itinerary.py    ← 行程生成/保存
│   │   ├── locations.py    ← 景点数据
│   │   ├── mbti.py         ← 旅行人格测试
│   │   └── video.py        ← 视频分析
│   ├── services/
│   │   ├── llm_service.py  ← LLM 调用
│   │   └── video_processor.py
│   ├── data/
│   │   ├── mbti_data.py
│   │   └── shanghai_locations.py
│   ├── config.py
│   └── database.py
├── app.py                  ← Flask 入口
└── log.md                  ← 本文件
```

### 前端应用流程

```
Step 1: 登录/注册 → Step 2: 旅行人格测试 → Step 3: 行程规划
→ Step 4: 旅行搭子 → Step 5: 精选视频 → Step 6: 地图预览
→ Step 7: 路线生成 → Step 8: 导出分享
```

### 关键状态对象

```javascript
const state = {
  tripConfig: { city, days, budget },    // 行程配置
  mbtiResult: { personality, mbti },     // 旅行人格结果
  itinerary: { summary, days[], tips[] }, // 行程数据（核心）
  // days[].items[].{ time, activity, notes, location: { name, lat, lng, category } }
};
```
