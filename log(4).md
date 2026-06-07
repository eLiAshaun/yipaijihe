# 一拍迹合 — 修改日志

> 本文档记录每次对项目的改动细节，供协作者和 AI Agent 快速理解变更内容。
> 阅读本文档后，应能直接定位到需要修改的文件和代码位置。

---

## 2026-06-07 | 旅行人格 6 人格收口 & 最近原型匹配重写

### 背景

旅行人格测试原本使用 4 个二元维度直接累加并拼出四字母编码：

- **di**：记录 D / 沉浸 I
- **rl**：精致 R / 本地 L
- **ps**：计划 P / 灵感 S
- **cd**：覆盖 C / 深度 T

在本轮收口中，旅行人格从原 10 人格删并为最终 6 人格：

| 人格 | 意图维度 |
|---|---|
| 摄影师 | D·R·P·T |
| 特种兵 | D·R·P·C |
| 生活家 | I·L·S·T |
| 架构师 | I·R·P·T |
| 悠享家 | I·R·S·C |
| 美食家 | I·L·S·C |

原旧算法的问题是：  
只要每一维用硬判定，就会出现部分人格“意图维度”和“实际算出结果”不一致。

典型问题：

- **悠享家**目标是 `IRSC`，但旧算法容易被算成记录 / 计划型；
- **美食家**目标是 `ILSC`，但旧算法容易被算成生活家 `ILST`；
- 根因是当前题目里的 `cover` 覆盖倾向经常和 `record / plan / refined` 绑定，导致“沉浸 + 灵感 + 覆盖”这种人格不稳定。

本次为了尽快收口，不再继续纠结每一维是否严格命中，而是改为：

> **答案 → 连续维度分 → 与 6 条人格标准配方计算距离 → 返回最近人格。**

即：  
**按定稿配方答题，必须测出对应人格。**

---

### 改动概览

| # | 改动 | 文件 | 类型 |
|---|---|---|---|
| 1 | 更新最终 6 人格配方 | `figure/人格配方表.md` | 修改 |
| 2 | 将 `calculate_mbti()` 改为最近原型匹配 | `backend/data/mbti_data.py` | 重写 |
| 3 | 新增 6 条人格标准答案原型 | `backend/data/mbti_data.py` | 新增 |
| 4 | 精简人格映射，只保留最终 6 人格 | `backend/data/mbti_data.py` | 修改 |
| 5 | 保留 `get_personality()` / `get_dimension_scores()` 接口兼容 | `backend/data/mbti_data.py` | 修改 |
| 6 | 同步人格测试接口返回结构 | `backend/routes/mbti.py` | 兼容 |
| 7 | 新增 6 条配方自动化测试 | `tests/test_mbti_recipes.py` | 新增 |

---

### 改动 1：更新最终 6 人格配方

**文件**：`figure/人格配方表.md`

**做了什么**：

将最终人格收口为 6 个：

```text
摄影师 DRPT
特种兵 DRPC
生活家 ILST
架构师 IRPT
悠享家 IRSC
美食家 ILSC
````

最终配方如下：

| 人格  | 意图维度    | Q1      | Q2 | Q3 | Q4 | Q5      | Q6 | Q7 | Q8        |
| --- | ------- | ------- | -- | -- | -- | ------- | -- | -- | --------- |
| 摄影师 | D·R·P·T | a→b→d→c | 左  | 左  | d  | a→b→c→d | b  | b  | a→b→d→e→c |
| 特种兵 | D·R·P·C | b→c→a→d | 左  | 左  | a  | a→c→b→d | a  | a  | a→e→b→c→d |
| 生活家 | I·L·S·T | d→a→c→b | 右  | 右  | b  | b→d→a→c | d  | c  | b→c→d→a→e |
| 架构师 | I·R·P·T | a→b→c→d | 右  | 左  | b  | b→c→d→a | b  | b  | d→a→b→c→e |
| 悠享家 | I·R·S·C | d→b→a→c | 右  | 左  | d  | b→a→c→d | b  | c  | a→c→d→e→b |
| 美食家 | I·L·S·C | c→d→a→b | 右  | 右  | d  | d→b→a→c | d  | c  | c→b→d→e→a |

**同步决策**：

* 删除 **知音者**；
* 删除 **践行者**；
* 合并 **逍遥客 / 漫步客 / 生活家** 为 **生活家**；
* 不新增社交维度；
* 不再保留旧 10 人格。

---

### 改动 2：将 `calculate_mbti()` 改为最近原型匹配

**文件**：`backend/data/mbti_data.py`

**原逻辑**：

```text
用户答案
→ 各维度累计分
→ 每个维度二选一
→ 拼出四字母 code
→ 通过 MBTI_TO_PERSONA 找人格
```

**新逻辑**：

```text
用户答案
→ 计算连续维度向量
→ 和 6 条标准人格配方的原型向量计算距离
→ 返回距离最近的人格 code
```

**核心变化**：

`calculate_mbti()` 函数名保持不变，避免影响前端和路由。

但内部逻辑改为：

```python
def calculate_mbti(answers: dict) -> str:
    """
    根据用户答案计算旅行人格 code。

    注意：
    这里不再使用旧的四维硬判定拼码，
    而是使用 6 人格标准配方的最近原型匹配。
    """
    return match_persona_by_prototype(answers)
