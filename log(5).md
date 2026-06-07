# 改动记录（log.md）

> 这份文档用于交接给其他 AI Agent / 协作同学。
> 目标是让对方读完后，直接知道：
> 1. 这次为什么改
> 2. 改了哪些文件
> 3. 在哪个函数/哪一段改
> 4. 原来是什么逻辑
> 5. 现在改成了什么逻辑
> 6. 如果还要继续改，应该优先看哪里

---

## 1. 这次改动要解决的问题

这次主要修的是“景点地图预览页里，所有景点都被标记成 `风格不匹配`”的问题，原因有两层：

1. 前端地图页的 MBTI 匹配逻辑仍然残留旧版编码。
   - 新版第三维/第四维是：`P/S` 和 `C/T`
   - 旧逻辑还在按：`P/F` 和 `C/S` 判断
   - 结果会把很多本来应该匹配的景点误判成不匹配

2. 视频提取出来的景点通常没有 `travel_style_fit` 这类结构化风格字段。
   - 原来前端遇到“没有风格字段”的景点时，仍然继续走硬匹配
   - 这样大部分视频景点都会被压成“不匹配”
   - 现在已经接入已有大模型 API，为视频景点自动补全 `travel_style_fit`

---

## 2. 已完成改动总览

本次实际修改了 4 个文件：

1. `frontend/js/app.js`
2. `backend/services/llm_service.py`
3. `backend/routes/video.py`
4. `backend/routes/itinerary.py`

没有改动 HTML / CSS。

---

## 3. 前端改动

## 3.1 地图页人格匹配逻辑修正

**文件**
`frontend/js/app.js`

**位置**
函数：`isPersonalityMatch(loc)`
搜索关键字：`function isPersonalityMatch`
当前大约在 `frontend/js/app.js:1750`

### 原来的问题

原逻辑的问题有两个：

1. 第三维用的是旧判断：
   - `P -> fit.exp === "scene"`
   - `F -> fit.exp === "food"`

2. 第四维用的是旧判断：
   - `C -> fit.social === "social"`
   - `S -> fit.social === "solo"`

3. 即使景点没有 `travel_style_fit` / `personality_fit`，也会继续参与打分，最后很容易因为分数不够被判成“不匹配”。

### 现在改成什么

在 `isPersonalityMatch(loc)` 里做了 3 个修正：

1. 新增“是否有结构化风格字段”的判断：
   - 读取 `loc.travel_style_fit || loc.personality_fit || {}`
   - 检查其中是否至少存在一个有效字段：`pace/pref/exp/social`

2. 如果景点没有结构化风格字段，直接返回 `true`
   - 也就是“不阻塞、不误判”
   - 这样视频景点、预览态景点即使暂时没有结构化字段，也不会在前端被打成“不匹配”

3. 把 MBTI 第三、第四维判断切换到新版编码：
   - 第三维：
     - `P -> fit.exp in ["any", "scene"]`
     - `S -> fit.exp in ["any", "food"]`
   - 第四维：
     - `C -> fit.social in ["any", "social"]`
     - `T -> fit.social in ["any", "solo"]`

### 你需要关注的具体代码点

在这个函数里，目前新增/改动的是下面这几类语句：

```js
const hasStructuredFit =
  !!fit &&
  ["pace", "pref", "exp", "social"].some(
    (key) => typeof fit[key] === "string" && fit[key].trim() !== ""
  );
if (!hasStructuredFit) return true;
```

以及把旧判断：

```js
if (d2 === "F" && (fit.exp === "any" || fit.exp === "food")) score++;
if (d3 === "S" && (fit.social === "any" || fit.social === "solo")) score++;
```

改成了：

```js
if (d2 === "S" && (fit.exp === "any" || fit.exp === "food")) score++;
if (d3 === "T" && (fit.social === "any" || fit.social === "solo")) score++;
```

### 这段改动的影响

影响地图预览页这些功能：

1. “风格不匹配”徽标是否出现
2. “只看符合我风格的景点”开关的筛选结果
3. 匹配数量 `matchCount` / `mismatchCount` 的统计

---

## 4. 后端改动：给视频景点补 `travel_style_fit`

## 4.1 新增结构化风格补全能力

**文件**
`backend/services/llm_service.py`

**位置**

1. 常量定义位置：文件前部，`logger = logging.getLogger(__name__)` 后面
2. 新增函数：
   - `_normalize_travel_style_fit(raw_fit)`
   - `_has_structured_travel_style_fit(fit)`
   - `enrich_locations_travel_style_fit(locations, video_title="")`

搜索关键字：

