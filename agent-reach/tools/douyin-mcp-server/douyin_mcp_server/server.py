#!/usr/bin/env python3
"""
抖音无水印视频下载并提取文本的 MCP 服务器

该服务器提供以下功能：
1. 解析抖音分享链接获取无水印视频链接
2. 下载视频并提取音频
3. 从音频中提取文本内容
4. 自动清理中间文件
"""

import os
import re
import json
import base64
import requests
import tempfile
import asyncio
from pathlib import Path
from typing import Optional, Tuple
import ffmpeg
from tqdm.asyncio import tqdm
from openai import OpenAI

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context


# 创建 MCP 服务器实例
mcp = FastMCP("Douyin MCP Server",
              dependencies=["requests", "ffmpeg-python", "tqdm", "openai"])

# 请求头，模拟移动端访问
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}

# 默认 API 配置（支持环境变量覆盖）
DEFAULT_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-asr")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1")

# 转录提示词 — 强制逐字完整转录
TRANSCRIBE_SYSTEM_PROMPT = """你是一个专业的语音转录引擎。请将音频中的所有语音内容逐字逐句完整转录为文字。

要求：
- 完整转录音频中的每一句话，不要遗漏任何内容
- 不要总结、不要缩写、不要省略
- 保留口语化表达、语气词（如"嗯"、"啊"、"呢"、"吧"等）
- 适当添加标点符号
- 如果有多个说话人，不需要区分说话人，直接连续转录
- 输出纯文本，不要添加任何额外说明或格式"""