```

**原因**：

旧的硬判定适合 4 个维度完全正交的情况，但当前题目选项存在耦合。
最近原型匹配更适合现在的 6 人格收口目标：
**只要整体答题模式接近某个人格，就返回该人格。**

---

### 改动 3：新增 6 条人格标准答案原型

**文件**：`backend/data/mbti_data.py`

**新增常量**：`PERSONA_RECIPES`

```python
PERSONA_RECIPES = {
    "photographer": {
        "name": "摄影师",
        "code": "DRPT",
        "answers": {
            "q1": ["a", "b", "d", "c"],
            "q2": 0,
            "q3": 0,
            "q4": "d",
            "q5": ["a", "b", "c", "d"],
            "q6": "b",
            "q7": "b",
            "q8": ["a", "b", "d", "e", "c"],
        },
    },
    "commando": {
        "name": "特种兵",
        "code": "DRPC",
        "answers": {
            "q1": ["b", "c", "a", "d"],
            "q2": 0,
            "q3": 0,
            "q4": "a",
            "q5": ["a", "c", "b", "d"],
            "q6": "a",
            "q7": "a",
            "q8": ["a", "e", "b", "c", "d"],
        },
    },
    "life_artist": {
        "name": "生活家",
        "code": "ILST",
        "answers": {
            "q1": ["d", "a", "c", "b"],
            "q2": 100,
            "q3": 100,
            "q4": "b",
            "q5": ["b", "d", "a", "c"],
            "q6": "d",
            "q7": "c",
            "q8": ["b", "c", "d", "a", "e"],
        },
    },
    "architect": {
        "name": "架构师",
        "code": "IRPT",
        "answers": {
            "q1": ["a", "b", "c", "d"],
            "q2": 100,
            "q3": 0,
            "q4": "b",
            "q5": ["b", "c", "d", "a"],
            "q6": "b",
            "q7": "b",
            "q8": ["d", "a", "b", "c", "e"],
        },
    },
    "enjoyer": {
        "name": "悠享家",
        "code": "IRSC",
        "answers": {
            "q1": ["d", "b", "a", "c"],
            "q2": 100,
            "q3": 0,
            "q4": "d",
            "q5": ["b", "a", "c", "d"],
            "q6": "b",
            "q7": "c",
            "q8": ["a", "c", "d", "e", "b"],
        },
    },
    "foodie": {
        "name": "美食家",
        "code": "ILSC",
        "answers": {
            "q1": ["c", "d", "a", "b"],
            "q2": 100,
            "q3": 100,
            "q4": "d",
            "q5": ["d", "b", "a", "c"],
            "q6": "d",
            "q7": "c",
            "q8": ["c", "b", "d", "e", "a"],
        },
    },
}
```

**说明**：

* `q2` / `q3` 滑块：

  * 左 = `0`
  * 右 = `100`
* 排序题统一使用数组，从“最想 / 最怕”到“最不想 / 最不怕”。
* 这 6 条配方是后续人格测试的唯一权威原型。

---

### 改动 4：新增向量计算与距离匹配函数

**文件**：`backend/data/mbti_data.py`

**新增函数 1**：`build_answer_vector()`

```python
def build_answer_vector(answers: dict) -> dict:
    """
    将用户答案转换为连续维度向量。

    输出 tag：
    - record / immerse
    - refined / local
    - plan / spontaneous
    - cover / deep
    """
```

**新增函数 2**：`build_persona_prototypes()`

```python
def build_persona_prototypes() -> dict:
    """
    根据 PERSONA_RECIPES 中的标准答案，
    预计算 6 个人格的原型向量。
    """
```

**新增函数 3**：`vector_distance()`

```python
def vector_distance(user_vector: dict, proto_vector: dict) -> float:
    """
    计算用户向量和人格原型向量之间的距离。

    当前使用欧氏距离。
    后续如果需要增强某些维度区分，可以在这里加权。
    """
```

**新增函数 4**：`match_persona_by_prototype()`

```python
def match_persona_by_prototype(answers: dict) -> str:
    """
    返回距离最近的人格 code：
    DRPT / DRPC / ILST / IRPT / IRSC / ILSC
    """
```

**匹配逻辑**：

```text
user_vector = build_answer_vector(answers)
prototypes = build_persona_prototypes()

遍历 6 个人格原型：
    distance = vector_distance(user_vector, prototype_vector)

返回 distance 最小的人格 code
```

---

### 改动 5：精简人格映射，只保留最终 6 人格

**文件**：`backend/data/mbti_data.py`

**做了什么**：

删除或废弃旧的 10 人格配置，只保留：

```python
PERSONALITY_TYPES = {
    "photographer": {...},
    "commando": {...},
    "life_artist": {...},
    "architect": {...},
    "enjoyer": {...},
    "foodie": {...},
}
```

新增或替换 code 映射：

```python
CODE_TO_PERSONA = {
    "DRPT": "photographer",
    "DRPC": "commando",
    "ILST": "life_artist",
    "IRPT": "architect",
    "IRSC": "enjoyer",
    "ILSC": "foodie",
}
```

`get_personality()` 改为：

```python
def get_personality(mbti: str) -> dict:
    persona_key = CODE_TO_PERSONA.get(mbti, "life_artist")
    return PERSONALITY_TYPES.get(persona_key, PERSONALITY_TYPES["life_artist"])
```

**原因**：

当前产品只保留 6 人格。
旧的 `MBTI_TO_PERSONA` 16 编码映射会继续制造歧义，因此不再作为主逻辑使用。

---

### 改动 6：保留 `get_dimension_scores()` 接口兼容

**文件**：`backend/data/mbti_data.py`

**做了什么**：

`get_dimension_scores()` 继续保留，用于前端展示和 debug，但它不再决定最终人格。

输出仍保留四维倾向：

```python
{
    "di": {
        "left": "record",
        "right": "immerse",
        "left_score": 12,
        "right_score": 18,
        "winner": "I"
    },
    "rl": {
        "left": "refined",
        "right": "local",
        "left_score": 10,
        "right_score": 14,
        "winner": "L"
    },
    "ps": {
        "left": "plan",
        "right": "spontaneous",
        "left_score": 8,
        "right_score": 11,
        "winner": "S"
    },
    "cd": {
        "left": "cover",
        "right": "deep",
        "left_score": 9,
        "right_score": 13,
        "winner": "T"
    }
}
```

注意：

* `winner` 只代表单维展示；
* 最终人格由 `calculate_mbti()` 的最近原型匹配决定；
* 所以可能出现维度 winner 和最终 code 不完全一致的情况，这是正常的。

---

### 改动 7：同步人格测试接口返回结构

**文件**：`backend/routes/mbti.py`

**做了什么**：

保持原接口结构不大改。

核心调用仍然是：

```python
mbti = calculate_mbti(answers)
personality = get_personality(mbti)
raw_scores = get_dimension_scores(answers)
```

返回给前端的数据结构保持兼容：

```python
{
    "mbti": mbti,
    "personality": personality,
    "scores": raw_scores
}
```

**原因**：

避免影响前端 `state.mbtiResult.mbti` 和 `state.mbtiResult.personality` 的使用。

---

### 改动 8：新增 6 条配方自动化测试

**文件**：`tests/test_mbti_recipes.py`

**做了什么**：

新增测试，确保 6 条标准配方都能测出对应人格。

测试内容：

```python
def test_photographer_recipe():
    assert calculate_mbti(PHOTOGRAPHER_ANSWERS) == "DRPT"


def test_commando_recipe():
    assert calculate_mbti(COMMANDO_ANSWERS) == "DRPC"


def test_life_artist_recipe():
    assert calculate_mbti(LIFE_ARTIST_ANSWERS) == "ILST"


