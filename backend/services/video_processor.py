"""
视频处理器：解析抖音分享链接 → 下载 → 听语音（本地 Whisper / MiMo）+ 看画面（多模态大模型）

understand() 是对外的完整流程，每一步都可以单独失败而不影响其他步骤：
没下载成功就只用标题；语音模型没准备好就只看画面；不支持看图就只听语音。
"""

from __future__ import annotations

import io
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

    def _load_share_item(self, share_text: str, timeout=REQUEST_TIMEOUT) -> tuple[dict, str]:
        """解析分享链接，返回抖音页面里的作品数据（视频与图文笔记都支持）"""
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
            resp = requests.get(share_url, headers=HEADERS, allow_redirects=True, timeout=timeout)
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
        resp = requests.get(page_url, headers=HEADERS, timeout=timeout)
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
            raise ValueError("抖音没有返回作品数据（作品可能已删除 / 仅自己可见，或当前网络访问抖音受限）")
        return items[0], video_id

    def extract_audio(self, video_path: Path) -> Path:
        """从视频提取适合 ASR 的轻量音频。"""
        import ffmpeg  # 延迟导入：只有真正处理音频时才需要 ffmpeg
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
        import ffmpeg  # 延迟导入：只有真正处理音频时才需要 ffmpeg
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

    # ------------------------------------------------------------ 新流程 ----
    MAX_VIDEO_MB = 200

    @staticmethod
    def media_of(item: dict) -> dict:
        """从作品数据里取出：标题、视频地址、封面、图文笔记的图片、时长（秒）"""
        video = item.get("video") or {}
        play = (video.get("play_addr") or {}).get("url_list") or []
        cover = ((video.get("origin_cover") or video.get("cover") or {}).get("url_list") or [None])[0]
        images = []
        for img in item.get("images") or []:
            urls = (img or {}).get("url_list") or []
            if urls:
                images.append(urls[-1] if len(urls) > 1 else urls[0])
        return {
            "title": (item.get("desc") or "").strip(),
            "video_url": play[0].replace("playwm", "play") if play and not images else "",
            "cover": cover,
            "images": images,
            "duration": int((video.get("duration") or 0) / 1000),
        }

    def download_video_limited(self, video_url: str) -> Path:
        """下载视频（超过 MAX_VIDEO_MB 直接放弃，避免把磁盘 / 内存占满）"""
        video_path = self.temp_dir / "video.mp4"
        limit = self.MAX_VIDEO_MB * 1024 * 1024
        got = 0
        with requests.get(video_url, headers=HEADERS, stream=True, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            if int(resp.headers.get("Content-Length") or 0) > limit:
                raise ValueError(f"视频超过 {self.MAX_VIDEO_MB}MB，跳过下载")
            with open(video_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    got += len(chunk)
                    if got > limit:
                        raise ValueError(f"视频超过 {self.MAX_VIDEO_MB}MB，跳过下载")
                    f.write(chunk)
        logger.info("视频下载完成: %.1fMB", got / 1024 / 1024)
        return video_path

    @staticmethod
    def fetch_images(urls: list[str], limit: int = 8) -> list[bytes]:
        from backend.services.vision import to_jpeg

        out = []
        for url in urls[:limit]:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=(5, 15))
                resp.raise_for_status()
                jpg = to_jpeg(resp.content)
                if jpg:
                    out.append(jpg)
            except Exception as e:  # noqa: BLE001
                logger.info("图片下载失败: %s", e)
        return out

    @staticmethod
    def frames(video_path: Path, count: int = 8) -> list[bytes]:
        """均匀截取关键帧（PyAV 解码，不需要系统 ffmpeg）。没装 PyAV / Pillow 时返回空列表。"""
        try:
            import av
        except ImportError:
            return []
        from backend.services.vision import to_jpeg

        out = []
        try:
            with av.open(str(video_path)) as container:
                stream = container.streams.video[0]
                duration = (container.duration or 0) / 1_000_000 or float(stream.duration * stream.time_base if stream.duration else 0)
                if duration <= 0:
                    return []
                # 跳过开头 0.5 秒（常是黑屏），在剩余时长里等距取帧
                points = [0.5 + (duration - 0.5) * (i + 0.5) / count for i in range(count)]
                for t in points:
                    container.seek(int(t / stream.time_base), stream=stream, any_frame=False, backward=True)
                    for frame in container.decode(stream):
                        buf = io.BytesIO()
                        frame.to_image().save(buf, "PNG")
                        jpg = to_jpeg(buf.getvalue())
                        if jpg:
                            out.append(jpg)
                        break
        except Exception as e:  # noqa: BLE001
            logger.warning("截取视频画面失败: %s", e)
        return out

    def transcribe_any(self, video_path: Path, hints: list[str]) -> str:
        """按配置选择转写引擎：MiMo 云端（需要系统 ffmpeg 切片）或本地 Whisper"""
        from backend.services import asr

        if asr.engine() == "mimo":
            try:
                segments = self.split_audio(self.extract_audio(video_path))
                return self.transcribe_parallel(segments)
            except Exception as e:  # noqa: BLE001 — 没装 ffmpeg / MiMo 出错：有本地模型就用本地的
                if not (Config.HAS_LOCAL_ASR and asr.status()["ready"]):
                    raise
                logger.warning("MiMo 转写失败，改用本地 Whisper：%s", e)
        return asr.transcribe_local(str(video_path), hints)

    def understand(self, share_text: str, city: str = "", hints: list[str] | None = None, progress=None) -> dict:
        """
        完整流程。返回 {title, transcript, seen(看画面结果), steps(做了哪些), notes(哪些没做以及原因)}；
        读取作品信息失败时抛出异常（调用方可以退回只用分享文案）。
        """
        from backend.services import asr, vision

        step = progress or (lambda *_: None)
        out = {"title": "", "transcript": "", "seen": {"text": [], "places": [], "summary": ""}, "steps": [], "notes": []}
        try:
            step("读取视频信息")
            item, _ = self._load_share_item(share_text, timeout=(5, 12))
            media = self.media_of(item)
            out["title"] = media["title"]
            out["steps"].append("title")

            asr_state = asr.status()
            want_asr = bool(media["video_url"]) and asr_state["ready"]
            want_vision = Config.HAS_VISION
            if media["video_url"] and asr_state["engine"] == "local" and not asr_state["ready"]:
                pct = f"（{asr_state['progress']}%）" if asr_state.get("progress") is not None else ""
                out["notes"].append(f"本地语音模型还在准备{pct}，这次没有听语音" if asr_state["state"] != "error" else "本地语音模型加载失败，这次没有听语音")
            elif media["video_url"] and asr_state["engine"] == "none":
                out["notes"].append("没有开启语音转写（安装 requirements-video.txt 即可免费使用本地 Whisper）")

            images: list[bytes] = []
            if media["images"] and want_vision:
                step("看图片")
                images = self.fetch_images(media["images"])
            elif media["video_url"] and (want_asr or want_vision):
                step("下载视频")
                try:
                    path = self.download_video_limited(media["video_url"])
                except Exception as e:  # noqa: BLE001
                    out["notes"].append(f"视频下载失败（{str(e)[:60]}）")
                    path = None
                if path and want_asr:
                    step("听语音")
                    try:
                        out["transcript"] = self.transcribe_any(path, hints or [])
                        if out["transcript"]:
                            out["steps"].append("asr")
                    except Exception as e:  # noqa: BLE001
                        out["notes"].append(f"语音转写失败（{str(e)[:60]}）")
                if path and want_vision:
                    step("看画面")
                    images = self.frames(path)
            if want_vision and not images and media["cover"]:
                step("看画面")
                images = self.fetch_images([media["cover"]], 1)
            if images:
                seen = vision.read_images(images, media["title"], city)
                if seen["text"] or seen["places"]:
                    out["seen"] = seen
                    out["steps"].append("vision")
            return out
        finally:
            self.cleanup()