class DouyinProcessor:
    """抖音视频处理器"""
    
    def __init__(self, api_key: str, model: Optional[str] = None):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.temp_dir = Path(tempfile.mkdtemp())
        self._client = None

    @property
    def client(self):
        """延迟初始化 MiMo API 客户端（仅在需要时创建）"""
        if self._client is None:
            if not self.api_key:
                raise ValueError("需要 API Key 才能调用 MiMo ASR")
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=MIMO_API_BASE
            )
        return self._client
    
    def __del__(self):
        """清理临时目录"""
        import shutil
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def parse_share_url(self, share_text: str) -> dict:
        """从分享文本中提取无水印视频链接"""
        # 提取分享链接
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")

        share_url = urls[0]

        # 如果是完整视频链接（包含 video ID），直接使用
        video_id_match = re.search(r'(?:video|note)/(\d+)', share_url)
        if video_id_match:
            video_id = video_id_match.group(1)
        else:
            # 短链接需要跟随重定向获取真实URL
            share_response = requests.get(share_url, headers=HEADERS, allow_redirects=True)
            final_url = share_response.url

            # 验证重定向是否到达了视频页面（而非首页）
            if 'douyin.com' in final_url and '/video/' not in final_url and '/note/' not in final_url:
                raise ValueError(f"链接已失效或不是有效的视频链接，重定向到: {final_url}")

            video_id = final_url.split("?")[0].strip("/").split("/")[-1]

            # 验证 video_id 是数字
            if not video_id.isdigit():
                raise ValueError(f"无法从链接中提取视频ID，可能是链接已过期或无效: {share_url}")

        share_url = f'https://www.iesdouyin.com/share/video/{video_id}'

        # 获取视频页面内容
        response = requests.get(share_url, headers=HEADERS)
        response.raise_for_status()

        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(response.text)

        if not find_res or not find_res.group(1):
            raise ValueError("从HTML中解析视频信息失败")

        # 解析JSON数据
        json_data = json.loads(find_res.group(1).strip())
        VIDEO_ID_PAGE_KEY = "video_(id)/page"
        NOTE_ID_PAGE_KEY = "note_(id)/page"

        if VIDEO_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][VIDEO_ID_PAGE_KEY]["videoInfoRes"]
        elif NOTE_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][NOTE_ID_PAGE_KEY]["videoInfoRes"]
        else:
            raise Exception("无法从JSON中解析视频或图集信息")

        # 检查 item_list 是否为空
        item_list = original_video_info.get("item_list", [])
        if not item_list:
            status_code = original_video_info.get("status_code", -1)
            raise ValueError(f"视频不存在或已被删除（状态码: {status_code}，视频ID: {video_id}）")

        data = item_list[0]

        # 获取视频信息
        video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        desc = data.get("desc", "").strip() or f"douyin_{video_id}"
        
        # 替换文件名中的非法字符
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)
        
        return {
            "url": video_url,
            "title": desc,
            "video_id": video_id
        }
    
    async def download_video(self, video_info: dict, ctx: Context) -> Path:
        """异步下载视频到临时目录"""
        filename = f"{video_info['video_id']}.mp4"
        filepath = self.temp_dir / filename
        
        ctx.info(f"正在下载视频: {video_info['title']}")
        
        response = requests.get(video_info['url'], headers=HEADERS, stream=True)
        response.raise_for_status()
        
        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))
        
        # 异步下载文件，显示进度
        with open(filepath, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = downloaded / total_size
                        await ctx.report_progress(downloaded, total_size)
        
        ctx.info(f"视频下载完成: {filepath}")
        return filepath
    
    def extract_audio(self, video_path: Path) -> Path:
        """从视频文件中提取音频"""
        audio_path = video_path.with_suffix('.mp3')
        
        try:
            (
                ffmpeg
                .input(str(video_path))
                .output(str(audio_path), acodec='libmp3lame', q=0)
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            return audio_path
        except Exception as e:
            raise Exception(f"提取音频时出错: {str(e)}")
    
    def extract_text_from_video_url(self, video_url: str) -> str:
        """从视频URL中提取文字（使用小米 MiMo ASR API）"""
        try:
            # 下载视频到临时文件
            video_path = self.temp_dir / "temp_video.mp4"
            response = requests.get(video_url, headers=HEADERS, stream=True)
            response.raise_for_status()
            with open(video_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 用 ffmpeg 提取音频为 mp3（192kbps 高质量）
            audio_path = self.temp_dir / "temp_audio.mp3"
            (
                ffmpeg
                .input(str(video_path))
                .output(str(audio_path), acodec='libmp3lame', audio_bitrate='192k')
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )

            # 检查 base64 后大小（MiMo 限制 10MB）
            audio_size = audio_path.stat().st_size
            b64_size = audio_size * 4 // 3 + 4  # 估算 base64 大小
            probe = ffmpeg.probe(str(audio_path))
            duration = float(probe['format']['duration'])
            print(f"[ASR] 音频: {duration:.0f}s, {audio_size/1024/1024:.2f}MB, b64≈{b64_size/1024/1024:.2f}MB", flush=True)

            if b64_size > 10 * 1024 * 1024:
                # 超过 10MB，分段处理
                return self._transcribe_long_audio(audio_path)
            else:
                # 直接转录
                return self._transcribe_audio(audio_path)

        except Exception as e:
            raise Exception(f"提取文字时出错: {str(e)}")

    def _transcribe_audio(self, audio_path: Path) -> str:
        """转录单个音频文件（完整逐字转录）"""
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # 获取音频时长用于日志
        probe = ffmpeg.probe(str(audio_path))
        duration = float(probe['format']['duration'])

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": TRANSCRIBE_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/mp3;base64,{audio_b64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0,
            max_tokens=4096,
            extra_body={
                "asr_options": {
                    "language": "zh"
                }
            }
        )
        result = completion.choices[0].message.content
        usage = completion.usage

        # 剥离模型可能回显的 system prompt
        if result.startswith("你是一个专业"):
            for sep in ["\n", "。"]:
                idx = result.find(sep)
                if idx != -1 and idx < 300:
                    result = result[idx + 1:].strip()
                    break

        print(f"[ASR] {duration:.0f}s音频 → {usage.completion_tokens}tokens输出", flush=True)
        return result

    def _transcribe_long_audio(self, audio_path: Path) -> str:
        """分段转录长音频（每段2分钟，确保高精度）"""
        import math
        # 获取音频时长
        probe = ffmpeg.probe(str(audio_path))
        duration = float(probe['format']['duration'])
        # 每段 90 秒，提升识别精度
        segment_duration = 90
        num_segments = math.ceil(duration / segment_duration)

        print(f"[ASR] 音频{duration:.0f}s，分为{num_segments}段处理", flush=True)
        texts = []
        for i in range(num_segments):
            start = i * segment_duration
            segment_path = self.temp_dir / f"segment_{i}.mp3"
            (
                ffmpeg
                .input(str(audio_path), ss=start, t=segment_duration)
                .output(str(segment_path), acodec='libmp3lame', audio_bitrate='128k')
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            print(f"[ASR] 处理第{i+1}/{num_segments}段 ({start}s-{start+segment_duration}s)", flush=True)
            text = self._transcribe_audio(segment_path)
            texts.append(text)
            segment_path.unlink(missing_ok=True)

        return "\n".join(texts)
    
    def cleanup_files(self, *file_paths: Path):
        """清理指定的文件"""
        for file_path in file_paths:
            if file_path.exists():
                file_path.unlink()


@mcp.tool()
def get_douyin_download_link(share_link: str) -> str:
    """
    获取抖音视频的无水印下载链接
    
    参数:
    - share_link: 抖音分享链接或包含链接的文本
    
    返回:
    - 包含下载链接和视频信息的JSON字符串
    """
    try:
        processor = DouyinProcessor("")  # 获取下载链接不需要API密钥
        video_info = processor.parse_share_url(share_link)
        
        return json.dumps({
            "status": "success",
            "video_id": video_info["video_id"],
            "title": video_info["title"],
            "download_url": video_info["url"],
            "description": f"视频标题: {video_info['title']}",
            "usage_tip": "可以直接使用此链接下载无水印视频"
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"获取下载链接失败: {str(e)}"
        }, ensure_ascii=False, indent=2)


@mcp.tool()
async def extract_douyin_text(
    share_link: str,
    model: Optional[str] = None,
    ctx: Context = None
) -> str:
    """
    从抖音分享链接提取视频中的文本内容

    参数:
    - share_link: 抖音分享链接或包含链接的文本
    - model: 语音识别模型（可选，默认使用mimo-v2.5-asr）

    返回:
    - 提取的文本内容

    注意: 需要设置环境变量 MIMO_API_KEY
    """
    try:
        # 从环境变量获取API密钥
        api_key = os.getenv('MIMO_API_KEY')
        if not api_key:
            raise ValueError("未设置环境变量 MIMO_API_KEY，请在配置中添加小米 MiMo API 密钥")
        
        processor = DouyinProcessor(api_key, model)
        
        # 解析视频链接
        ctx.info("正在解析抖音分享链接...")
        video_info = processor.parse_share_url(share_link)
        
        # 直接使用视频URL进行文本提取
        ctx.info("正在从视频中提取文本...")
        text_content = processor.extract_text_from_video_url(video_info['url'])
        
        ctx.info("文本提取完成!")
        return text_content
        
    except Exception as e:
        ctx.error(f"处理过程中出现错误: {str(e)}")
        raise Exception(f"提取抖音视频文本失败: {str(e)}")


@mcp.tool()
def parse_douyin_video_info(share_link: str) -> str:
    """
    解析抖音分享链接，获取视频基本信息
    
    参数:
    - share_link: 抖音分享链接或包含链接的文本
    
    返回:
    - 视频信息（JSON格式字符串）
    """
    try:
        processor = DouyinProcessor("")  # 不需要API密钥来解析链接
        video_info = processor.parse_share_url(share_link)
        
        return json.dumps({
            "video_id": video_info["video_id"],
            "title": video_info["title"],
            "download_url": video_info["url"],
            "status": "success"
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": str(e)
        }, ensure_ascii=False, indent=2)


@mcp.resource("douyin://video/{video_id}")
def get_video_info(video_id: str) -> str:
    """
    获取指定视频ID的详细信息
    
    参数:
    - video_id: 抖音视频ID
    
    返回:
    - 视频详细信息
    """
    share_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    try:
        processor = DouyinProcessor("")
        video_info = processor.parse_share_url(share_url)
        return json.dumps(video_info, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取视频信息失败: {str(e)}"


@mcp.prompt()
def douyin_text_extraction_guide() -> str:
    """抖音视频文本提取使用指南"""
    return """
# 抖音视频文本提取使用指南

## 功能说明
这个MCP服务器可以从抖音分享链接中提取视频的文本内容，以及获取无水印下载链接。

## 环境变量配置
请确保设置了以下环境变量：
- `MIMO_API_KEY`: 小米 MiMo API 密钥

## 使用步骤
1. 复制抖音视频的分享链接
2. 在Claude Desktop配置中设置环境变量 API_KEY
3. 使用相应的工具进行操作

## 工具说明
- `extract_douyin_text`: 完整的文本提取流程（需要API密钥）
- `get_douyin_download_link`: 获取无水印视频下载链接（无需API密钥）
- `parse_douyin_video_info`: 仅解析视频基本信息
- `douyin://video/{video_id}`: 获取指定视频的详细信息

## Claude Desktop 配置示例
```json
{
  "mcpServers": {
    "douyin-mcp": {
      "command": "uvx",
      "args": ["douyin-mcp-server"],
      "env": {
        "MIMO_API_KEY": "your-mimo-api-key-here"
      }
    }
  }
}
```

## 注意事项
- 需要提供有效的小米 MiMo API 密钥（通过环境变量 MIMO_API_KEY）
- 使用小米 MiMo mimo-v2.5-asr 模型进行语音识别
- 支持大部分抖音视频格式
- 获取下载链接无需API密钥
"""


def main():
    """启动MCP服务器"""
    mcp.run()


if __name__ == "__main__":
    main()