def test_architect_recipe():
    assert calculate_mbti(ARCHITECT_ANSWERS) == "IRPT"


def test_enjoyer_recipe():
    assert calculate_mbti(ENJOYER_ANSWERS) == "IRSC"


def test_foodie_recipe():
    assert calculate_mbti(FOODIE_ANSWERS) == "ILSC"
```

新增唯一性测试：

```python
def test_all_persona_recipes_are_unique():
    results = {
        calculate_mbti(PHOTOGRAPHER_ANSWERS),
        calculate_mbti(COMMANDO_ANSWERS),
        calculate_mbti(LIFE_ARTIST_ANSWERS),
        calculate_mbti(ARCHITECT_ANSWERS),
        calculate_mbti(ENJOYER_ANSWERS),
        calculate_mbti(FOODIE_ANSWERS),
    }

    assert results == {"DRPT", "DRPC", "ILST", "IRPT", "IRSC", "ILSC"}
```

---

### 验证结果

使用 6 条定稿配方跑最近原型匹配：

```text
摄影师   意图=DRPT  算出=DRPT  OK
特种兵   意图=DRPC  算出=DRPC  OK
生活家   意图=ILST  算出=ILST  OK
架构师   意图=IRPT  算出=IRPT  OK
悠享家   意图=IRSC  算出=IRSC  OK
美食家   意图=ILSC  算出=ILSC  OK
```

最近原型匹配验证：

```text
6 条配方全部自分类命中
最小原型间距：4.47
最近的一组：生活家 ↔ 美食家
```

结论：

```text
✅ 按摄影师配方答题 → 必出摄影师
✅ 按特种兵配方答题 → 必出特种兵
✅ 按生活家配方答题 → 必出生活家
✅ 按架构师配方答题 → 必出架构师
✅ 按悠享家配方答题 → 必出悠享家
✅ 按美食家配方答题 → 必出美食家
```

---

### 核心设计取舍

本次不再追求：

```text
每一维 winner 必须刚好等于人格 code 的每个字母
```

而是追求：

```text
整体答题模式最接近哪个人格，就返回哪个人格
```

原因：

1. 当前题目选项不是完全正交的；
2. `cover` 覆盖倾向很难和 `immerse / spontaneous` 完全独立表达；
3. 如果继续硬判定，会反复出现悠享家、美食家撞车；
4. 最近原型匹配能最快稳定收口；
5. 自动化测试能保证 6 条标准配方不再漂移。

---

### 当前最终人格解释

| Code   | 人格  | 解释                      |
| ------ | --- | ----------------------- |
| `DRPT` | 摄影师 | 记录、精致、计划、深度；重视画面、审美和取景  |
| `DRPC` | 特种兵 | 记录、精致、计划、覆盖；高效打卡代表性地点   |
| `ILST` | 生活家 | 沉浸、本地、灵感、深度；喜欢街区慢逛和烟火气  |
| `IRPT` | 架构师 | 沉浸、精致、计划、深度；重视城市结构和文化脉络 |
| `IRSC` | 悠享家 | 沉浸、精致、灵感、覆盖；舒服地体验多个高质量点 |
| `ILSC` | 美食家 | 沉浸、本地、灵感、覆盖；围绕味道和本地小店行动 |

---

### 已知限制 & 后续可优化

1. **`calculate_mbti()` 名称仍沿用旧名**
   当前为了兼容前端和接口，没有改名。实际含义已经从“计算 MBTI”变为“计算旅行人格”。

2. **维度分只用于展示，不再决定最终人格**
   前端如果展示四维倾向，需要注意：最终人格以最近原型匹配为准。

3. **生活家和美食家仍是最接近的一组**
   当前最小原型间距是生活家 ↔ 美食家。虽然已能稳定区分，但后续如果继续优化题目，可以优先增强两者差异。

4. **暂时不继续扩展新人格**
   本轮目标是收口，不再新增第 5 维，也不恢复知音者 / 践行者 / 逍遥客 / 漫步客。

5. **景点匹配和路线生成后续也应吃同一套维度**
   本次先完成测试人格稳定收口。后续建议继续同步：

   * `backend/routes/itinerary.py`
   * `backend/data/shanghai_locations.py`
   * `backend/services/llm_service.py`

---

### 本次影响范围

```text
backend/data/mbti_data.py        ← 核心人格算法
backend/routes/mbti.py           ← 人格测试接口，保持兼容
figure/人格配方表.md             ← 6 人格权威配方
tests/test_mbti_recipes.py       ← 新增配方命中测试
```

---

### 前端状态影响

前端状态结构保持不变：

```javascript
const state = {
  mbtiResult: {
    mbti,          // DRPT / DRPC / ILST / IRPT / IRSC / ILSC
    personality,   // 6 人格之一
    scores         // 四维分数，仅展示 / 调试用
  }
};
```

兼容原则：

* 不改 `state.mbtiResult.mbti`
* 不改 `state.mbtiResult.personality`
* 不改人格测试接口返回字段
* 前端无需感知最近原型匹配细节

```
```


---

## 2026-06-07 | 图文海报功能修复（路线图改为本地自绘）& 移除假分享链接

### 背景

延续 `log(3).md` 的目标：导出分享页（Step 8）的**图文海报功能完全不可用**——
`exportAsImage()` 调用 `html2canvas` 把海报 DOM 截成 PNG，但 `index.html` 从未引入该库，
导致永远走降级路径（下载 HTML 而非图片）。此外海报模板是 420px 纯文字堆叠、
分享链接是假的（无后端、点开 404、还用了废弃的 `document.execCommand`）。

本次在 `log(3)` 方案基础上做了**一处关键改进**：路线缩略图**不使用高德静态图 API**，
改为**纯本地 DOM/SVG 自绘**。原因见下方「与 log(3) 的差异」。

### 改动概览

| # | 改动 | 文件 | 类型 |
|---|------|------|------|
| 1 | 引入 html2canvas CDN | `frontend/index.html` | 新增 |
| 2 | 删除假分享链接 HTML 区块 | `frontend/index.html` | 删除 |
| 3 | 重写 `exportAsImage()` 截图函数 | `frontend/js/app.js` | 重写 |
| 4 | 重写 `buildPosterHTML()` 海报模板 | `frontend/js/app.js` | 重写 |
| 5 | 新增 `getCategoryEmoji()` 辅助函数 | `frontend/js/app.js` | 新增 |
| 6 | 新增 `buildPosterRouteMap()` 本地路线图 | `frontend/js/app.js` | 新增 |
| 7 | 删除 `generateShareLink()` / `copyShareLink()` 及调用 | `frontend/js/app.js` | 删除 |
| 8 | 新增导出卡片 loading 动画 + 删除分享链接样式 | `frontend/css/style.css` | 新增/删除 |

---

### 改动 1：引入 html2canvas CDN

**文件**：`frontend/index.html`，高德地图 `<script>` 之后、`</head>` 之前。

```html
<script src="https://webapi.amap.com/maps?v=2.0&key=f82fd3115909f6cda7b1378ff7b2e3cb"></script>
<!-- html2canvas：图文海报截图（导出分享页用） -->
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
</head>
```

**原因**：`exportAsImage()` 检查 `typeof html2canvas !== "undefined"`，但库从未加载，永远降级。

---

### 改动 2：删除假分享链接 HTML 区块

**文件**：`frontend/index.html`，`page-export` 内 `.export-options` 与 `.export-footer` 之间。

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

**原因**：该功能无后端存储，生成的 `/share/xxxxxxxx` 链接打开是 404，是个假功能。

---

### 改动 3：重写 `exportAsImage()`

**文件**：`frontend/js/app.js`（搜索 `function exportAsImage` 定位）

**做了什么**：同步 `.then()` 链 → `async/await`；新增 loading 态、字体就绪等待、错误降级、finally 清理。

**新逻辑**：
1. 校验 `state.itinerary` 是否存在，不存在直接 toast 返回。
2. 给「图文海报」卡片（`document.querySelectorAll(".export-card")[1]`）加 `loading` 类。
3. 离屏渲染：临时 div 设 `position:fixed;left:-9999px;z-index:-1;pointer-events:none;width:750px`，
   `innerHTML = buildPosterHTML()` 后 append 到 body。
4. `try`：
   - 若 `html2canvas` 未定义则抛错；
   - `await document.fonts.ready`（避免 emoji/中文缺字）；
   - `await html2canvas(poster, { scale: 2, useCORS: true, backgroundColor: "#ffffff", logging: false })`；
   - `toDataURL("image/png")` → `<a download>` 触发下载，文件名含城市名。
5. `catch`：降级下载完整 `<!DOCTYPE html>` 包装、居中展示的 HTML 版本，toast 提示失败。
6. `finally`：移除临时 div、移除 `loading` 类。

---

### 改动 4：重写 `buildPosterHTML()`

**文件**：`frontend/js/app.js`（搜索 `function buildPosterHTML` 定位）

**做了什么**：420px 纯文字堆叠 → 750px 卡片式长图，全内联样式（确保 html2canvas 正确渲染）。

**新模板结构**：
```
┌─────────────────────────────────────┐
│ 渐变头部 #FF6B35→#E85D75              │ ✈️ 一拍迹合 + 行程摘要 + 旅行人格徽章
├─────────────────────────────────────┤
│ 信息条 #FFF8F0                        │ 📍目的地 | 📅天数 | 💰人均预算 | 🗺️打卡点数
├─────────────────────────────────────┤
│ 路线缩略图（本地自绘，见改动 6）       │ 710×300px，编号圆点 + 虚线连线
├─────────────────────────────────────┤
│ 🗓️ 行程安排（按天分组，每天分色）     │ 圆形序号 + 分类emoji + 名称 + 🕐时间 + 💡备注
├─────────────────────────────────────┤
│ 💡 旅行小贴士（橙色卡片）             │ itin.tips[] 列表
├─────────────────────────────────────┤
│ 底部水印 #FAFAFA                      │ 生成日期
└─────────────────────────────────────┘
```

**关键实现 — 全局连续编号**：函数开头把 `itin.days[].items[]` 扁平化成 `stops[]`，
每个停留点带 `{ di, global, name, time, notes, category, lat, lng }`，`global` 从 1 连续递增。
**地图圆点编号与时间线圆点编号用的是同一个 `global`**，保证看图能对上行程顺序。
所有文本经 `escapeHtml()`（`app.js` 第 409 行已有）转义。

**数据来源**：
- `state.tripConfig.city / .days / .budget` → 信息条
- `state.mbtiResult.personality.{name, full_name, emoji}` / `.mbti` → 人格徽章
- `state.itinerary.summary` → 头部摘要
- `state.itinerary.days[].items[].{ time, notes, location: { name, lat, lng, category } }` → 时间线 + 地图
- `state.itinerary.tips[]` → 小贴士

**天数配色**（模块级常量 `POSTER_DAY_COLORS`，地图与日期徽章共用）：
```javascript
["#FF6B35", "#E85D75", "#7B68EE", "#20B2AA", "#FF8C42", "#6C5CE7", "#00B894"]
```

---

### 改动 5：新增 `getCategoryEmoji()`

**文件**：`frontend/js/app.js`（紧邻 `buildPosterHTML` 之前）

根据地点分类字符串返回 emoji，用 `category.includes(key)` 模糊匹配，无匹配回退 `📍`。

```javascript
{ 景点:"🏛️", 美食:"🍜", 餐厅:"🍽️", 咖啡:"☕", 购物:"🛍️", 酒店:"🏨",
  交通:"🚇", 公园:"🌳", 寺庙:"🛕", 海滩:"🏖️", 夜景:"🌃", 博物馆:"🏛️",
  商圈:"🏬", 文创:"🎨", 拍照:"📸", 甜品:"🍰", 酒吧:"🍸", 书店:"📚",
  市场:"🛒", 地标:"🗼" }