1. `def _normalize_travel_style_fit`
2. `def _has_structured_travel_style_fit`
3. `def enrich_locations_travel_style_fit`

当前大约在：

1. `backend/services/llm_service.py:122`
2. `backend/services/llm_service.py:135`
3. `backend/services/llm_service.py:140`

### 新增了什么

#### 1. 新增风格字段合法值定义

新增常量：

```python
_TRAVEL_STYLE_FIT_SCHEMA = {
    "pace": {"any", "rush", "slow"},
    "pref": {"any", "classic", "hidden"},
    "exp": {"any", "scene", "food"},
    "social": {"any", "social", "solo"},
}
```

作用：
统一约束 `travel_style_fit` 的合法结构，避免模型返回脏值直接落库。

#### 2. 新增标准化函数 `_normalize_travel_style_fit`

作用：

1. 把模型返回的 `travel_style_fit` 做清洗
2. 只保留 schema 允许的 key/value
3. 非法值直接丢弃

#### 3. 新增检查函数 `_has_structured_travel_style_fit`

作用：
判断某个景点当前是否已经有可用的结构化风格字段。

#### 4. 新增核心函数 `enrich_locations_travel_style_fit`

作用：
使用现有大模型 API，为视频提取出来、但缺少结构化风格字段的景点补全 `travel_style_fit`。

### 这个函数的逻辑

`enrich_locations_travel_style_fit(locations, video_title="")` 现在的处理流程是：

1. 遍历传入的 `locations`
2. 过滤出“没有结构化 `travel_style_fit` / `personality_fit`”的景点
3. 为这些景点组织 prompt，送给模型
4. 模型输出 JSON 数组，格式如下：

```json
[
  {
    "name": "景点名",
    "travel_style_fit": {
      "pace": "rush|slow|any",
      "pref": "classic|hidden|any",
      "exp": "scene|food|any",
      "social": "social|solo|any"
    }
  }
]
```

5. 用 `_extract_json_array()` 解析
6. 用 `_normalize_travel_style_fit()` 清洗
7. 按景点名回填到原始 `locations`

### 模型调用策略

这个函数内部优先走：

1. `chat_completion(...)`

如果没有结果，再 fallback 到：

2. `_call_doubao_responses(prompt, use_web_search=False)`

所以这个补全能力是“优先复用当前项目已有 LLM 配置”，而不是新起一套接口。

### 重要说明

这里虽然字段名还是旧的：

1. `exp`
2. `social`

但语义已经按新版人格维度写进 prompt 里了：

1. `exp`
   - `scene` 对应新版第三维里更偏计划/稳定路线的点
   - `food` 对应新版第三维里更偏随性/临场探索的点

2. `social`
   - `social` 对应新版第四维里更偏高覆盖、多点串联
   - `solo` 对应新版第四维里更偏深度停留、慢体验

也就是说：
字段名没改库结构，但语义提示已经更新。

---

## 5. 后端改动：把视频提取流程接到风格补全

## 5.1 视频景点提取后立刻补风格字段

**文件**
`backend/routes/video.py`

**位置**
函数：`_extract_locations_from_text(transcript, video_title, mbti)`
搜索关键字：`def _extract_locations_from_text`
当前大约在 `backend/routes/video.py:326`

### 原来的逻辑

原来这段函数只做：

1. 把视频转写文本交给 LLM
2. 提取景点 JSON
3. 给每个景点补 `labels`
4. 直接返回景点列表

### 现在改成什么

做了 3 处改动：

#### 1. 增加导入

原来：

```python
from backend.services.llm_service import chat_completion
```

现在：

```python
from backend.services.llm_service import chat_completion, enrich_locations_travel_style_fit
```

#### 2. 给视频景点显式打 `source`

在遍历 `locations` 的时候新增：

```python
loc["source"] = loc.get("source") or "video"
```

作用：
让后续前端/行程逻辑能识别这是视频来源景点。

#### 3. 返回前调用风格补全

原来直接：

```python
return [loc for loc in locations if isinstance(loc, dict) and loc.get("name")]
```

现在改成：

```python
locations = [loc for loc in locations if isinstance(loc, dict) and loc.get("name")]
return enrich_locations_travel_style_fit(locations, video_title=video_title)
```

作用：
视频提取出来的景点，不再直接裸返回，而是先补齐 `travel_style_fit` 再返回给前端。

---

## 5.2 视频景点入库时保存 `travel_style_fit`

**文件**
`backend/routes/video.py`

**位置**
函数：`_save_locations_to_db(locations)`
搜索关键字：`INSERT OR IGNORE INTO attractions`
当前大约在 `backend/routes/video.py:707` 附近

### 原来的逻辑

