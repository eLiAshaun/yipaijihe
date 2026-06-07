"""
视频处理器 - 下载视频、提取音频、切片并行转写
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ffmpeg
import requests
from openai import OpenAI

from backend.config import Config

logger = logging.getLogger(__name__)

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1"
}

# ASR 配置
REQUEST_TIMEOUT = (10, 60)
ASR_MODEL = Config.MIMO_MODEL
ASR_SEGMENT_DURATION = max(30, Config.MIMO_ASR_SEGMENT_DURATION)  # 每段 90 秒
ASR_MAX_WORKERS = max(1, Config.MIMO_ASR_MAX_WORKERS)  # 单个视频内的并行转写线程数
ASR_GLOBAL_MAX_CONCURRENT = max(1, Config.MIMO_ASR_GLOBAL_MAX_CONCURRENT)
ASR_AUDIO_BITRATE = Config.MIMO_ASR_AUDIO_BITRATE
ASR_AUDIO_SAMPLE_RATE = max(8000, Config.MIMO_ASR_SAMPLE_RATE)
ASR_AUDIO_CHANNELS = max(1, Config.MIMO_ASR_CHANNELS)
_ASR_SEMAPHORE = threading.BoundedSemaphore(ASR_GLOBAL_MAX_CONCURRENT)

TRANSCRIBE_SYSTEM_PROMPT = """你是一个专业的语音转录引擎。请将音频中的所有语音内容逐字逐句完整转录为文字。