```

---

### 改动 6：新增 `buildPosterRouteMap()`（核心：本地自绘路线图）

**文件**：`frontend/js/app.js`（紧邻 `buildPosterHTML` 之前）

**做了什么**：把所有带经纬度的 `stops` 按 bounding box 归一化投影，
用一条 SVG 虚线 `<polyline>` 连线 + 一组 HTML 绝对定位编号圆点，画出 710×300 的路线缩略图。

**投影逻辑**：
- 取所有点 lat/lng 的 min/max，`latRange / lngRange`（为 0 时兜底为 1）；
- `x = pad + (lng-minLng)/lngRange * (W-2pad)`；
- `y = pad + (1 - (lat-minLat)/latRange) * (H-2pad)`（纬度越大越靠上，符合地图直觉）；
- 仅 1 个点时居中显示；
- **无任何带坐标的点 → 返回空串，海报中地图区域自动消失**。

**圆点**用 HTML div（而非 SVG `<text>`）渲染编号——html2canvas 对 HTML 文本的兼容性比 SVG text 更稳。
连线用 SVG（线条渲染稳定）。颜色按 `stop.di` 取 `POSTER_DAY_COLORS`。

---

### 改动 7：删除假分享链接 JS

**文件**：`frontend/js/app.js`

- 删除 `generateShareLink()`（生成随机 `/share/:id` 假链接）；
- 删除 `copyShareLink()`（用废弃的 `document.execCommand("copy")`）；
- 删除 `initButtons()` 里 `btn-to-export` 点击回调中的 `generateShareLink()` 调用：
  ```javascript
  document.getElementById("btn-to-export").addEventListener("click", () => {
    showPage("export");   // 原来这里先调了 generateShareLink()
  });
  ```

---

### 改动 8：CSS

**文件**：`frontend/css/style.css`

**新增**（`.export-card:hover` 之后）：
```css
.export-card.loading { pointer-events: none; opacity: 0.6; }
.export-card.loading .export-card-icon { animation: pulse-spin 1s ease-in-out infinite; }
@keyframes pulse-spin {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15) rotate(5deg); }
}
```

**删除**：`.export-share` / `.export-share h3` / `.share-link-box` / `.share-link-box input`
/ `.btn-copy` / `.btn-copy:hover`（分享链接相关样式，对应改动 2/7 一并清理）。

---

### 与 log(3) 的差异（为什么不完全照做）

1. **路线图：高德静态图 API → 本地 DOM/SVG 自绘**（最关键）。
   `log(3)` 用 `restapi.amap.com/v3/staticmap` 拉图片，但其「已知限制」第 1 条自己也承认：
   html2canvas 截图时该跨域图片大概率渲染空白，甚至 taint canvas 导致 `toDataURL` 抛
   `SecurityError` 让整张海报失败。改为本地绘制后**零外部请求、零跨域**，截图 100% 可靠，
   也彻底消除了 `log(3)` 遗留的这个隐患。

2. 文件名带城市名（`一拍迹合-{city}计划.png`）；导出前 `await document.fonts.ready` 防缺字；
   降级 HTML 用完整 `<!DOCTYPE>` 包装并居中展示。

### 已知限制 & 后续可优化

1. **长行程海报**：天数多（>5 天）或每天点位多时海报会很长。可加截断逻辑（如最多展示前 3 天）。
2. **PDF 导出**：仍是 `window.open + win.print()` 浏览器打印方案，体验一般，可考虑 `jsPDF`。
3. **分享功能**：如需恢复，需后端加存储接口（保存行程 → 返回 share_id）+ 前端 `/share/:id` 页面。
4. **路线图为示意图**：本地自绘是按经纬度相对位置的示意图，非真实底图。若要真实底图，
   建议后端代理高德静态图（服务端拉取后转 base64 再下发），绕开浏览器跨域。

### 本次未改动

- 嵌套旧副本 `douyinai2026-YQQ/douyinai2026-YQQ/`（与根目录已不一致，属更旧分支）。
- 后端任何代码。

### 校验

- `node --check frontend/js/app.js` 通过；
- 全前端已无 `generateShareLink` / `copyShareLink` / `share-link` / `export-share` / `btn-copy` 残留引用。
- ⚠️ 截图真机效果（emoji/中文/圆点定位）需本地 `bash run.sh` → http://localhost:5000 走到 Step 8 点「图文海报」实测确认。

---

## 2026-06-07 | 修复：视频分析后地图页「暂无景点数据 / 已提取 0 个景点」

### 背景 / Bug

视频读取成功（日志显示「提取 14 个、写库 12 个」），但 Step 5 地图页仍显示「暂无景点数据」，
提示条写「已从视频中提取 0 个景点」，且没有一个景点符合当前旅行人格。

**根因**：「后端写库成功」≠「前端这一步读到可显示的数据」。

1. Step 5 地图页优先读前端内存里的 `state.analyzedLocations`（视频分析成功后已被塞入
   `data.locations`），只有它为空时才会回库调 `/api/locations/list`。见
   `frontend/js/app.js` 第 1833 / 1567 / 1580 行。
2. 地图页有一句筛选：**只保留有 `lat/lng` 的景点**（`frontend/js/app.js` 第 1850 行）。
3. 而 `/api/video/analyze` 返回给前端的是 `unique_locations` **原始结果**
   （`backend/routes/video.py` 第 151 行），坐标补全 `_fill_coords()` 却**只在
   `_save_locations_to_db()` 写库时执行**（第 644 / 694 行），补全后的 `lat/lng`
   从未回写到接口响应里。

于是接口返回的 14 个景点坐标是 `null/undefined` → 被第 1850 行筛选全部丢弃 →
页面「暂无景点数据」、提示条按筛选后数量算出「0 个」。

### 改动

**文件**：`backend/routes/video.py`，`analyze()` 去重之后、写库与 `return` 之前。

**改前**
```python
    logger.info(f"分析完成：{len(transcripts)}/{len(urls)} 个视频成功，提取 {len(unique_locations)} 个景点")

    # 持久化到数据库（作为预备默认景点）
    saved_count = _save_locations_to_db(unique_locations)