原来写入数据库时，`personality_fit` 固定写死为空对象：

```python
json.dumps({}, ensure_ascii=False)
```

### 现在改成什么

改成写入景点自身的结构化风格字段：

```python
json.dumps(loc.get("travel_style_fit", {}), ensure_ascii=False)
```

### 作用

这意味着：

1. 视频景点补出来的 `travel_style_fit` 不只是接口返回时临时可用
2. 还会真正持久化进数据库的 `personality_fit` 列
3. 后续再次读取这些景点时，也能带出结构化风格数据

---

## 6. 后端改动：把 `travel_style_fit` 透传到行程生成链路

## 6.1 视频景点合并时保留 `travel_style_fit`

**文件**
`backend/routes/itinerary.py`

**位置**
函数：`_convert_video_locations(video_locations, existing_locations=None)`
搜索关键字：`def _convert_video_locations`
当前大约在 `backend/routes/itinerary.py:258`

### 改动 1：合并到已有景点时保留风格字段

在“视频景点与已有景点相似”的分支里，原来只会更新：

1. 坐标
2. 描述
3. tags

现在新增：

```python
if vl.get("travel_style_fit"):
    merged["travel_style_fit"] = vl["travel_style_fit"]
```

作用：
如果视频版本景点已经有补全好的结构化风格字段，那么合并到已有景点时不要丢。

### 改动 2：作为新景点加入时保留风格字段

原来新建视频景点对象时写的是：

```python
"travel_style_fit": {},
```

现在改成：

```python
"travel_style_fit": vl.get("travel_style_fit", {}),
```

作用：
如果视频景点本身已经补好了风格字段，那么作为新景点进入路线生成时会完整保留。

---

## 6.2 地图预览页传回来的景点也保留 `travel_style_fit`

**文件**
`backend/routes/itinerary.py`

**位置**
函数：`_convert_preview_locations(preview_locations)`
搜索关键字：`def _convert_preview_locations`
当前大约在 `backend/routes/itinerary.py:323`

### 原来的逻辑

预览页选中的景点在转成后端统一格式时，风格字段写死为空：

```python
"travel_style_fit": {},
```

### 现在改成什么

改成：

```python
"travel_style_fit": vl.get("travel_style_fit") or vl.get("personality_fit") or {},
```

### 作用

这样不管景点来自：

1. 视频分析结果
2. 默认推荐结果
3. 数据库已有景点

只要它身上已经有结构化风格字段，从地图预览页传到行程生成时就不会被抹掉。

---

## 7. 后端改动：行程推荐逻辑也切到新版 MBTI 编码

**文件**
`backend/routes/itinerary.py`

**位置**
函数：`_recommend_locations(all_locations, profile, days)`
搜索关键字：`def _recommend_locations`
当前大约在 `backend/routes/itinerary.py:357`

### 原来的问题

这个函数里还残留了一套更老的 MBTI 编码，和前端地图页不是同一套：

1. 第一维按 `R/S`
2. 第二维按 `C/H`
3. 第三维按 `F/S`
4. 第四维甚至有 `o`

这和当前项目新版编码不一致，会导致：

1. 地图预览页按一套逻辑筛
2. 行程推荐又按另一套逻辑推荐

前后不统一。

### 现在改成什么

已经统一成与前端一致的新版编码：

#### 第一维

原来：

```python
if pace == "R" and fit.get("pace") in ["any", "rush"]:
elif pace == "S" and fit.get("pace") in ["any", "slow"]:
```

现在：

```python
if pace == "D" and fit.get("pace") in ["any", "rush"]:
elif pace == "I" and fit.get("pace") in ["any", "slow"]:
```

#### 第二维

原来：

```python
if pref == "C" and fit.get("pref") in ["any", "classic"]:
elif pref == "H" and fit.get("pref") in ["any", "hidden"]:
```

现在：

```python
if pref == "R" and fit.get("pref") in ["any", "classic"]:
elif pref == "L" and fit.get("pref") in ["any", "hidden"]:
```

#### 第三维

原来：

```python
if exp == "F" and fit.get("exp") in ["any", "food"]:
elif exp == "S" and fit.get("exp") in ["any", "scene"]:
```

现在：

```python
if exp == "P" and fit.get("exp") in ["any", "scene"]:
elif exp == "S" and fit.get("exp") in ["any", "food"]:
```

#### 第四维

原来：

```python
if social == "S" and fit.get("social") in ["any", "social"]:
elif social == "o" and fit.get("social") in ["any", "solo"]:
```

现在：

```python
if social == "C" and fit.get("social") in ["any", "social"]:
elif social == "T" and fit.get("social") in ["any", "solo"]:
```

