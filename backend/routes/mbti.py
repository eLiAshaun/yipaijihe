"""
旅行 MBTI 路由
"""

from flask import Blueprint, jsonify, request
from backend.data.mbti_data import (
    QUESTIONS,
    DIMENSIONS,
    PERSONA_RECIPES,
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


def _result_for(answers: dict) -> dict:
    mbti = calculate_mbti(answers)
    personality = get_personality(mbti)
    raw_scores = get_dimension_scores(answers)
    dimensions = []
    for dim_key in ("di", "rl", "ps", "cd"):
        dim_info = DIMENSIONS[dim_key]
        a_score = raw_scores[dim_key]["a"]
        b_score = raw_scores[dim_key]["b"]
        dimensions.append({
            "name": dim_info["name"],
            "value": dim_info["pole_a"] if a_score >= b_score else dim_info["pole_b"],
            "label_a": dim_info["label_a"],
            "label_b": dim_info["label_b"],
            "score_a": round(a_score, 2),
            "score_b": round(b_score, 2),
            "total": round(a_score + b_score, 2),
        })
    return {
        "mbti": mbti,
        "persona_key": personality.get("persona_key", "life_artist"),
        "personality": personality,
        "scores": raw_scores,
        "dimensions": dimensions,
    }


@mbti_bp.route("/personas", methods=["GET"])
def list_personas():
    """6 种旅行人格，供「我知道自己是哪种」直接选择"""
    out = []
    for recipe in PERSONA_RECIPES.values():
        p = get_personality(recipe["code"])
        out.append({k: p.get(k) for k in ("name", "full_name", "emoji", "subtitle", "image", "style_tags")} | {"code": recipe["code"]})
    return jsonify({"personas": out})


@mbti_bp.route("/pick", methods=["POST"])
def pick_persona():
    """直接选择人格：用该人格的标准答案计算，结果结构与答题一致"""
    code = ((request.get_json(silent=True) or {}).get("code") or "").upper()
    recipe = next((r for r in PERSONA_RECIPES.values() if r["code"] == code), None)
    if not recipe:
        return jsonify({"error": "没有这种旅行人格"}), 400
    return jsonify(_result_for(recipe["answers"]))


@mbti_bp.route("/calculate", methods=["POST"])
def calculate():
    """计算 MBTI 结果"""
    data = request.get_json(silent=True) or {}
    answers = data.get("answers", {})
    if not answers:
        return jsonify({"error": "请提供答案"}), 400
    return jsonify(_result_for(answers))