```

**改后**
```python
    # 坐标/类型补全：在返回前就把 lat/lng 补齐，否则前端地图页会因坐标为空把景点全部过滤掉
    for loc in unique_locations:
        lat, lng = _fill_coords((loc.get("name") or "").strip(), loc.get("lat"), loc.get("lng"))
        loc["lat"], loc["lng"] = lat, lng
        raw_type = (loc.get("type") or "").strip().lower()
        loc["type"] = raw_type if raw_type in ("landmark", "street", "food", "culture") \
            else _infer_type_from_keywords(loc.get("keywords", []))

    logger.info(f"分析完成：{len(transcripts)}/{len(urls)} 个视频成功，提取 {len(unique_locations)} 个景点")

    # 持久化到数据库（作为预备默认景点）
    saved_count = _save_locations_to_db(unique_locations)
```

**原因**：把坐标/类型补全提前到「分析返回前」，让**接口响应与写库用的是同一份已补全数据**，
地图页 `state.analyzedLocations` 拿到的每个景点都带 `lat/lng`，不再被第 1850 行筛成 0。
`_save_locations_to_db()` 内部仍调 `_fill_coords()`，但对已补全的坐标是无副作用的
（`lat/lng` 非空时原样返回），类型也复用同一份，两条路径一致、不重复计算。

### 验证

- `python -m py_compile backend/routes/video.py` 通过。
- **后端打桩验证已通过**：用 Flask 测试客户端打桩 `_process_single_video`，让它返回两个
  **完全不带坐标**的景点（模拟「LLM 提取出景点但没给经纬度」这一触发 bug 的真实场景），
  再调 `/api/video/analyze`，结果 `HTTP 200 / fallback:False / total_locations:2`，
  返回的两个景点都拿到非空 `lat/lng` 且补出了 `type`，两条补全分支均覆盖：
  - 命中兜底表：外滩 → `31.24, 121.49`，`type=landmark`；
  - 兜底表未命中：编造的「ZZZ秘密花园」→ 落到上海市中心 `31.2304, 121.4737`，`type=culture`。
  （验证脚本为一次性临时脚本，跑通后已删除，未入库。）
- ⚠️ 端到端真机仍待测：需 `agent-reach`/mcporter 语音转写 + 配好的 LLM 提取跑通真实抖音链接，
  确认 Step 5 地图页正常打点、提示条数量与提取数一致。该路径依赖外部服务，未在本环境内验证；
  但坐标补全发生在转写/提取之后、`return` 之前，与数据来源无关，桩测已足以确证修复逻辑。

### 未改动的次级隐患（待定）

`/api/locations/list` 按 `city` 查询（`backend/routes/locations.py` 第 46 行），
但视频景点入库时 `city` 被**写死成「上海」**（`backend/routes/video.py` 第 713 行）。
若行程城市非上海，**回库读取**这条降级路径仍会查不到。

本次未修，原因：
1. 主修复后正常路径走内存 `analyzedLocations`，不经过 city 查询，地图页已可正常显示；
2. 真修需把行程实际城市从前端/会话透传到 `analyze` 与 `_save_locations_to_db`，改动面更大；
3. 兜底坐标表 `_SHANGHAI_COORD_FALLBACK` 目前只有上海数据，光改 city 字段、非上海城市的坐标
   仍会落到上海市中心，意义有限。如需支持非上海城市 + 依赖回库读取，再补 city 透传 + 多城兜底坐标。

---

## 2026-06-07 | 形成规划页（Step 2）移除「返回上一步」按钮

### 背景

「形成规划」页（即第二部分行程规划页 `#page-plan`，标题「想去哪儿？」）此前在 `.page-inner`
首行也放了和其它步骤一样的「← 返回上一步」按钮（点击走 `goToPreviousStep()` → 回旅行人格页）。

