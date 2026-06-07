"""
旅行 MBTI 数据 - 6 人格最近原型匹配模型

四个维度：
  D (Document/Record) vs I (Immerse)  — 记录表达 vs 沉浸感受
  R (Refined) vs L (Local)            — 精致风格 vs 本地烟火
  P (Plan) vs S (Spontaneous)          — 计划依赖 vs 灵感优先
  C (Cover) vs T (Deep/Thorough)       — 覆盖打卡 vs 深度停留

问题类型：
  - single: 单选题（3-5 个选项）
  - ranking: 排序题（用户排列选项顺序）
  - slider: 滑块题（A-B 两端，0~100）
"""

# ============================================================
# 测试题目
# ============================================================
QUESTIONS = [
    # ── Q1 行李箱隐喻（排序） ──
    {
        "id": 1,
        "type": "ranking",
        "question": "如果行李箱只剩一个空位，你会放进什么？（请拖拽排列，最想带的排最前）",
        "deco_image": "行李箱.png",
        "deco_position": "right",
        "options": [
            {"id": "a", "text": "一本与目的地有关的书", "tags": ["record", "deep"]},
            {"id": "b", "text": "一个能稳定出片的自拍杆", "tags": ["record", "refined"]},
            {"id": "c", "text": "一双舒服到可以暴走的鞋", "tags": ["immerse", "cover"]},
            {"id": "d", "text": "什么都不放，留给当地买到的小东西", "tags": ["local", "deep"]},
        ],
    },
    # ── Q2 景点体验（滑块） ──
    {
        "id": 2,
        "type": "slider",
        "question": "去到一个景点，你会更在意什么？",
        "deco_image": "相机.png",
        "deco_position": "right",
        "label_a": "拍照打卡出片",
        "label_b": "慢慢感受氛围",
        "dimension": "di",
        "weight_a": "record",
        "weight_b": "immerse",
    },
    # ── Q3 消费场所（滑块） ──
    {
        "id": 3,
        "type": "slider",
        "question": "在陌生城市吃第一顿饭，你更想去哪里？",
        "deco_image": "指南针.png",
        "deco_position": "left",
        "label_a": "空间漂亮、体验稳定、适合拍照的店",
        "label_b": "本地人常去、可能环境普通但很有城市味道的小店",
        "dimension": "rl",
        "weight_a": "refined",
        "weight_b": "local",
    },
    # ── Q4 城市关系（单选） ──
    {
        "id": 4,
        "type": "single",
        "question": "在这个目的地，你有一个下午的时间可以安排，你会去哪？",
        "deco_image": "地图.png",
        "deco_position": "right",
        "options": [
            {"id": "a", "text": '去几个代表性"景点"，不想错过', "tags": ["record", "cover"]},
            {"id": "b", "text": "去一片街区慢慢逛，观察城市气质", "tags": ["immerse", "deep"]},
            {"id": "c", "text": "去本地人的生活区，看看他们怎么生活", "tags": ["local", "deep"]},
            {"id": "d", "text": "去好吃、好逛、好坐的地方，享受城市设施", "tags": ["refined", "deep"]},
        ],
    },
    # ── Q5 时间有限（排序） ──
    {
        "id": 5,
        "type": "ranking",
        "question": "如果你在一个城市只有一天，你更怕什么？（请拖拽排列，最怕的排最前）",
        "deco_image": "指示牌.png",
        "deco_position": "left",
        "options": [
            {"id": "a", "text": "明明来了却错过必去点", "tags": ["cover", "record"]},
            {"id": "b", "text": "行程太赶，最后什么都没感受到", "tags": ["deep", "immerse"]},
            {"id": "c", "text": "临时不知道去哪，浪费时间", "tags": ["plan", "cover"]},
            {"id": "d", "text": "去的地方太游客化，没有真实感", "tags": ["local", "deep"]},
        ],
    },
    # ── Q6 计划准备度（单选） ──
    {
        "id": 6,
        "type": "single",
        "question": "出发前，你收藏了很多这个城市的视频。你最希望 AI 怎么帮你？",
        "deco_image": "护照.png",
        "deco_position": "right",
        "options": [
            {"id": "a", "text": "直接排成每天的完整路线，我照着走就行", "tags": ["plan", "cover"]},
            {"id": "b", "text": "先按区域和主题整理好，我再自己挑", "tags": ["plan", "refined"]},
            {"id": "c", "text": "只告诉我最值得去的几个点，其他到时候再说", "tags": ["plan", "deep"]},
            {"id": "d", "text": "不用提前整理，等我到了当地随时问你", "tags": ["spontaneous", "local"]},
        ],
    },
    # ── Q7 路线弹性（单选） ──
    {
        "id": 7,
        "type": "single",
        "question": "你原本下午有一条路线，但刚刷到一个附近很心动的地方。你会？",
        "deco_image": "墨镜.png",
        "deco_position": "left",
        "options": [
            {"id": "a", "text": "不改，先按原路线走", "tags": ["plan", "cover"]},
            {"id": "b", "text": "如果顺路，就加进去", "tags": ["plan", "refined"]},
            {"id": "c", "text": "直接改，旅行就是要抓住当下心动", "tags": ["spontaneous", "immerse"]},
            {"id": "d", "text": "先让 AI 判断：值不值得为了它调整路线", "tags": ["spontaneous", "deep"]},
        ],
    },
    # ── Q8 离开城市（排序） ──
    {
        "id": 8,
        "type": "ranking",
        "question": "离开一座城市时，你最希望带走什么？（请拖拽排列，最想带走的排最前）",
        "deco_image": "城堡.png",
        "deco_position": "right",
        "options": [
            {"id": "a", "text": "一组很好看的照片", "tags": ["record", "refined"]},
            {"id": "b", "text": "一个反复想起的味道", "tags": ["local", "deep"]},
            {"id": "c", "text": "一段和当地人/同行人的聊天", "tags": ["local", "immerse"]},
            {"id": "d", "text": "一种「我好像懂了这里」的感觉", "tags": ["immerse", "deep"]},
            {"id": "e", "text": "一件有纪念意义的小物", "tags": ["record", "cover"]},
        ],
    },
]

