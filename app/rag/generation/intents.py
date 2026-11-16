"""Course QA intents and their response instructions."""

INTENTS = {
    "material_lookup": (
        "定位或查看资料中的原题、章节或原文。",
        "按题号或章节定位，按用户要求展示原文和可见选项，保留原题空格。",
    ),
    "concept_explanation": (
        "解释概念、语法，或说明某个答案为什么成立。",
        "先解释概念或规则，再结合原文说明它如何对应题干线索。",
    ),
    "homework_hint": (
        "用户明确要求提示、思路，或要求先别告诉答案。",
        "只给一个可操作的解题线索。不要写出正确选项、填空答案或完整解法。",
    ),
    "general_qa": (
        "普通课程问答，包括明确要求答案或填完整句子。",
        "直接回答所问内容。",
    ),
}


def routing_instructions() -> str:
    choices = "\n".join(f"{name}：{description}" for name, (description, _) in INTENTS.items())
    return (
        "为课程问答生成一条短检索查询，并识别用户意图。保留题号、人名和英文短语，"
        "可补充同义表达。用户明确要求提示时优先选择 homework_hint。"
        '只输出 JSON {"query":"...","intent":"..."}。intent 必须从以下选项中选择。\n'
        + choices
    )