产品希望：该页**不再保留**这个返回按钮。如果要回到「重新测试旅行人格」的界面，
直接点击本页「想去哪儿？」上方人格画像框（`#plan-persona`）里已有的
「重新测试旅行人格」按钮即可（该按钮调用 `retakeMBTI()`，见 `frontend/js/app.js` 第 685 行，
会清空测试结果并 `showPage("mbti")` 跳回测试页）。两个入口功能重复，故删掉返回按钮。

### 改动

**文件**：`frontend/index.html`，`#page-plan`（`<!-- Step 2: 行程规划 -->`）的 `.page-inner` 首行。

**改前**
```html
      <!-- Step 2: 行程规划 -->
      <section id="page-plan" class="page">
        <div class="page-inner">
          <button class="btn-back" onclick="goToPreviousStep()">← 返回上一步</button>
          <div id="plan-check-section" class="plan-check-section" style="display:none;">
```

**改后**
```html
      <!-- Step 2: 行程规划 -->
      <section id="page-plan" class="page">
        <div class="page-inner">
          <div id="plan-check-section" class="plan-check-section" style="display:none;">
```

**说明**：仅删除 `#page-plan` 这一行 `btn-back`。其它步骤页（`#page-buddy` / `#page-videos`
/ `#page-map` / `#page-itinerary` / `#page-export`）的返回按钮**保持不变**。
返回测试页的功能改由人格画像框内的「重新测试旅行人格」按钮承担（`retakeMBTI()`），无需新增代码。

> 注：`lsylog.md` 的「三·补 B」原本要求 `#page-plan` 也插入 `btn-back`，本次改动相当于
> **撤销该页的 btn-back**。若日后对照 lsylog 复现，请跳过 `#page-plan` 一行（其余 5 页仍按 lsylog 插入）。

### 验证

- 浏览器 Ctrl+F5 进入「想去哪儿？」页，确认左上角不再有「← 返回上一步」按钮；
- 点击「想去哪儿？」上方人格框内「重新测试旅行人格」，确认正常跳回旅行人格测试页并清空旧结果。

### 本次未改动

- `frontend/js/app.js` 的 `goToPreviousStep` / `PREV_PAGE`（仍被其它 5 页使用，保留）；
- 嵌套旧副本 `douyinai2026-YQQ/douyinai2026-YQQ/`。

---

## 2026-06-07 | 旅行搭子：补全「同步形成」功能（添加搭子 → 贯穿展示 → 导出页同步计划）

### 背景 / 需求

UI 第三部分「旅行搭子」(`#page-buddy`) 此前只是个空壳：输入框下方橙色按钮写「同步计划」，
点了调 `/api/buddy/sync` 拉到搭子的旧计划列表就完事，**没有真正的「同步形成」闭环**。

产品希望改成：
1. 如果有搭子、且**搭子也在用本产品**，输入用户名/UID 点按钮后只是「**添加搭子**」；
2. 添加成功后，**后续每个步骤页都显示该搭子的头像 + 用户名**，表示此行程有搭子同行；
3. 行程规划好、走到**导出那一步**，才出现「**同步计划**」按钮，把成形的行程同步给搭子；
4. 因此输入搭子信息处的橙色按钮，文案从「同步计划」改为「**添加搭子**」。

### 改动概览

| # | 改动 | 文件 | 类型 |
|---|------|------|------|
| 1 | 橙色按钮「同步计划」→「添加搭子」 | `frontend/index.html` | 改文案 |
| 2 | 新增贯穿后续步骤的「同行搭子」标识 DOM | `frontend/index.html` | 新增 |
| 3 | 导出页新增「同步计划给搭子」按钮 | `frontend/index.html` | 新增 |
| 4 | `submitBuddySync()` 改为「添加搭子」语义 + 新增 `renderBuddyBadge()`/`buddyAvatarLetter()`/`syncPlanToBuddy()`，删除 `loadBuddyPlan()` | `frontend/js/app.js` | 重写/新增/删除 |
| 5 | `showPage()` 内调用 `renderBuddyBadge()`；`startNewTrip()` 重置 `hasBuddy` | `frontend/js/app.js` | 修改 |
| 6 | 新增 `.buddy-badge*` 样式 | `frontend/css/style.css` | 新增 |
| 7 | 新增后端接口 `POST /api/buddy/share-plan`（把行程写入搭子 travel_history） | `backend/routes/buddy.py` | 新增 |

