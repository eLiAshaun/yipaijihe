"""
全链路测试：分步验证各组件
Step 1: 配置检查
Step 2: LLM 调用 (mimo-v2.5-pro)
Step 3: ASR 语音转写 (mimo-v2.5-asr)
Step 4: LLM 景点提取（不截断文本）
"""
import sys
import json
import tempfile
sys.path.insert(0, ".")

from backend.config import Config


def test_step1_config():
    """验证配置"""
    print("=" * 60)
    print("[Step 1] 检查配置")
    print(f"  LLM_MODEL:     {Config.LLM_MODEL}")
    print(f"  LLM_BASE_URL:  {Config.LLM_BASE_URL}")
    print(f"  LLM_API_KEY:   {'✓ 已配置' if Config.LLM_API_KEY else '✗ 未配置'}")
    print(f"  MIMO_API_KEY:  {'✓ 已配置' if Config.MIMO_API_KEY else '✗ 未配置'}")
    print(f"  MIMO_API_BASE: {Config.MIMO_API_BASE}")
    assert Config.LLM_API_KEY, "LLM_API_KEY 未配置"
    assert Config.MIMO_API_KEY, "MIMO_API_KEY 未配置"
    print("  ✓ 配置检查通过\n")


def test_step2_llm():
    """验证 LLM 可调用（mimo-v2.5-pro）"""
    print("=" * 60)
    print("[Step 2] 测试 LLM 调用 (mimo-v2.5-pro)")
    from backend.services.llm_service import chat_completion
    result = chat_completion(
        [{"role": "user", "content": "你好，请用一句话介绍上海外滩"}],
        temperature=0.3,
        max_tokens=200,
    )
    print(f"  LLM 回复: {result[:200]}")
    assert result, "LLM 调用失败，返回空"
    print("  ✓ LLM 调用成功\n")


def test_step3_asr():
    """验证 ASR 语音转写（mimo-v2.5-asr）"""
    print("=" * 60)
    print("[Step 3] 测试 ASR 转写 (mimo-v2.5-asr)")

    # 用 ffmpeg 生成一段 3 秒的静音测试音频
    import subprocess
    from pathlib import Path

    tmp_dir = Path(tempfile.mkdtemp(prefix="asr_test_"))
    audio_path = tmp_dir / "test.mp3"

    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-acodec", "libmp3lame", "-b:a", "128k", str(audio_path)],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        print(f"  ffmpeg 错误: {proc.stderr[:300]}")
        raise RuntimeError("ffmpeg 生成测试音频失败")

    import base64
    from openai import OpenAI

    client = OpenAI(
        api_key=Config.MIMO_API_KEY,
        base_url=Config.MIMO_API_BASE,
    )

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    print("  → 发送 ASR 请求...")
    completion = client.chat.completions.create(
        model="mimo-v2.5-asr",
        messages=[
            {"role": "system", "content": "你是一个专业的语音转录引擎。请将音频中的所有语音内容逐字逐句完整转录为文字。"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": f"data:audio/mp3;base64,{audio_b64}"},
                    }
                ],
            },
        ],
        temperature=0,
        max_tokens=4096,
        extra_body={"asr_options": {"language": "zh"}},
    )

    result = completion.choices[0].message.content.strip()
    print(f"  ASR 回复: {result[:200]}")
    print("  ✓ ASR 调用成功（模型正常响应）\n")

    # 清理
    audio_path.unlink(missing_ok=True)
    tmp_dir.rmdir()


def test_step4_llm_extract():
    """验证 LLM 提取景点（用模拟转写文本，不截断）"""
    print("=" * 60)
    print("[Step 4] 测试 LLM 提取景点（文本不截断）")

    # 模拟一段较长的转写文本
    mock_transcript = """
    大家好，今天带大家逛逛上海最经典的几个地方。
    首先我们来到的是外滩，这里是上海的标志性景点，可以看到黄浦江对面的陆家嘴天际线，
    东方明珠塔、上海中心大厦、环球金融中心三件套一览无余。
    建议傍晚时分过来，可以看到日落和灯光秀的完美过渡。

    接下来我们去了南京路步行街，这是上海最繁华的商业街之一，
    从外滩一路走到人民广场，沿途有很多老字号商店和美食。

    然后我们打车去了豫园，这里是上海保存最完整的古典园林，
    旁边的城隍庙小吃街非常有名，推荐南翔小笼包，
    还有蟹壳黄、排骨年糕这些上海特色小吃。

    最后我们去了新天地，这里是由石库门老建筑改造的时尚休闲街区，
    有很多精品餐厅和酒吧，晚上来氛围特别好。
    武康路也值得去，梧桐树荫下的法式老洋房特别适合拍照，
    沿途有很多精品咖啡馆。
    """ * 3  # 重复3次模拟长文本

    print(f"  输入文本长度: {len(mock_transcript)} 字（模拟长文本不截断）")

    from backend.services.llm_service import chat_completion

    prompt = f"""从以下抖音旅行视频转写文本中，提取提到的旅行景点/地点/餐厅。

视频标题：上海一日游必去景点

转写文本：
{mock_transcript}

以 JSON 数组输出，每个景点包含 name、keywords（2-4个）、reason（1句话）、lat、lng。
上海知名景点给坐标，不确定为 null。只输出 JSON 数组。"""

    messages = [
        {"role": "system", "content": "你是旅行信息提取助手。只输出 JSON 数组，不要其他文字。"},
        {"role": "user", "content": prompt},
    ]

    result = chat_completion(messages, temperature=0.3, max_tokens=4000)
    print(f"  LLM 原始回复长度: {len(result)} 字")
    print(f"  LLM 原始回复:\n{result[:600]}")

    # 尝试解析 JSON
    if "```json" in result:
        result = result.split("```json")[1].split("```")[0]
    elif "```" in result:
        result = result.split("```")[1].split("```")[0]

    try:
        locations = json.loads(result.strip())
        print(f"\n  ✓ 解析成功，提取到 {len(locations)} 个景点:")
        for loc in locations:
            name = loc.get("name", "?")
            reason = loc.get("reason", "")[:50]
            lat = loc.get("lat", "null")
            lng = loc.get("lng", "null")
            print(f"    - {name} ({lat}, {lng}): {reason}")
    except json.JSONDecodeError as e:
        print(f"\n  ✗ JSON 解析失败: {e}")
        print(f"  原始文本: {result[:300]}")
        raise

    print("\n  ✓ LLM 提取成功\n")
    return locations


def main():
    print("\n🧪 全链路测试开始\n")

    test_step1_config()
    test_step2_llm()
    test_step3_asr()
    test_step4_llm_extract()

    print("=" * 60)
    print("🎉 全链路测试通过！")
    print("  - LLM (mimo-v2.5-pro) ✓")
    print("  - ASR (mimo-v2.5-asr) ✓")
    print("  - 景点提取（不截断） ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