# ============================================================
# 维度定义
# ============================================================
DIMENSIONS = {
    "di": {"name": "记录 vs 沉浸", "pole_a": "D", "pole_b": "I",
            "label_a": "记录表达型", "label_b": "沉浸感受型",
            "tag_a": "record", "tag_b": "immerse"},
    "rl": {"name": "精致 vs 本地", "pole_a": "R", "pole_b": "L",
            "label_a": "精致风格型", "label_b": "本地烟火型",
            "tag_a": "refined", "tag_b": "local"},
    "ps": {"name": "计划 vs 灵感", "pole_a": "P", "pole_b": "S",
            "label_a": "计划依赖型", "label_b": "灵感优先型",
            "tag_a": "plan", "tag_b": "spontaneous"},
    "cd": {"name": "覆盖 vs 深度", "pole_a": "C", "pole_b": "T",
            "label_a": "覆盖打卡型", "label_b": "深度停留型",
            "tag_a": "cover", "tag_b": "deep"},
}

# tag → (dimension_key, is_pole_a)
TAG_MAP = {
    "record":      ("di", True),
    "immerse":     ("di", False),
    "refined":     ("rl", True),
    "local":       ("rl", False),
    "plan":        ("ps", True),
    "spontaneous": ("ps", False),
    "cover":       ("cd", True),
    "deep":        ("cd", False),
}

VECTOR_TAGS = [
    "record",
    "immerse",
    "refined",
    "local",
    "plan",
    "spontaneous",
    "cover",
    "deep",
]

