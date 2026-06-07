from backend.data.mbti_data import PERSONA_RECIPES, calculate_mbti


def test_all_persona_recipes_match_target_codes():
    for recipe in PERSONA_RECIPES.values():
        assert calculate_mbti(recipe["answers"]) == recipe["code"]


def test_all_persona_recipes_are_unique():
    results = {
        calculate_mbti(recipe["answers"])
        for recipe in PERSONA_RECIPES.values()
    }

    assert results == {"DRPT", "DRPC", "ILST", "IRPT", "IRSC", "ILSC"}
