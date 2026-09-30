# 一拍迹合 · Trip Journal

> 把抖音收藏夹里的旅行视频，走成一条**真的走得通**的路线。

粘贴收藏的旅行视频 → AI 听视频、认地点 → 结合你的「旅行人格」筛选 → 生成逐日路线，
并在编辑时实时告诉你：**赶不赶得上、花多少钱、那天下不下雨、该带什么**。

抖音精选内容重构黑客松参赛作品。

---

## 它解决什么问题

收藏了一堆「上海必去」，真到做计划时却是：地点散、顺序乱、不知道一天排几个合适、预算心里没数。
一拍迹合把这件事拆成 7 步，每一步都有「可行性」在兜底：

| 步骤 | 做什么 |
|---|---|
| 01 旅行人格 | 8 道题（单选 / 排序 / 滑块）→ 10 种旅行画像，决定节奏与偏好 |
| 02 行程规划 | 天数、出发日期、预算，**节奏**（悠闲 / 适中 / 紧凑）默认由人格推断 |
| 03 旅行搭子 | 同步搭子，对比人格**契合度**并给出同行建议；可一键借用 TA 分享的行程 |
| 04 精选视频 | 粘贴抖音链接（支持整段分享文案），并行转写 + 提取景点 |
| 05 地点筛选 | 地图 + 列表联动；缺坐标的地点自动用 POI 搜索补全；可手动添加 |
| 06 路线编辑 | 见下 |
| 07 导出分享 | 海报 PNG · PDF · 手机日历 `.ics` · 文字 · Markdown · **只读分享链接** |

### 路线编辑器（核心）

- **通勤估算**：相邻两站之间标出步行 / 地铁 / 打车与时长，来不及会标红并给出「差几分钟」
- **可行性预警**：时间冲突、当天太满、结束太晚、单日跨度过长、相邻两点过远、缺少餐饮
- **一键优化顺序**：在保持首站不变的前提下重排，使当天通勤最短（≤8 点为精确最优）
- **重排时间**：按「停留时长 + 通勤」重新排布，餐饮点落在饭点窗口
- **拖拽 / 键盘 / 触屏**都能改：拖拽排序、上下移、移到另一天、推荐池一键加入
- **换一个**：从推荐池挑同类型、最近的景点替换，原景点回到推荐池
- **实时预算**：餐饮 / 景点 / 交通分项，编辑即重算，超预算立刻提示
- **逐日天气**（填出发日期后）：雨天 / 高温给出调整建议
- **行前清单**：按天数、天气、人格、行程内容生成，勾选状态本地保存
- **撤销 / 重做**（Ctrl+Z）、**自动保存**（本机草稿 + 云端）、**我的行程**（打开 / 删除）

## 快速开始

```bash
./run.sh            # 创建 .venv、安装依赖、启动 → http://localhost:5000
```

不配置任何 Key 也能跑通全流程（Demo 模式：内置景点库 + 规则引擎排程）。
需要 AI 能力：

```bash
cp .env.example .env    # 填 LLM_API_KEY / MIMO_API_KEY / DOUBAO_API_KEY 等
```

高德地图 Key 通过环境变量 `AMAP_JS_KEY` / `AMAP_SECURITY_CODE` 配置（由 `/api/config` 下发，不再写死在 HTML 里）。
**地图不可用时**（无网络 / Key 失效）会自动降级为手账风「示意图」，核心流程不受影响。

## 架构

```
app.py                  应用工厂：路由注册、安全头(CSP)、统一 JSON 错误
backend/
  config.py             环境配置
  database.py           SQLite 建表 + 种子数据 + 旧版历史迁移
  routes/               auth · mbti · locations · itinerary · video · chat · buddy · trips(+weather)
  services/
    trips.py            行程仓储（增删改查 / 分享）
    llm_service.py      LLM 调用（可选）
frontend/               无构建步骤：原生 ES Modules + CSS
  index.html            外壳
  css/                  tokens → base → layout → components → pages/*
  js/
    main.js             启动
    core/               dom(h 辅助) · state · api · router(hash) · config · icons
    services/
      planner.js        ★ 行程引擎：纯函数，可在 Node 里单测
      map.js            高德 / 示意图 双实现，统一接口
      exporters.js      海报 · 打印 · ICS · Markdown
      trips.js auth.js itinerary.js persona-fit.js
    pages/              一页一个模块，路由按需加载
    ui/                 header · chat · modal · toast
tests/
  test_api.py           后端接口（23 项）
  js/planner.test.mjs   行程引擎（15 项）
```

### 设计取舍

- **无构建、无框架**：`h()` 辅助函数直接创建 DOM，所有动态文本走 `textContent`，天然免疫 XSS
  （旧版靠字符串拼接 + `innerHTML`，AI / 用户输入未转义）。
- **行程引擎与 UI 解耦**：`planner.js` 不碰 DOM，通勤 / 预警 / 优化 / 预算 / ICS / 清单都能脱离浏览器测试。
- **地图可降级**：`map.js` 的 `createMapView()` 失败即回退到 SVG 示意图，接口一致。
- **数据可迁移**：旧的 `users.travel_history` JSON 会在启动时一次性迁入 `trips` 表。

### 视觉

「旅行手账」：暖纸底 + 墨色 + 朱红印章，登机牌 / 票根 / 贴纸 / 邮戳。
衬线大标题（Noto Serif SC）+ 等宽小标签（DM Mono）；深浅色跟随系统，可手动切换；
尊重 `prefers-reduced-motion`；全部交互可键盘操作。
人格插画 / 贴纸已转 WebP（46 MB → 1.3 MB）。

## 部署

仓库自带 `Dockerfile`（gunicorn）和 `render.yaml`。以 Render 为例：**New → Blueprint → 选择本仓库**，
在控制台按需填写 `LLM_API_KEY` / `AMAP_JS_KEY` 等（全部留空则为 Demo 模式）。
任何支持 Docker 的平台（Fly.io / Railway / 自有服务器）同理：

```bash
docker build -t yipaijihe .
docker run -p 8080:8080 -v yipaijihe-data:/data -e AMAP_JS_KEY=... yipaijihe
```

SQLite 位于 `/data`，请挂载持久卷；视频分析是 1–2 分钟的长请求，网关超时需 ≥ 300 s。

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 后端
node --test "tests/js/*.test.mjs"        # 行程引擎
```

`tests/integration/` 需要真实的 LLM / ASR Key，手动运行：`python tests/integration/test_full_pipeline.py`。

## 安全说明

- 密码使用 scrypt（旧的 sha256 记录登录后自动升级）；接口不再回显异常细节
- 搭子同步 / 视频分析需要登录；**只有用户主动开启分享的行程**才对搭子可见
- 视频链接仅允许抖音系域名，并限制单次数量（防 SSRF / 滥用）
- 分享链接为不可猜测的随机 token，可随时关闭
- 响应带 CSP / `nosniff` / `Referrer-Policy`

## 已知限制

- 目前仅内置上海景点库
- 通勤为直线距离 ×1.3 的估算（地图可用时，路线绘制使用高德真实路网）
- 天气来自 Open-Meteo，仅覆盖未来 16 天
- 价格为档位估价，不含住宿与大交通

## License

见 [LICENSE](LICENSE)。