---

### 改动 1：橙色按钮文案 — `frontend/index.html`

`#page-buddy` → `.buddy-input-actions` 内。

**改前**
```html
<button class="btn-primary" onclick="submitBuddySync()">同步计划</button>
```
**改后**
```html
<button class="btn-primary" onclick="submitBuddySync()">添加搭子</button>
```

---

### 改动 2：新增「同行搭子」标识 DOM — `frontend/index.html`

位置：`</main>` 之后、AI 搭子浮动按钮 `#chat-fab` 之前（作为全局固定元素，跨页面复用）。

**新增**
```html
<!-- ========== 旅行搭子：贯穿后续步骤的同行搭子标识 ========== -->
<div id="buddy-badge" class="buddy-badge" style="display:none;">
  <span class="buddy-badge-avatar" id="buddy-badge-avatar"></span>
  <div class="buddy-badge-text">
    <span class="buddy-badge-label">同行搭子</span>
    <span class="buddy-badge-name" id="buddy-badge-name"></span>
  </div>
</div>
```

---

### 改动 3：导出页新增「同步计划给搭子」按钮 — `frontend/index.html`

`#page-export` → `.export-footer` 内，「返回路线」与「开始新的旅行」之间。

**改前**
```html
<div class="export-footer">
  <button class="btn-secondary" onclick="goToPage(6)">
    ← 返回路线
  </button>
  <button class="btn-primary" onclick="startNewTrip()">
    ✨ 开始新的旅行
  </button>
</div>
```
**改后**
```html
<div class="export-footer">
  <button class="btn-secondary" onclick="goToPage(6)">
    ← 返回路线
  </button>
  <button class="btn-primary" id="btn-sync-buddy-plan" style="display:none;" onclick="syncPlanToBuddy()">
    🔗 同步计划给搭子
  </button>
  <button class="btn-primary" onclick="startNewTrip()">
    ✨ 开始新的旅行
  </button>
</div>
```
> 按钮默认 `display:none`，仅在「导出页 + 已添加搭子」时由 `renderBuddyBadge()` 显示。

---

### 改动 4：JS 逻辑 — `frontend/js/app.js`

`handleBuddyChoice()` / `submitBuddySync()` / `loadBuddyPlan()` 整段（原约第 1418–1488 行）替换为下面内容。
要点：
- **`submitBuddySync` 改为「添加搭子」**：调 `/api/buddy/sync` 仅用于**校验搭子存在**（查不到会返回
  error，等价于「搭子没在用本产品」→ 不会误加），成功后记 `state.buddyInfo`、`state.hasBuddy=true`，
  渲染标识，提示后进入下一步。**不再展示搭子旧计划列表 / 自动同步旧计划**。
- **删除 `loadBuddyPlan()`**（原「同步此计划」按钮回调，已无引用）。
- **新增 `renderBuddyBadge()`**：每次切页时按「当前页是否属于 videos/map-preview/itinerary/export
  且已添加搭子」决定标识与导出按钮的显隐。头像取用户名首字母（与顶部用户头像一致）。
- **新增 `syncPlanToBuddy()`**：导出页按钮回调，调新接口 `/api/buddy/share-plan`。

**改后（替换段）**
```js
function handleBuddyChoice(hasBuddy) {
  state.hasBuddy = hasBuddy;
  if (hasBuddy) {
    document.getElementById("buddy-input-section").style.display = "";
  } else {
    state.buddyInfo = null;
    renderBuddyBadge();
    showPage("videos");
  }
}

/** 添加搭子：校验搭子存在（也在用本产品）后记下信息，后续页面贯穿展示其头像与用户名 */
async function submitBuddySync() {
  const identifier = document.getElementById("buddy-identifier").value.trim();
  if (!identifier) {
    showToast("请输入搭子的用户名或UID", true);
    return;
  }

  const statusEl = document.getElementById("buddy-sync-status");
  statusEl.textContent = "正在查找搭子...";
  statusEl.style.color = "var(--text-secondary)";

  const data = await api.post("/api/buddy/sync", { buddy_identifier: identifier });

  if (data.error) {
    statusEl.textContent = data.error;
    statusEl.style.color = "#E74C3C";
    return;
  }

  state.hasBuddy = true;
  state.buddyInfo = data.buddy;
  renderBuddyBadge();

  statusEl.textContent = `已添加搭子：${data.buddy.username}，将与你同行本次旅程`;
  statusEl.style.color = "var(--accent)";

  showToast(`已添加搭子 ${data.buddy.username}！规划完成后可在导出页同步计划给 TA`);
  setTimeout(() => showPage("videos"), 900);
}

/** 头像取用户名首字符（与顶部用户头像一致的呈现方式） */
function buddyAvatarLetter(name) {
  return (name || "?").trim().charAt(0).toUpperCase() || "?";
}

/** 根据 state.buddyInfo 与当前页面，更新「同行搭子」标识与导出页的同步按钮可见性 */
function renderBuddyBadge() {
  const badge = document.getElementById("buddy-badge");
  const syncBtn = document.getElementById("btn-sync-buddy-plan");
  const hasBuddy = !!(state.buddyInfo && state.buddyInfo.username);

  // 仅在「旅行搭子」之后的步骤展示搭子标识
  const showOnPages = ["videos", "map-preview", "itinerary", "export"];
  const onLaterStep = showOnPages.includes(state.currentPage);

  if (badge) {
    if (hasBuddy && onLaterStep) {
      document.getElementById("buddy-badge-avatar").textContent = buddyAvatarLetter(state.buddyInfo.username);
      document.getElementById("buddy-badge-name").textContent = state.buddyInfo.username;
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }

  // 导出页：有搭子才显示「同步计划给搭子」按钮
  if (syncBtn) {
    syncBtn.style.display = hasBuddy && state.currentPage === "export" ? "" : "none";
  }
}

/** 把当前规划好的行程同步到搭子的旅行历史中（导出页） */
async function syncPlanToBuddy() {
  if (!state.buddyInfo || !state.buddyInfo.username) {
    showToast("还没有添加搭子", true);
    return;
  }
  if (!state.itinerary) {
    showToast("请先生成行程", true);
    return;
  }

  const btn = document.getElementById("btn-sync-buddy-plan");
  if (btn) btn.disabled = true;

  const data = await api.post("/api/buddy/share-plan", {
    buddy_id: state.buddyInfo.id,
    buddy_identifier: state.buddyInfo.username,
    city: state.tripConfig.city,
    days: state.tripConfig.days,
    companions: state.hasBuddy ? "和搭子一起" : "独自旅行",
    budget: state.tripConfig.budget ? `人均 ¥${state.tripConfig.budget}` : "",
    itinerary: state.itinerary,
  });

  if (btn) btn.disabled = false;

  if (data.error) {
    showToast(data.error, true);
    return;
  }
  showToast(data.message || `已同步计划给 ${state.buddyInfo.username}`);
}
```

