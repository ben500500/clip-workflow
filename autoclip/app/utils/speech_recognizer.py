"""
语音识别工具。

支持两种方式（通过 SpeechRecognitionConfig.method 或环境变量选择）：
  - aliyun_speech: 阿里云百炼 DashScope qwen3-asr-flash（默认）
  - whisper: 本地 faster-whisper（CPU 推理，无需 API Key，可离线）
"""
import logging
import subprocess
import os
import shutil
import tempfile
from typing import Optional, List, Dict, Any
from pathlib import Path
from enum import Enum
import requests
from dataclasses import dataclass
from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)

# 阿里云百炼 qwen3-asr-flash 单次请求的限制：
#   - 时长上限约 300 秒；16kHz 单声道 16bit PCM 文件大小上限约 10MB。
# 16kHz 单声道 16bit PCM 每秒 32000 字节，270s → 8.64MB，安全且兼顾分段数量。
# 可通过环境变量 AUTOCLIP_ASR_SEGMENT_SECONDS 覆盖。
SEGMENT_SECONDS = int(os.getenv("AUTOCLIP_ASR_SEGMENT_SECONDS", "270"))


class SpeechRecognitionMethod(str, Enum):
    """语音识别方法枚举"""
    ALIYUN_SPEECH = "aliyun_speech"
    WHISPER = "whisper"


class LanguageCode(str, Enum):
    """支持的语言代码"""
    CHINESE_SIMPLIFIED = "zh"
    ENGLISH = "en"
    AUTO = "auto"


@dataclass
class SpeechRecognitionConfig:
    """语音识别配置"""
    method: SpeechRecognitionMethod = SpeechRecognitionMethod.ALIYUN_SPEECH
    language: LanguageCode = LanguageCode.AUTO
    model: str = "base"
    timeout: int = 0  # 超时时间（秒），0表示使用默认 300s
    output_format: str = "srt"
    enable_timestamps: bool = True
    enable_punctuation: bool = True
    enable_speaker_diarization: bool = False
    enable_fallback: bool = False
    fallback_method: SpeechRecognitionMethod = SpeechRecognitionMethod.ALIYUN_SPEECH

    # API配置
    openai_api_key: Optional[str] = None
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = None
    google_credentials_path: Optional[str] = None
    aliyun_access_key: Optional[str] = None
    aliyun_access_secret: Optional[str] = None
    custom_api_url: Optional[str] = None
    custom_api_key: Optional[str] = None


class SpeechRecognitionError(Exception):
    """语音识别错误"""
    pass


