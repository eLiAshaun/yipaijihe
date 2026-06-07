"""
旅行 MBTI 路由
"""

from flask import Blueprint, jsonify, request
from backend.data.mbti_data import (
    QUESTIONS,
    DIMENSIONS,
    calculate_mbti,
    get_personality,
    get_dimension_scores,
)

mbti_bp = Blueprint("mbti", __name__)


@mbti_bp.route("/questions", methods=["GET"])
def get_questions():
    """获取 MBTI 测试题目"""
    questions = []
    for q in QUESTIONS:
        item = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
        }

        if q["type"] == "single":
            item["options"] = [
                {"id": opt["id"], "text": opt["text"]}
                for opt in q["options"]
            ]
        elif q["type"] == "ranking":
            item["options"] = [
                {"id": opt["id"], "text": opt["text"]}
                for opt in q["options"]
            ]
        elif q["type"] == "slider":
            item["label_a"] = q["label_a"]
            item["label_b"] = q["label_b"]

        # 装饰图
        if q.get("deco_image"):
            item["deco_image"] = q["deco_image"]
            item["deco_position"] = q.get("deco_position", "right")

        questions.append(item)

    return jsonify({"questions": questions})


@mbti_bp.route("/calculate", methods=["POST"])
def calculate():
    """计算 MBTI 结果"""
    data = request.get_json()
    answers = data.get("answers", {})

    if not answers:
        return jsonify({"error": "请提供答案"}), 400

    # 计算 MBTI
    mbti = calculate_mbti(answers)
    personality = get_personality(mbti)

    # 计算各维度得分
    raw_scores = get_dimension_scores(answers)

    # 构建维度信息
    dimensions = []
    dim_keys = ["di", "rl", "ps", "cd"]
    for dim_key in dim_keys:
        dim_info = DIMENSIONS[dim_key]
        a_score = raw_scores[dim_key]["a"]
        b_score = raw_scores[dim_key]["b"]
        total = a_score + b_score

        # 确定该维度的值
        dim_value = dim_info["pole_a"] if a_score >= b_score else dim_info["pole_b"]

        dimensions.append({
            "name": dim_info["name"],
            "value": dim_value,
            "label_a": dim_info["label_a"],
            "label_b": dim_info["label_b"],
            "score_a": round(a_score, 2),
            "score_b": round(b_score, 2),
            "total": round(total, 2),
        })

    return jsonify({
        "mbti": mbti,
        "persona_key": personality.get("persona_key", "life_artist"),
        "personality": personality,
        "scores": raw_scores,
        "dimensions": dimensions,
    })