要求：
- 完整转录音频中的每一句话，不要遗漏任何内容
- 不要总结、不要缩写、不要省略
- 保留口语化表达、语气词
- 适当添加标点符号
- 输出纯文本，不要添加任何额外说明或格式"""


class VideoProcessor:
    """视频处理器：下载 → 提取音频 → 切片 → 并行转写"""

    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="video_proc_"))
        self._asr_client = None

    @property
    def asr_client(self):
        if self._asr_client is None:
            api_key = Config.MIMO_API_KEY
            if not api_key:
                raise ValueError("未配置 MIMO_API_KEY，无法进行语音转写")
            self._asr_client = OpenAI(
                api_key=api_key,
                base_url=Config.MIMO_API_BASE,
                timeout=Config.MIMO_ASR_REQUEST_TIMEOUT,
                max_retries=Config.MIMO_ASR_MAX_RETRIES,
            )
        return self._asr_client

    def cleanup(self):
        if hasattr(self, "temp_dir") and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __del__(self):
        self.cleanup()

    def parse_share_url(self, share_text: str) -> dict:
        """从分享文本中提取视频信息（复用 MCP server 逻辑）"""
        urls = re.findall(
            r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
            share_text,
        )
        if not urls:
            raise ValueError("未找到有效的分享链接")

        share_url = urls[0]

        # 如果是完整视频链接，直接提取 ID
        share_type = "video"
        video_id_match = re.search(r"(video|note)/(\d+)", share_url)
        if video_id_match:
            share_type = video_id_match.group(1)
            video_id = video_id_match.group(2)
        else:
            # 短链接跟随重定向
            resp = requests.get(share_url, headers=HEADERS, allow_redirects=True, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            final_url = resp.url
            if "douyin.com" in final_url and "/video/" not in final_url and "/note/" not in final_url:
                raise ValueError(f"链接已失效，重定向到: {final_url}")
            share_type = "note" if "/note/" in final_url else "video"
            video_id = final_url.split("?")[0].strip("/").split("/")[-1]
            if not video_id.isdigit():
                raise ValueError(f"无法提取视频ID: {share_url}")

        # 获取视频页面
        page_url = f"https://www.iesdouyin.com/share/{share_type}/{video_id}"
        resp = requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
        match = pattern.search(resp.text)
        if not match:
            raise ValueError("从HTML中解析视频信息失败")

        data = json.loads(match.group(1).strip())
        loader_data = data.get("loaderData", {})
        page = loader_data.get("video_(id)/page") or loader_data.get("note_(id)/page") or {}
        info = page.get("videoInfoRes", {})
        items = info.get("item_list", [])
        if not items:
            raise ValueError(f"视频不存在或已被删除 (ID: {video_id})")

        item = items[0]
        video = item.get("video") or {}
        url_list = video.get("play_addr", {}).get("url_list", [])
        if not url_list:
            raise ValueError("该链接没有可下载的视频音轨，无法转写")
        video_url = url_list[0].replace("playwm", "play")
        desc = re.sub(r'[\\/:*?"<>|]', "_", item.get("desc", "").strip() or f"douyin_{video_id}")

        return {"url": video_url, "title": desc, "video_id": video_id}

    def download_video(self, video_url: str) -> Path:
        """下载视频到临时目录"""
        video_path = self.temp_dir / "video.mp4"
        with requests.get(video_url, headers=HEADERS, stream=True, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        logger.info(f"视频下载完成: {video_path.stat().st_size / 1024 / 1024:.1f}MB")
        return video_path

    def extract_audio(self, video_path: Path) -> Path:
        """从视频提取适合 ASR 的轻量音频。"""
        audio_path = video_path.with_suffix(".mp3")
        (
            ffmpeg.input(str(video_path))
            .output(
                str(audio_path),
                acodec="libmp3lame",
                audio_bitrate=ASR_AUDIO_BITRATE,
                ac=ASR_AUDIO_CHANNELS,
                ar=ASR_AUDIO_SAMPLE_RATE,
                vn=None,
            )
            .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        )
        logger.info(f"音频提取完成: {audio_path.stat().st_size / 1024 / 1024:.1f}MB")
        return audio_path

    def split_audio(self, audio_path: Path, segment_duration: int = ASR_SEGMENT_DURATION) -> list[Path]:
        """将音频切片为多个片段"""
        probe = ffmpeg.probe(str(audio_path))
        duration = float(probe["format"]["duration"])
        num_segments = math.ceil(duration / segment_duration)

        if num_segments <= 1:
            return [audio_path]

        segments = []
        for i in range(num_segments):
            start = i * segment_duration
            seg_path = self.temp_dir / f"segment_{i}.mp3"
            (
                ffmpeg.input(str(audio_path), ss=start, t=segment_duration)
                .output(
                    str(seg_path),
                    acodec="libmp3lame",
                    audio_bitrate=ASR_AUDIO_BITRATE,
                    ac=ASR_AUDIO_CHANNELS,
                    ar=ASR_AUDIO_SAMPLE_RATE,
                    vn=None,
                )
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            segments.append(seg_path)

        logger.info(f"音频切片完成: {duration:.0f}s → {num_segments} 段")
        return segments

    def _transcribe_segment(self, segment_path: Path, index: int, total: int) -> tuple[int, str]:
        """转写单个音频片段（在线程中运行）"""
        with open(segment_path, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        logger.info(f"[ASR] 开始转写第 {index+1}/{total} 段")

        with _ASR_SEMAPHORE:
            completion = self.asr_client.chat.completions.create(
                model=ASR_MODEL,
                messages=[
                    {"role": "system", "content": TRANSCRIBE_SYSTEM_PROMPT},
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

        # 剥离模型可能回显的 system prompt
        if result.startswith("你是一个专业"):
            for sep in ["\n", "。"]:
                idx = result.find(sep)
                if idx != -1 and idx < 300:
                    result = result[idx + 1:].strip()
                    break

        logger.info(f"[ASR] 第 {index+1}/{total} 段转写完成，{len(result)} 字")
        return index, result

    def transcribe_parallel(self, segments: list[Path]) -> str:
        """并行转写所有音频片段，按顺序合并"""
        if len(segments) == 1:
            _, text = self._transcribe_segment(segments[0], 0, 1)
            return text

        results = [None] * len(segments)

        with ThreadPoolExecutor(max_workers=min(ASR_MAX_WORKERS, len(segments))) as executor:
            futures = {
                executor.submit(self._transcribe_segment, seg, i, len(segments)): i
                for i, seg in enumerate(segments)
            }
            for future in as_completed(futures):
                try:
                    index, text = future.result()
                    results[index] = text
                except Exception as e:
                    idx = futures[future]
                    logger.error(f"[ASR] 第 {idx+1} 段转写失败: {e}")
                    results[idx] = ""

        # 按顺序合并
        return "\n".join(r for r in results if r)

    def process_video(self, share_url: str) -> tuple[str, str, str]:
        """
        完整流程：解析 → 下载 → 提取音频 → 切片 → 并行转写

        Returns:
            (transcript, video_title, error_msg)
        """
        video_title = ""
        try:
            # 1. 解析视频信息
            logger.info(f"[VideoProcessor] 解析视频链接...")
            video_info = self.parse_share_url(share_url)
            video_title = video_info["title"]
            logger.info(f"[VideoProcessor] 视频标题: {video_title}")

            # 2. 下载视频
            logger.info(f"[VideoProcessor] 下载视频...")
            video_path = self.download_video(video_info["url"])

            # 3. 提取音频
            logger.info(f"[VideoProcessor] 提取音频...")
            audio_path = self.extract_audio(video_path)

            # 4. 切片
            logger.info(f"[VideoProcessor] 切片音频...")
            segments = self.split_audio(audio_path)

            # 5. 并行转写
            logger.info(f"[VideoProcessor] 并行转写 {len(segments)} 个片段...")
            transcript = self.transcribe_parallel(segments)

            if not transcript.strip():
                return None, video_title, "ASR 未返回有效文本"

            return transcript, video_title, ""

        except Exception as e:
            logger.error(f"[VideoProcessor] 处理失败: {e}")
            return None, video_title, str(e)
        finally:
            self.cleanup()