class SpeechRecognizer:
    """语音识别器（阿里云百炼 qwen3-asr-flash）"""

    def __init__(self, config: Optional[SpeechRecognitionConfig] = None):
        self.config = config or SpeechRecognitionConfig()
        self.available_methods = {
            SpeechRecognitionMethod.ALIYUN_SPEECH: self._check_aliyun_speech_availability(),
            SpeechRecognitionMethod.WHISPER: self._check_whisper_availability(),
        }

    def _check_whisper_availability(self) -> bool:
        """检查本地 faster-whisper 是否可用（无需 API Key）。"""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            logger.warning("faster-whisper 未安装，whisper 方式不可用")
            return False

    def _check_aliyun_speech_availability(self) -> bool:
        """检查阿里云语音识别是否可用"""
        try:
            access_key = (os.getenv("ALIYUN_API_KEY")
                          or os.getenv("DASHSCOPE_API_KEY")
                          or os.getenv("API_DASHSCOPE_API_KEY")
                          or (self.config.aliyun_access_key if hasattr(self, 'config') else None))
            return bool(access_key)
        except Exception:
            return False

    def _extract_audio_from_video(self, video_path: Path, output_dir: Path) -> Path:
        """从视频文件中提取 16kHz 单声道 PCM wav"""
        try:
            ffmpeg_bin = get_ffmpeg_path()
            result = subprocess.run([ffmpeg_bin, '-version'],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise SpeechRecognitionError("ffmpeg不可用，请安装ffmpeg")

            audio_filename = f"{video_path.stem}_audio.wav"
            audio_path = output_dir / audio_filename

            if audio_path.exists():
                logger.info(f"音频文件已存在: {audio_path}")
                return audio_path

            logger.info(f"正在从视频提取音频: {video_path} -> {audio_path}")
            cmd = [
                ffmpeg_bin,
                '-i', str(video_path),
                '-vn',
                '-acodec', 'pcm_s16le',
                '-ar', '16000',
                '-ac', '1',
                '-y',
                str(audio_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise SpeechRecognitionError(f"音频提取失败: {result.stderr}")
            if not audio_path.exists():
                raise SpeechRecognitionError("音频提取失败，输出文件不存在")

            logger.info(f"音频提取成功: {audio_path}")
            return audio_path

        except subprocess.TimeoutExpired:
            raise SpeechRecognitionError("音频提取超时")
        except Exception as e:
            raise SpeechRecognitionError(f"音频提取失败: {e}")

    def generate_subtitle(self, video_path: Path, output_path: Optional[Path] = None,
                          config: Optional[SpeechRecognitionConfig] = None) -> Path:
        """
        生成字幕文件（仅支持 aliyun_speech）

        Args:
            video_path: 视频文件路径
            output_path: 输出字幕文件路径
            config: 语音识别配置

        Returns:
            生成的字幕文件路径
        """
        if not video_path.exists():
            raise SpeechRecognitionError(f"视频文件不存在: {video_path}")

        config = config or self.config

        if output_path is None:
            output_path = video_path.parent / f"{video_path.stem}.{config.output_format}"

        if config.method == SpeechRecognitionMethod.ALIYUN_SPEECH:
            return self._generate_subtitle_aliyun_speech(video_path, output_path, config)
        if config.method == SpeechRecognitionMethod.WHISPER:
            return self._generate_subtitle_whisper(video_path, output_path, config)
        raise SpeechRecognitionError(f"不支持的语音识别方法: {config.method}")

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        if seconds is None or seconds < 0:
            seconds = 0.0
        ms = int(round(seconds * 1000.0))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @classmethod
    def _segments_to_srt(cls, segments: List[Dict[str, Any]]) -> str:
        lines = []
        for i, seg in enumerate(segments, start=1):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            start = cls._format_srt_timestamp(seg.get("start", 0.0))
            end = cls._format_srt_timestamp(seg.get("end", 0.0))
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _get_media_duration(media_path: Path) -> float:
        """获取媒体文件时长（秒），失败时回退到 30.0。"""
        try:
            result = subprocess.run(
                [get_ffprobe_path(), '-v', 'error',
                 '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(media_path)],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 30.0

    def _aliyun_speech_transcribe_audio(self, audio_path: Path, config: SpeechRecognitionConfig,
                                        api_key: str) -> str:
        """
        调用阿里云百炼 qwen3-asr-flash 转写单个音频文件，返回纯文本。
        无语音内容时返回空字符串（不抛异常，交由上层生成空 SRT）。
        """
        import base64

        with open(audio_path, 'rb') as audio_file:
            audio_data = base64.b64encode(audio_file.read()).decode('utf-8')

        request_data = {
            "model": "qwen3-asr-flash",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"audio": f"data:audio/wav;base64,{audio_data}"}
                        ]
                    }
                ]
            },
            "parameters": {
                "result_format": "text"
            }
        }

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = requests.post(
            'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation',
            headers=headers,
            json=request_data,
            timeout=config.timeout if config.timeout > 0 else 300
        )

        if response.status_code == 200:
            result = response.json()
            transcript = None
            try:
                choices = result.get('output', {}).get('choices') or []
                if choices:
                    content = (choices[0].get('message') or {}).get('content')
                    if isinstance(content, list) and content:
                        transcript = content[0].get('text')
                    elif isinstance(content, str):
                        transcript = content
            except (KeyError, IndexError, TypeError, AttributeError):
                transcript = None

            if not transcript:
                logger.warning("阿里云语音识别返回结果为空（可能为静音视频）")
                return ""
            return transcript
        else:
            error_detail = (response.json().get('message', '未知错误')
                            if response.headers.get('content-type', '').startswith('application/json')
                            else response.text)
            raise SpeechRecognitionError(
                f"阿里云语音识别API调用失败: {response.status_code} - {error_detail}")

    def _generate_subtitle_whisper(self, video_path: Path, output_path: Path,
                                   config: SpeechRecognitionConfig) -> Path:
        """使用本地 faster-whisper 生成字幕（CPU 推理，无需 API Key）。

        模型通过环境变量 WHISPER_MODEL 选择（默认 small），例如 small / medium / large-v3。
        可通过 HF_ENDPOINT=https://hf-mirror.com 走国内镜像下载模型。
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise SpeechRecognitionError(
                "faster-whisper 未安装，无法使用 whisper 方式。"
                "请先 pip install faster-whisper") from e

        model_name = os.getenv("WHISPER_MODEL", "small").strip()
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        device = os.getenv("WHISPER_DEVICE", "cpu")

        logger.info("加载 faster-whisper 模型: %s (device=%s, compute=%s)", model_name, device, compute_type)
        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        with tempfile.TemporaryDirectory() as tmp:
            audio_path = self._extract_audio_from_video(video_path, Path(tmp))
            language = config.language.value if config.language != LanguageCode.AUTO else None
            logger.info("开始 whisper 转写: %s (language=%s)", audio_path, language or "auto")
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=True,
                beam_size=5,
            )
            seg_list = [
                {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
                for s in segments
                if s.text and s.text.strip()
            ]
            logger.info("whisper 转写完成: %d 段（detected language=%s）", len(seg_list), info.language or "?")

        srt_content = self._segments_to_srt(seg_list)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(srt_content, encoding="utf-8")
        if not seg_list:
            logger.warning("whisper 未识别到语音内容（可能为静音视频）")
        return output_path

    def _generate_subtitle_aliyun_speech(self, video_path: Path, output_path: Path,
                                         config: SpeechRecognitionConfig) -> Path:
        """使用阿里云语音识别生成字幕（长音频自动分段转写，按时间偏移合成 SRT）"""
        if not self.available_methods.get(SpeechRecognitionMethod.ALIYUN_SPEECH):
            raise SpeechRecognitionError("阿里云语音识别不可用，请配置API Key")

        try:
            logger.info(f"开始使用阿里云语音识别生成字幕: {video_path}")

            if not video_path.exists():
                raise SpeechRecognitionError(f"视频文件不存在: {video_path}")

            audio_path = self._extract_audio_from_video(video_path, output_path.parent)

            api_key = (config.aliyun_access_key
                       or os.getenv("ALIYUN_API_KEY")
                       or os.getenv("DASHSCOPE_API_KEY")
                       or os.getenv("API_DASHSCOPE_API_KEY"))

            duration = self._get_media_duration(audio_path)

            if duration <= SEGMENT_SECONDS:
                logger.info(f"音频时长 {duration:.1f}s <= 阈值 {SEGMENT_SECONDS}s，单次转写")
                transcript = self._aliyun_speech_transcribe_audio(audio_path, config, api_key)
                srt_lines = self._segments_to_srt(
                    [{"start": 0.0, "end": max(duration, 1.0), "text": transcript}])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(srt_lines)
                logger.info(f"阿里云语音识别字幕生成成功: {output_path}")
                return output_path

            logger.info(f"音频时长 {duration:.1f}s 超过阈值 {SEGMENT_SECONDS}s，开始分段转写")
            ffmpeg_bin = get_ffmpeg_path()
            seg_dir = Path(tempfile.mkdtemp(prefix="asr_seg_", dir=str(output_path.parent)))
            try:
                cmd = [
                    ffmpeg_bin, '-y', '-i', str(audio_path),
                    '-f', 'segment', '-segment_time', str(SEGMENT_SECONDS),
                    '-ac', '1', '-ar', '16000',
                    str(seg_dir / "seg_%04d.wav")
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                if result.returncode != 0:
                    raise SpeechRecognitionError(f"音频分段失败: {(result.stderr or '')[-2000:]}")

                seg_files = sorted(seg_dir.glob("seg_*.wav"))
                if not seg_files:
                    raise SpeechRecognitionError("音频分段失败：未生成任何分段")

                logger.info(f"音频已切分为 {len(seg_files)} 段: {seg_dir}")

                all_segments = []
                success_count = 0
                cursor = 0.0
                for idx, seg_path in enumerate(seg_files, start=1):
                    seg_duration = self._get_media_duration(seg_path)
                    seg_start = cursor
                    seg_end = cursor + seg_duration
                    cursor = seg_end
                    try:
                        seg_text = self._aliyun_speech_transcribe_audio(seg_path, config, api_key)
                        all_segments.append({"start": seg_start, "end": seg_end, "text": seg_text})
                        success_count += 1
                        logger.info(
                            f"第 {idx}/{len(seg_files)} 段转写成功: {seg_path.name} "
                            f"({seg_duration:.1f}s, {seg_start:.1f}s-{seg_end:.1f}s)")
                    except Exception as seg_error:
                        logger.error(f"第 {idx}/{len(seg_files)} 段转写失败: {seg_path.name}: {seg_error}")

                if success_count == 0:
                    raise SpeechRecognitionError("阿里云语音识别全部分段转写失败")
                if success_count < len(seg_files):
                    logger.warning(
                        f"阿里云语音识别有 {len(seg_files) - success_count} 段转写失败，已跳过")

                srt_lines = self._segments_to_srt(all_segments)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(srt_lines)

                logger.info(f"阿里云语音识别字幕生成成功（{success_count}/{len(seg_files)} 段）: {output_path}")
                return output_path
            finally:
                shutil.rmtree(seg_dir, ignore_errors=True)

        except Exception as e:
            error_msg = f"阿里云语音识别生成字幕时发生错误: {e}"
            logger.error(error_msg)
            raise SpeechRecognitionError(error_msg)


def generate_subtitle_for_video(video_path: Path, output_path: Optional[Path] = None,
                               method: str = "aliyun_speech", language: str = "auto",
                               model: str = "base", enable_fallback: bool = True,
                               api_key: Optional[str] = None) -> Path:
    """
    为视频生成字幕文件的便捷函数（仅支持 aliyun_speech）

    Args:
        video_path: 视频文件路径
        output_path: 输出字幕文件路径
        method: 生成方法（仅 "aliyun_speech" 有效）
        language: 语言代码
        model: 模型参数（保留兼容）
        enable_fallback: 是否启用回退（阿里云方法无需回退）
        api_key: API密钥（缺省时回退到环境变量 DASHSCOPE_API_KEY）

    Returns:
        生成的字幕文件路径

    Raises:
        SpeechRecognitionError: 语音识别失败
    """
    config = SpeechRecognitionConfig(
        method=SpeechRecognitionMethod.ALIYUN_SPEECH,
        language=LanguageCode(language) if language != "auto" else LanguageCode.AUTO,
        model=model,
        enable_fallback=False,
    )
    if api_key:
        config.aliyun_access_key = api_key

    recognizer = SpeechRecognizer()
    return recognizer.generate_subtitle(video_path, output_path, config)