# ============================================================
# 旅行人格类型（最终 6 种主画像）
# ============================================================
PERSONALITY_TYPES = {
    "photographer": {
        "id": 3,
        "code": "DRPT",
        "name": "摄影师",
        "full_name": "审美驱动的城市记录者",
        "emoji": "📸",
        "subtitle": "记录 × 精致 × 计划 × 深度",
        "image": "3摄影师.png",
        "description": "你是一个审美驱动的城市记录者。\n你会通过画面记住一座城市。空间是否好看、光线是否舒服、路线是否适合拍摄，都会影响你的旅行体验。你不是只想打卡，而是希望这趟旅行能留下漂亮而有质感的记录。",
        "color": "#9B59B6",
        "strengths": ["审美敏锐", "出片率高", "视觉记录"],
        "style_tags": ["记录表达", "审美优先", "结构路线", "深度取景"],
        "avoid": ["环境混乱的路线", "光线差的时段", "纯功能性景点"],
        "recommend_strategy": "出片街区、设计感咖啡店、展览、买手店、城市夜景、拍照机位；补充最佳拍摄时间、机位、光线提示。",
        "dimensions": {"di": "a", "rl": "a", "ps": "a", "cd": "b"},
    },
    "commando": {
        "id": 4,
        "code": "DRPC",
        "name": "特种兵",
        "full_name": "高效打卡的城市任务完成者",
        "emoji": "⚡",
        "subtitle": "记录 × 精致 × 计划 × 覆盖",
        "image": "4特种兵.png",
        "description": "你是一个高效打卡的城市任务完成者。\n你希望在有限时间里尽可能看见这座城市最有代表性的部分。你不喜欢临时混乱，也不想因为没规划好而错过重要地点。对你来说，一条清晰、高效、有完成感的路线非常重要。",
        "color": "#E74C3C",
        "strengths": ["执行力强", "时间管理", "完成感高"],
        "style_tags": ["高效覆盖", "经典路线", "严格计划", "打卡完成"],
        "avoid": ["留白太多", "临时调整", "小众但不具代表性的地方"],
        "recommend_strategy": "城市经典路线、必去景点合集、高效一日游、交通顺路安排；给清晰时间表，减少留白和临时调整。",
        "dimensions": {"di": "a", "rl": "a", "ps": "a", "cd": "a"},
    },
    "life_artist": {
        "id": 2,
        "code": "ILST",
        "name": "生活家",
        "full_name": "本地烟火的生活潜入者",
        "emoji": "🏠",
        "subtitle": "沉浸 × 本地 × 灵感 × 深度",
        "image": "2生活家.png",
        "description": "你是一个本地烟火的生活潜入者。\n你喜欢旅行里那些「不像景点」的部分：早餐摊、老社区、本地人常去的小店、街边聊天的人。你希望短暂地进入当地生活，而不是只站在游客视角看城市。你的路线适合慢下来，保留街区漫游和偶遇的空间。",
        "color": "#E67E22",
        "strengths": ["本地融入", "生活观察", "真实体验"],
        "style_tags": ["本地生活", "街区慢逛", "灵感游走", "深度停留"],
        "avoid": ["过度商业街", "纯拍照点", "网红但缺少地方感的店"],
        "recommend_strategy": "本地小吃、菜市场、老街区、居民区附近小店、本地人推荐路线；避开过度商业街、纯拍照点。",
        "dimensions": {"di": "b", "rl": "b", "ps": "b", "cd": "b"},
    },
    "architect": {
        "id": 6,
        "code": "IRPT",
        "name": "架构师",
        "full_name": "结构感强的安心探索者",
        "emoji": "🏗️",
        "subtitle": "沉浸 × 精致 × 计划 × 深度",
        "image": "6架构师.png",
        "description": "你是一个结构感强的安心探索者。\n你并不是一定要把每天排满，但你不喜欢信息散乱、临时不知道去哪。你希望 AI 先把内容整理成清晰的区域、主题和备选项，再把选择权留给你。你适合有脉络、有解释、也有自主空间的路线。",
        "color": "#3498DB",
        "strengths": ["信息整理", "自主决策", "结构清晰"],
        "style_tags": ["结构需求", "按区域整理", "文化脉络", "深度探索"],
        "avoid": ["一长串未分类地点", "完全无计划", "信息混乱"],
        "recommend_strategy": "按区域整理、按主题整理、A/B 路线选择、备选地点、路线理由解释；避免直接给一长串未分类地点。",
        "dimensions": {"di": "b", "rl": "a", "ps": "a", "cd": "b"},
    },
    "enjoyer": {
        "id": 8,
        "code": "IRSC",
        "name": "悠享家",
        "full_name": "舒适享受的城市生活玩家",
        "emoji": "☕",
        "subtitle": "沉浸 × 精致 × 灵感 × 覆盖",
        "image": "8悠享家.png",
        "description": "你是一个舒适享受的城市生活玩家。\n你喜欢一座城市里那些让人舒服的部分：好吃的店、好坐的咖啡馆、好逛的街区、适合聊天和停留的空间。你不想把旅行变成体力挑战，更在意体验是否稳定、轻松、有质感。",
        "color": "#F39C12",
        "strengths": ["体验质感", "节奏舒适", "享受当下"],
        "style_tags": ["舒适优先", "稳定不踩雷", "灵感选择", "轻松覆盖"],
        "avoid": ["暴走路线", "长时间排队", "交通折腾"],
        "recommend_strategy": "好坐的咖啡店、稳定不踩雷的餐厅、轻松街区、适合聊天的空间；路线中加入休息点，避免暴走、排队、交通折腾。",
        "dimensions": {"di": "b", "rl": "a", "ps": "b", "cd": "a"},
    },
    "foodie": {
        "id": 9,
        "code": "ILSC",
        "name": "美食家",
        "full_name": "味觉记忆驱动的城市吃货",
        "emoji": "🍜",
        "subtitle": "沉浸 × 本地 × 灵感 × 覆盖",
        "image": "9美食家.png",
        "description": "你是一个味觉记忆驱动的城市吃货。\n你会通过味道记住一座城市。比起标准景点，你更在意吃到什么、在哪里吃、这家店有没有本地气息。你的路线应该围绕餐饮节奏展开，而不是把吃饭当成景点之间的空隙。",
        "color": "#E74C3C",
        "strengths": ["味觉敏锐", "本地美食探索", "餐饮规划"],
        "style_tags": ["味觉记忆", "本地餐饮", "随性觅食", "美食覆盖"],
        "avoid": ["连锁餐厅", "纯游客美食街", "吃饭当空隙的路线"],
        "recommend_strategy": "本地早餐、老字号、小吃街、夜宵、咖啡甜品、餐厅附近顺路景点；路线围绕餐饮节奏展开。",
        "dimensions": {"di": "b", "rl": "b", "ps": "b", "cd": "a"},
    },
}