---

### 改动 5：切页时刷新标识 + 重置 — `frontend/js/app.js`

(a) `showPage()` 内 `window.scrollTo(...)` 之后、`if (pageId === "map-preview")` 之前**新增一行**：
```js
    // 同行搭子标识：随页面切换更新可见性
    renderBuddyBadge();
```

(b) `startNewTrip()` 内，`state.buddyInfo = null;` 之后**新增一行**（开始新行程时清掉搭子标记）：
```js
  state.hasBuddy = false;
```

---

### 改动 6：CSS — `frontend/css/style.css`

在 `.user-avatar-name {…}` 规则之后**新增**：
```css
/* 同行搭子标识：固定在右下角，贯穿「精选视频」之后的步骤 */
.buddy-badge {
  position: fixed;
  right: 24px;
  bottom: 96px; /* 让开右下角的 AI 搭子浮动按钮 */
  z-index: 900;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px 8px 8px;
  background: var(--bg-card);
  border: 2px solid var(--border);
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-lg);
}

.buddy-badge-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--gradient-primary);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}

.buddy-badge-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.buddy-badge-label {
  font-size: 11px;
  color: var(--text-muted);
}

.buddy-badge-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
```
> 标识固定在右下角 `bottom:96px`，刚好叠在 AI 搭子浮动按钮（`bottom:32px`、高 60px → 顶到 92px）上方，不遮挡。

---

### 改动 7：后端新增「同步计划给搭子」接口 — `backend/routes/buddy.py`

在 `/sync` 与 `/search` 之间**新增** `share_plan()`。逻辑：登录校验 → 必须带 `itinerary` →
按 `buddy_id`（兜底 `buddy_identifier`）找到搭子 → 不能是自己 → 把 trip 追加进搭子
`travel_history`（带 `shared_by=当前用户名` 标记来源）→ 写库。

**新增**
```python
@buddy_bp.route("/share-plan", methods=["POST"])
def share_plan():
    """
    把当前用户规划好的行程，同步到搭子的旅行历史中（需登录）

    请求体：
    {
        "buddy_id": 2,                 # 或 buddy_identifier（用户名/UID）
        "buddy_identifier": "xxx",
        "city": "上海", "days": 2,
        "companions": "...", "budget": "...",
        "itinerary": {...}
    }
    """
    from backend.routes.auth import _get_current_user
    from datetime import datetime

    data = request.get_json() or {}

    user = _get_current_user()
    if not user:
        return jsonify({"error": "请先登录"}), 401

    if not data.get("itinerary"):
        return jsonify({"error": "请先生成行程后再同步"}), 400

    buddy_id = data.get("buddy_id")
    buddy_identifier = (data.get("buddy_identifier") or "").strip()

    db = get_db()
    try:
        buddy = None
        if buddy_id is not None:
            buddy = db.execute(
                "SELECT id, username, travel_history FROM users WHERE id = ?",
                (buddy_id,),
            ).fetchone()
        if not buddy and buddy_identifier:
            buddy = db.execute(
                "SELECT id, username, travel_history FROM users WHERE username = ?",
                (buddy_identifier,),
            ).fetchone()
        if not buddy:
            return jsonify({"error": "未找到该搭子，请确认搭子已添加"}), 404
        if buddy["id"] == user["id"]:
            return jsonify({"error": "不能把计划同步给自己"}), 400

        trip = {
            "city": data.get("city", "上海"),
            "days": data.get("days", 2),
            "companions": data.get("companions", ""),
            "budget": data.get("budget", ""),
            "mbti_type": user.get("mbti_type"),
            "itinerary": data.get("itinerary"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "shared_by": user["username"],  # 标记来自哪位搭子
        }

        history = []
        if buddy["travel_history"]:
            try:
                history = json.loads(buddy["travel_history"])
            except json.JSONDecodeError:
                history = []
        history.append(trip)

        db.execute(
            "UPDATE users SET travel_history = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), buddy["id"]),
        )
        db.commit()
        return jsonify({
            "message": f"已把计划同步给 {buddy['username']}",
            "buddy": {"id": buddy["id"], "username": buddy["username"]},
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"同步计划给搭子失败: {e}")
        return jsonify({"error": "同步失败，请稍后重试"}), 500
    finally:
        db.close()
```
> 复用 `users.travel_history`（与 `/api/itinerary/save` 同一份数据结构），搭子下次登录在「旅行历史」即可看到，带 `shared_by` 区分是搭子分享来的。无需建新表。

---

### 设计说明 / 取舍

- **没有真实头像图**：`users` 表无 avatar 字段，搭子头像沿用全站既有约定——用户名首字母 + 橙色渐变圆底
  （与顶部 `#user-avatar-letter` 一致），保证一致性、零数据迁移。
- **「同步计划」是真实功能不是假按钮**：参考本 log 早前「移除假分享链接」的教训，导出页同步按钮
  落到真后端 `/share-plan`，真正把行程写进搭子账号，而非弹个假提示。
- **「搭子也在用本产品」= 能在 users 表查到**：`/sync` 查不到即 404，前端原样报错，天然实现该前提。

### 验证

- `node --check frontend/js/app.js` 通过；
- `python -m py_compile backend/routes/buddy.py` 通过；
- 全前端已无 `loadBuddyPlan` 残留引用。
- ⚠️ 端到端真机待测：需注册两个账号 A/B，A 登录走到 Step 3 输入 B 的用户名点「添加搭子」，
  确认后续 4 个步骤页右下角出现 B 的头像+用户名；走到导出页点「同步计划给搭子」，
  再用 B 登录确认其「旅行历史」多出这条（带 `shared_by: A`）。该路径依赖运行态数据库，未在本环境内跑。

### 本次未改动

- `backend/routes/buddy.py` 的 `/sync`、`/search` 接口（`/sync` 现仅用于「添加搭子」校验，保留原样）；
- 嵌套旧副本 `douyinai2026-YQQ/douyinai2026-YQQ/`。
