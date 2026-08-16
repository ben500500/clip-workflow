"""
语音识别工具。

支持两种方式（通过 SpeechRecognitionConfig.method 或环境变量选择）：
  - aliyun_speech: 阿里云百炼 DashScope qwen3-asr-flash（默认）
  - whisper: 本地 faster-whisper（CPU 推理，无需 API Key，可离线）
"""
import logging
import subprocess
import os
import re
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
    FUNASR_LOCAL = "funasr_local"


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

    # 本地 FunASR 模型标识（如 iic/SenseVoiceSmall），None 时走默认值/环境变量
    funasr_model: Optional[str] = None


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
            SpeechRecognitionMethod.FUNASR_LOCAL: self._check_funasr_availability(),
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

    def _check_funasr_availability(self) -> bool:
        """检查本地 FunASR 运行时是否可用（无需 API Key）。"""
        try:
            import funasr  # noqa: F401
            return True
        except Exception:
            logger.debug("本地 FunASR 未安装（import funasr 失败）")
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
        if config.method == SpeechRecognitionMethod.FUNASR_LOCAL:
            return self._generate_subtitle_funasr_local(video_path, output_path, config)
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
    def _aggregate_word_timestamps(words: list) -> List[Dict[str, Any]]:
        """把 whisper 的词级时间戳聚合成短句级别的字幕段。

        faster-whisper 的 word_timestamps=True 返回每个词的 (start, end, word)。
        这里按以下规则把词聚合成一条条字幕：
          - 目标时长约 2~5 秒（MAX_SUB_DURATION=5.0，MIN_SUB_DURATION=1.2）；
          - 遇到标点（。！？，、；：）或停顿 >0.5s 时优先断句；
          - 每段最少 2 个词，避免字幕过于碎片。
        """
        MAX_DURATION = 5.0
        MIN_DURATION = 1.2
        PAUSE_BREAK = 0.5

        # 规范化 words：词可能带前后空格/标点，记录原始文本供拼接
        items = []
        for w in words:
            try:
                start = float(getattr(w, "start", 0.0))
                end = float(getattr(w, "end", start))
            except (TypeError, ValueError):
                continue
            text = (getattr(w, "word", "") or "").strip()
            if not text:
                continue
            items.append({"start": start, "end": end, "text": text})
        if not items:
            return []

        result = []
        cur_words = []
        cur_start = None
        cur_end = None

        def flush():
            nonlocal cur_words, cur_start, cur_end
            if cur_words:
                txt = " ".join(cur_words).strip()
                # 中文/日文等紧凑文字去掉词间多余空格
                txt = re.sub(r"\s+([，。！？；：、,.!?;])", r"\1", txt)
                if cur_start is not None and cur_end is not None and txt:
                    result.append({"start": cur_start, "end": cur_end, "text": txt})
                cur_words = []
                cur_start = None
                cur_end = None

        for it in items:
            if cur_start is None:
                cur_start = it["start"]
                cur_words = [it["text"]]
                cur_end = it["end"]
                continue
            # 停顿过长：断句
            if it["start"] - cur_end > PAUSE_BREAK:
                flush()
                cur_start = it["start"]
                cur_words = [it["text"]]
                cur_end = it["end"]
                continue
            # 句末标点且已到最小时长：断句
            last_text = cur_words[-1]
            cur_dur = it["end"] - (cur_start or 0.0)
            if last_text.endswith(("。", "！", "？", "，", "、", "；", ".", "!", "?")) \
                    and cur_dur >= MIN_DURATION:
                flush()
                cur_start = it["start"]
                cur_words = [it["text"]]
                cur_end = it["end"]
                continue
            # 超时强制断句
            if it["end"] - (cur_start or 0.0) > MAX_DURATION:
                flush()
                cur_start = it["start"]
                cur_words = [it["text"]]
                cur_end = it["end"]
                continue
            cur_words.append(it["text"])
            cur_end = it["end"]
        flush()
        return result

    @staticmethod
    def _merge_short_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并过短的相邻字幕段，避免字幕频繁闪断。

        相邻两条字幕都 <0.8s 且间隔 <0.3s 时合并为一条；
        单条 <0.4s 时也尝试与下一条合并。
        """
        MIN_KEEP = 0.4
        if not segments:
            return segments
        merged = []
        for seg in segments:
            dur = seg.get("end", 0.0) - seg.get("start", 0.0)
            if not merged:
                merged.append(seg)
                continue
            last = merged[-1]
            last_dur = last.get("end", 0.0) - last.get("start", 0.0)
            gap = seg.get("start", 0.0) - last.get("end", 0.0)
            # 两条都很短、间隔又近 → 合并
            if dur < MIN_KEEP and last_dur < 0.8 and gap < 0.3:
                merged[-1] = {
                    "start": last["start"],
                    "end": seg.get("end", seg.get("start", 0.0)),
                    "text": (last.get("text", "") + " " + seg.get("text", "")).strip(),
                }
            else:
                merged.append(seg)
        return merged

    @staticmethod
    def _detect_speech_windows(audio_path: Path,
                              silence_threshold: float = -35.0,
                              min_silence: float = 0.5) -> list:
        """用 ffmpeg silencedetect 检测音频中的语音（非静音）区间。

        返回有序的 (start, end) 秒级区间列表；失败或无语音时返回 []。
        用于后续对无时间戳的 ASR（如阿里云）做字幕时间轴精修：
        让每条字幕只在语音出现时显示。
        """
        try:
            ffmpeg_bin = get_ffmpeg_path()
            cmd = [
                ffmpeg_bin, '-i', str(audio_path),
                '-af', f'silencedetect=noise={silence_threshold}dB:d={min_silence}',
                '-f', 'null', '-',
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=3600)
            out = proc.stderr.decode(errors='replace')
            if proc.returncode != 0:
                logger.warning('silencedetect 失败，跳过语音窗口检测')
                return []
        except Exception as e:
            logger.warning('silencedetect 失败: %s', e)
            return []

        silence_starts = []
        silence_ends = []
        for line in out.splitlines():
            if 'silence_start:' in line:
                try:
                    silence_starts.append(float(line.split('silence_start:')[1].strip()))
                except ValueError:
                    pass
            elif 'silence_end:' in line:
                try:
                    # silence_end 行形如: silence_end: 2.345 | silence_duration: 1.234
                    silence_ends.append(float(line.split('silence_end:')[1].strip().split()[0]))
                except ValueError:
                    pass

        if not silence_starts:
            # 没有检测到静音 → 全程都在说话
            return []

        duration = SpeechRecognizer._get_media_duration(audio_path)

        # 合并静音区间
        silences = list(zip(silence_starts, silence_ends))
        if len(silence_starts) > len(silence_ends):
            silences.append((silence_starts[-1], duration or silence_starts[-1] + 1.0))
        silences.sort()
        merged_sil = []
        for s, e in silences:
            if merged_sil and s <= merged_sil[-1][1]:
                merged_sil[-1] = (merged_sil[-1][0], max(merged_sil[-1][1], e))
            else:
                merged_sil.append([s, e])

        # 非静音区间 = 相邻静音之间的空隙
        speech = []
        cursor = 0.0
        for s, e in merged_sil:
            if s > cursor + 0.05:
                speech.append((cursor, s))
            cursor = max(cursor, e)
        if duration > 0 and cursor < duration - 0.05:
            speech.append((cursor, duration))
        return speech

    @staticmethod
    def _split_text_by_punctuation(text: str, max_chars: int = 40) -> list:
        """把一段长文本按标点/换行切成短句，用于分配到语音区间。

        优先在句末标点（。！？）断句，其次逗号/分号，再次长句硬切。
        """
        if not text:
            return []
        text = text.strip()
        if not text:
            return []

        # 先把已有换行展开
        text = re.sub(r'\s+', ' ', text)
        pieces = []

        # 按句末标点切
        sentences = re.split(r'(?<=[。！？.!?])', text)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            # 句子里仍太长 → 按逗号/分号/顿号切
            while len(sent) > max_chars:
                # 找最近的逗号类标点切点
                cut = -1
                for punct in ['，', '；', '、', ',', ';', '：', ':']:
                    idx = sent.rfind(punct, 0, max_chars)
                    if idx > 0:
                        cut = idx + 1
                        break
                if cut <= 0:
                    # 没有标点，硬切到 max_chars
                    cut = max_chars
                pieces.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if sent:
                pieces.append(sent)
        return [p for p in pieces if p]

    @classmethod
    def _refine_srt_with_speech_windows(cls, srt_content: str,
                                        speech_windows: list) -> str:
        """根据语音窗口精修 SRT 字幕时间轴。

        核心思路：把每条 SRT 记录的显示时间精确对齐到语音区间。
        - 若一条字幕完全落在一个语音窗口内，保持原样（最多微调）；
        - 若一条字幕跨越多个语音窗口/含静音段，按语音窗口裁剪其显示时间；
        - 若一条字幕时间跨度远大于语音窗口总时长（如整段 ASR），按语音窗口
          把文本切成多条，每条对应一个语音窗口。

        speech_windows 为空时原样返回（无法精修）。
        """
        if not speech_windows:
            return srt_content
        if not srt_content or not srt_content.strip():
            return srt_content

        records = cls._parse_srt_records(srt_content)
        if not records:
            return srt_content

        refined = []
        for r in records:
            text = r.get('text', '').strip()
            if not text:
                continue
            s = r.get('start', 0.0)
            e = r.get('end', s)

            # 找出与这条字幕时间区间相交的语音窗口
            overlap = []
            for ws, we in speech_windows:
                os_ = max(s, ws)
                oe = min(e, we)
                if oe - os_ >= 0.05:
                    overlap.append((os_, oe))
            if not overlap:
                # 没有语音窗口 → 静音，跳过该条字幕
                continue

            # 只有一个语音窗口且基本覆盖整条字幕 → 保持一条，微调边界
            total_overlap = sum(oe - os_ for os_, oe in overlap)
            if len(overlap) == 1 and total_overlap >= (e - s) * 0.8:
                refined.append({'start': overlap[0][0], 'end': overlap[0][1], 'text': text})
                continue

            # 多个语音窗口（或覆盖不足）：尝试按文本切分分配
            # 把文本切成短句，然后均匀分配到各语音窗口
            pieces = cls._split_text_by_punctuation(text)
            if len(pieces) <= 1:
                # 无法切分 → 只保留最长的语音窗口，显示该条字幕
                best = max(overlap, key=lambda x: x[1] - x[0])
                refined.append({'start': best[0], 'end': best[1], 'text': text})
                continue

            # 把 pieces 分配到 overlap 窗口：同一窗口内的多条 pieces 合并成一条
            # 字幕（避免时间重叠），整条字幕在窗口时间内显示。
            win_count = len(overlap)
            if win_count == 0:
                continue
            win_durs = [max(0.0, we - ws) for ws, we in overlap]
            total_dur = sum(win_durs) or 1.0
            n_pieces = len(pieces)
            # 按权重计算每个窗口应得的条数；若窗口数 > pieces 数，只保留
            # 时长最长的 n_pieces 个窗口，每个窗口 1 条。
            if win_count >= n_pieces:
                sorted_idx = sorted(range(win_count), key=lambda i: win_durs[i], reverse=True)
                keep = sorted(sorted_idx[:n_pieces])
                alloc = [0] * win_count
                for ki in keep:
                    alloc[ki] = 1
            else:
                alloc = [max(1, int(round(d / total_dur * n_pieces))) for d in win_durs]
                # 修正：分配总数不能超过 pieces 数
                while sum(alloc) > n_pieces:
                    idx = max(range(win_count), key=lambda i: alloc[i])
                    if alloc[idx] > 1:
                        alloc[idx] -= 1
                    else:
                        idx2 = max([i for i in range(win_count) if alloc[i] > 1],
                                   key=lambda i: alloc[i], default=-1)
                        if idx2 < 0:
                            break
                        alloc[idx2] -= 1
                extra = n_pieces - sum(alloc)
                if extra > 0:
                    alloc[-1] += extra

            # 按分配把 pieces 分到各窗口，同一窗口的 pieces 合并为一条字幕
            piece_idx = 0
            for wi in range(win_count):
                count = alloc[wi]
                if count <= 0:
                    continue
                ws, we = overlap[wi]
                window_pieces = pieces[piece_idx:piece_idx + count]
                piece_idx += count
                if not window_pieces:
                    continue
                # 同一窗口的多条 pieces 合并为一条，时间覆盖整个窗口
                merged_text = ' '.join(window_pieces).strip()
                refined.append({'start': ws, 'end': we, 'text': merged_text})
            # 若还有未分配的 pieces，追加到最后一个窗口（合并成一条）
            if piece_idx < len(pieces):
                rest = ' '.join(pieces[piece_idx:])
                ws, we = overlap[-1]
                refined.append({'start': ws, 'end': we, 'text': rest})

        if not refined:
            return srt_content

        # 排序并重写 SRT
        refined.sort(key=lambda x: x['start'])
        lines = []
        for i, r in enumerate(refined, start=1):
            start = cls._format_srt_timestamp(r['start'])
            end = cls._format_srt_timestamp(r['end'])
            lines.append(f"{i}\n{start} --> {end}\n{r['text']}\n")
        return '\n'.join(lines) + '\n'

    @classmethod
    def _parse_srt_records(cls, srt_content: str) -> list:
        """解析 SRT 内容为有序记录 [{start, end, text}]。"""
        records = []
        if not srt_content:
            return records
        blocks = [b for b in srt_content.replace('\r\n', '\n').split('\n\n') if b.strip()]
        for block in blocks:
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            time_idx = None
            for i, ln in enumerate(lines):
                if '-->' in ln:
                    time_idx = i
                    break
            if time_idx is None:
                continue
            time_line = lines[time_idx]
            try:
                left, right = time_line.split('-->', 1)
            except ValueError:
                continue
            start = cls._parse_srt_time(left.strip())
            end = cls._parse_srt_time(right.strip())
            text = ' '.join(lines[time_idx + 1:])
            if end <= start:
                end = start + 1.0
            records.append({'start': start, 'end': end, 'text': text})
        return records

    @staticmethod
    def _parse_srt_time(ts: str) -> float:
        """解析 SRT 时间戳 "HH:MM:SS,mmm" 为秒。"""
        ts = ts.strip().replace(',', '.')
        parts = ts.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])

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
                word_timestamps=True,
            )
            seg_list = []
            for s in segments:
                if not s.text or not s.text.strip():
                    continue
                # 优先使用词级时间戳，聚合成更细粒度的短句字幕（每条约 2~5 秒，
                # 让字幕与语音精确对齐，避免一句长台词长时间挂在屏幕上）。
                words = list(getattr(s, "words", None) or [])
                if words:
                    seg_list.extend(self._aggregate_word_timestamps(words))
                else:
                    seg_list.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
            # 合并相邻过短的段，避免字幕闪断
            seg_list = self._merge_short_segments(seg_list)
            logger.info("whisper 转写完成: %d 段（detected language=%s）", len(seg_list), info.language or "?")

            # whisper 通过 word_timestamps=True 已获得词级精确时间戳，
            # 并聚合成短句级字幕，无需再做 VAD 二次裁剪（避免破坏精确边界）。
            srt_content = self._segments_to_srt(seg_list)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(srt_content, encoding="utf-8")
            if not seg_list:
                logger.warning("whisper 未识别到语音内容（可能为静音视频）")
            return output_path

    def _generate_subtitle_funasr_local(self, video_path: Path, output_path: Path,
                                        config: SpeechRecognitionConfig) -> Path:
        """使用本地 FunASR（AutoModel）生成字幕（CPU 推理，无需 API Key）。

        默认模型为 iic/SenseVoiceSmall，可通过 config.funasr_model 或
        环境变量 AUTOCLIP_ASR_FUNASR_MODEL 覆盖。
        """
        if not video_path.exists():
            raise SpeechRecognitionError(f"视频文件不存在: {video_path}")
        if video_path.stat().st_size == 0:
            raise SpeechRecognitionError(f"视频文件为空: {video_path}")
        if output_path.exists():
            logger.info(f"字幕文件已存在，跳过 FunASR 处理: {output_path}")
            return output_path
        try:
            from funasr import AutoModel
        except ModuleNotFoundError as e:
            raise SpeechRecognitionError(
                f"FunASR 运行时缺少依赖（{e}）。请安装 funasr / modelscope / torch 后再试。"
            )
        try:
            model_id = (getattr(config, "funasr_model", None)
                        or os.getenv("AUTOCLIP_ASR_FUNASR_MODEL", "iic/SenseVoiceSmall"))
            language = None if config.language == LanguageCode.AUTO else str(config.language).split("-")[0]
            logger.info(f"使用 FunASR 生成字幕: model={model_id} lang={language or 'auto'}")
            audio_path = self._extract_audio_from_video(video_path, output_path.parent)
            model = AutoModel(
                model=model_id,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                punc_model="ct-punc",
                disable_update=True,
                device="cpu",
            )
            res = model.generate(
                input=[str(audio_path)],
                batch_size_s=300,
                language=language or "auto",
                use_itn=True,
            )
            if not res or not res[0]:
                raise SpeechRecognitionError("FunASR 未识别出任何语音内容")
            sentence_info = res[0].get("sentence_info") or {}
            sent_texts = sentence_info.get("text") or []
            sent_ts = sentence_info.get("timestamp") or []
            if sent_texts and sent_ts and len(sent_texts) == len(sent_ts):
                segments = []
                for t, (s, e) in zip(sent_texts, sent_ts):
                    t = self._strip_funasr_tags(t).strip()
                    if t:
                        segments.append({"start": float(s), "end": float(e), "text": t})
                if not segments:
                    raise SpeechRecognitionError("FunASR 句子切分结果为空")
            else:
                text = self._strip_funasr_tags(res[0].get("text", "")).strip()
                if not text:
                    raise SpeechRecognitionError("FunASR 识别结果为空")
                duration = self._get_media_duration(video_path)
                segments = [{"start": 0.0, "end": duration, "text": text}]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(self._segments_to_srt(segments), encoding="utf-8")
            logger.info(f"本地 FunASR 字幕生成成功: {output_path}")
            return output_path
        except SpeechRecognitionError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"本地 FunASR 生成字幕失败: {e}", exc_info=True)
            raise SpeechRecognitionError(f"本地 FunASR 生成字幕失败: {e}")

    @staticmethod
    def _strip_funasr_tags(text: str) -> str:
        """去除 FunASR（SenseVoice）输出中的语言/情感标记，如 [ZH] [NEUTRAL]。"""
        if not text:
            return text
        return re.sub(r"\[[A-Za-z]+\]", "", text)

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
                # VAD 时间轴精修：把整段 ASR 文本按语音窗口切分为精确字幕，
                # 让字幕只在语音出现时显示（解决字幕提早出现/延后消失）
                speech_windows = self._detect_speech_windows(audio_path)
                if speech_windows:
                    srt_lines = self._refine_srt_with_speech_windows(srt_lines, speech_windows)
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
                # VAD 时间轴精修：按语音窗口裁剪每条字幕的显示时间，
                # 让字幕只在语音出现时显示（解决字幕提早出现/延后消失）
                speech_windows = self._detect_speech_windows(audio_path)
                if speech_windows:
                    srt_lines = self._refine_srt_with_speech_windows(srt_lines, speech_windows)
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