# ============================================================
# 6 条人格标准答案原型（唯一权威配方）
# ============================================================
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

CODE_TO_PERSONA = {
    "DRPT": "photographer",
    "DRPC": "commando",
    "ILST": "life_artist",
    "IRPT": "architect",
    "IRSC": "enjoyer",
    "ILSC": "foodie",
}

# ============================================================
# 计算逻辑
# ============================================================

def _answer_for_question(answers: dict, qid: int):
    """兼容前端数字 key、字符串 key，以及配方表中的 q1/q2 key。"""
    for key in (str(qid), qid, f"q{qid}"):
        if key in answers:
            return answers[key]
    return None


def _empty_vector() -> dict:
    return {tag: 0.0 for tag in VECTOR_TAGS}


def _add_tags(vector: dict, tags: list, weight: float = 1.0) -> None:
    for tag in tags:
        if tag in vector:
            vector[tag] += weight


def _clamp_slider_value(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 50.0
    return max(0.0, min(100.0, number))


def build_answer_vector(answers: dict) -> dict:
    """
    将用户答案转换为连续标签向量。

    输出 tag：
    - record / immerse
    - refined / local
    - plan / spontaneous
    - cover / deep
    """
    vector = _empty_vector()

    for q in QUESTIONS:
        answer = _answer_for_question(answers, q["id"])
        if answer is None:
            continue

        qtype = q["type"]

        if qtype == "ranking":
            # 排序题：排名越靠前权重越高；第 1 名=n，最后 1 名=1。
            if not isinstance(answer, list):
                continue
            n = len(answer)
            option_map = {opt["id"]: opt for opt in q["options"]}
            for rank, opt_id in enumerate(answer):
                opt = option_map.get(opt_id)
                if not opt:
                    continue
                _add_tags(vector, opt["tags"], n - rank)

        elif qtype == "slider":
            # 滑块题：0=完全倾向 A，100=完全倾向 B。
            value = _clamp_slider_value(answer)
            _add_tags(vector, [q["weight_a"]], (100.0 - value) / 100.0)
            _add_tags(vector, [q["weight_b"]], value / 100.0)

        elif qtype == "single":
            for opt in q["options"]:
                if opt["id"] == answer:
                    _add_tags(vector, opt["tags"], 1.0)
                    break

    return vector


def build_persona_prototypes() -> dict:
    """
    根据 PERSONA_RECIPES 中的标准答案，预计算 6 个人格的原型向量。
    """
    return {
        persona_key: build_answer_vector(recipe["answers"])
        for persona_key, recipe in PERSONA_RECIPES.items()
    }


def vector_distance(user_vector: dict, proto_vector: dict) -> float:
    """
    计算用户向量和人格原型向量之间的欧氏距离。

    后续如果需要增强某些维度区分，可以在这里加权。
    """
    return sum(
        (user_vector.get(tag, 0.0) - proto_vector.get(tag, 0.0)) ** 2
        for tag in VECTOR_TAGS
    ) ** 0.5


def match_persona_by_prototype(answers: dict) -> str:
    """
    返回距离最近的人格 code：DRPT / DRPC / ILST / IRPT / IRSC / ILSC。
    """
    user_vector = build_answer_vector(answers)
    prototypes = build_persona_prototypes()

    best_key = min(
        prototypes,
        key=lambda persona_key: vector_distance(user_vector, prototypes[persona_key]),
    )
    return PERSONA_RECIPES[best_key]["code"]


def calculate_mbti(answers: dict) -> str:
    """
    根据用户答案计算旅行人格 code。

    注意：
    这里不再使用旧的四维硬判定拼码，
    而是使用 6 人格标准配方的最近原型匹配。
    """
    return match_persona_by_prototype(answers)


def get_personality(mbti: str) -> dict:
    """根据旅行人格 code 获取 6 人格之一的详细信息。"""
    persona_key = CODE_TO_PERSONA.get(mbti, "life_artist")
    persona = PERSONALITY_TYPES.get(persona_key, PERSONALITY_TYPES["life_artist"])
    result = dict(persona)
    result["persona_key"] = persona_key
    return result


def get_dimension_label(dimension: str, value: str) -> str:
    """获取维度标签"""
    for dim_info in DIMENSIONS.values():
        if dim_info["pole_a"] == value:
            return dim_info["label_a"]
        if dim_info["pole_b"] == value:
            return dim_info["label_b"]
    return value


def get_dimension_scores(answers: dict) -> dict:
    """
    计算各维度得分（供 API 返回 / 前端展示 / debug）。

    这些 winner 只代表单维展示，最终人格由最近原型匹配决定。
    """
    vector = build_answer_vector(answers)
    scores = {}
    for dim_key, dim_info in DIMENSIONS.items():
        a_score = vector[dim_info["tag_a"]]
        b_score = vector[dim_info["tag_b"]]
        scores[dim_key] = {
            "a": a_score,
            "b": b_score,
            "left": dim_info["tag_a"],
            "right": dim_info["tag_b"],
            "left_score": a_score,
            "right_score": b_score,
            "winner": dim_info["pole_a"] if a_score >= b_score else dim_info["pole_b"],
        }
    return scores