### 作用

现在前后端对人格匹配的理解统一了：

1. 地图页筛选逻辑
2. 路线推荐逻辑
3. 视频景点结构化补全逻辑

三者都围绕同一套新版 `D/I + R/L + P/S + C/T` 运行。

---

## 8. 这次改动后的数据链路

为了让接手的人快速理解，这里把链路串起来：

### 链路 1：视频 -> 地图预览

1. 视频转写后，`backend/routes/video.py::_extract_locations_from_text(...)`
2. 提取景点 JSON
3. 调用 `backend/services/llm_service.py::enrich_locations_travel_style_fit(...)`
4. 每个视频景点尽量补齐 `travel_style_fit`
5. 前端 `frontend/js/app.js::isPersonalityMatch(loc)` 用新版规则判断
6. 如果某个景点仍然没有结构化字段，前端直接放行，不再误判为“不匹配”

### 链路 2：视频景点 -> 入库

1. 视频景点分析完成
2. `backend/routes/video.py::_save_locations_to_db(...)`
3. 把 `travel_style_fit` 写入数据库 `personality_fit`

### 链路 3：地图预览 -> 行程生成

1. 用户在地图预览页勾选景点
2. `backend/routes/itinerary.py::_convert_preview_locations(...)`
3. 保留 `travel_style_fit`
4. 进入 `_recommend_locations(...)` / 行程生成逻辑
5. 后端使用新版 MBTI 编码继续推荐

---

## 9. 本次没有改动、但接手人需要知道的点

### 1. 没有改数据库表结构

数据库列名仍然是：

1. `personality_fit`

前后端对象里仍然兼容：

1. `travel_style_fit`
2. `personality_fit`

这次只是把其内容语义对齐到了新版人格模型，没有做迁移表结构。

### 2. 没有改前端 UI 文案和布局

这次主要是逻辑修复，没有改：

1. 地图页布局
2. 风格不匹配徽标样式
3. 筛选条样式

### 3. demo fallback 数据没有专门补 `travel_style_fit`

`backend/routes/video.py::_demo_analyze(...)` 这次没有专门改 demo 返回结构。

但因为前端现在已经加了：

```js
if (!hasStructuredFit) return true;
```

所以即使 demo 数据没有结构化风格字段，也不会再被前端整批误判成“不匹配”。

---

## 10. 建议下一位 Agent 优先检查的地方

如果后续还要继续完善，建议按这个顺序看：

1. `frontend/js/app.js`
   - 先看 `isPersonalityMatch(loc)`
   - 这是地图页误判问题的最前端入口

2. `backend/services/llm_service.py`
   - 再看 `enrich_locations_travel_style_fit(...)`
   - 这是视频景点结构化风格补全的核心入口

3. `backend/routes/video.py`
   - 看 `_extract_locations_from_text(...)`
   - 确认补全函数有没有真正被调用

4. `backend/routes/itinerary.py`
   - 看 `_convert_video_locations(...)`
   - 看 `_convert_preview_locations(...)`
   - 看 `_recommend_locations(...)`
   - 这是后端是否把风格字段一路透传到底、并且按新版 MBTI 推荐的关键

---

## 11. 本次已做的验证

已经执行过的校验命令：

```bash
python -m py_compile backend/services/llm_service.py backend/routes/video.py backend/routes/itinerary.py
```

结果：

1. 通过
2. 说明这 3 个 Python 文件至少不存在语法错误

未做的验证：

1. 没有跑真实视频的端到端接口联调
2. 没有在浏览器里手工点击验证整条 UI 流程

所以如果下一位 Agent 要继续接手，最值得补的是：

1. 真实视频分析接口联调
2. 地图预览页实际筛选表现验证

---

## 12. 最简交接结论

如果你只想让下一个 Agent 快速知道“我到底动了哪里”，一句话总结如下：

1. 在 `frontend/js/app.js` 的 `isPersonalityMatch(loc)` 里，把旧版 MBTI 第三/第四维判断从 `F/S` 改成了新版 `S/T`，并增加了“无 `travel_style_fit` 时直接放行”的逻辑。
2. 在 `backend/services/llm_service.py` 里新增了 `enrich_locations_travel_style_fit(...)`，用已有大模型 API 为视频景点补结构化风格字段。
3. 在 `backend/routes/video.py` 里把这个补全函数接进了视频景点提取流程，并在入库时保存 `travel_style_fit`。
4. 在 `backend/routes/itinerary.py` 里保证 `travel_style_fit` 在“视频结果 -> 地图预览 -> 行程生成”这条链路中不丢失，同时把 `_recommend_locations(...)` 改成新版 MBTI 编码。

