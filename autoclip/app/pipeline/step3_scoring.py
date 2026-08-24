"""
Step 3: 内容评分 - 对每个话题进行质量评分，筛选出高质量内容
"""
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from collections import defaultdict

# 导入依赖
from ..utils.llm_client import LLMClient, LLMCallError
from ..utils.text_processor import TextProcessor
from ..core.shared_config import PROMPT_FILES, METADATA_DIR, MIN_SCORE_THRESHOLD, FRAME_ANALYSIS_ENABLED

logger = logging.getLogger(__name__)

class ClipScorer:
    """内容评分器"""
    
    # 台词回填相关常量
    _TRANSCRIPT_MAX_LEN = 1500      # 超过该字数触发中略截断
    _TRANSCRIPT_HEAD_RATIO = 0.4   # 保留开头比例
    _TRANSCRIPT_TAIL_RATIO = 0.4   # 保留结尾比例

    def __init__(self, prompt_files: Dict = None, metadata_dir: Path = None,
                 frame_analysis_enabled: Optional[bool] = None,
                 highlight_mode: bool = False,
                 highlight_max_duration: float = 10.0):
        self.llm_client = LLMClient()
        self.text_processor = TextProcessor()
        # 高光识别模式：从长剧集中找出多段 ≤highlight_max_duration 的短高光片段。
        # 开启时 LLM 更聚焦"三秒留人"的短爆点，并把 clip_type 判定为 highlight。
        self.highlight_mode = bool(highlight_mode)
        self.highlight_max_duration = float(highlight_max_duration or 10.0)

        # 台词回填依赖的 SRT 分块目录（Step1 产出）
        if metadata_dir is None:
            metadata_dir = METADATA_DIR
        self.metadata_dir = metadata_dir
        self.srt_chunks_dir = self.metadata_dir / "step1_srt_chunks"

        # 画面理解（可选）：源视频路径从环境变量注入（backend 调用时设置），
        # 开启 FRAME_ANALYSIS_ENABLED 且视频存在时才启用。
        # 支持每次运行传入 frame_analysis_enabled 覆盖环境变量（前端「画面理解」开关）。
        self.video_path = os.getenv("FRAME_ANALYSIS_VIDEO_PATH", "").strip()
        if frame_analysis_enabled is None:
            frame_analysis_enabled = FRAME_ANALYSIS_ENABLED
        self.frame_analysis_enabled = (
            bool(frame_analysis_enabled)
            and bool(self.video_path)
            and Path(self.video_path).exists()
        )
        if self.frame_analysis_enabled:
            try:
                from ..utils.frame_analyzer import analyze_timeline_frames
                self._analyze_timeline_frames = analyze_timeline_frames
            except Exception as e:
                logger.warning(f"画面分析模块加载失败，将跳过画面理解: {e}")
                self.frame_analysis_enabled = False

        # 加载提示词
        prompt_files_to_use = prompt_files if prompt_files is not None else PROMPT_FILES
        with open(prompt_files_to_use['recommendation'], 'r', encoding='utf-8') as f:
            self.recommendation_prompt = f.read()
    
    def score_clips(self, timeline_data: List[Dict]) -> List[Dict]:
        """
        为切片评分 (新版：按块批量处理，并使用LLM进行综合评估)
        """
        if not timeline_data:
            logger.warning("时间线数据为空，无法评分")
            return []
            
        logger.info(f"开始为 {len(timeline_data)} 个切片进行批量评分...")
        
        # 1. 按 chunk_index 对所有 timeline 数据进行分组
        timeline_by_chunk = defaultdict(list)
        for item in timeline_data:
            chunk_index = item.get('chunk_index')
            if chunk_index is not None:
                timeline_by_chunk[chunk_index].append(item)
            else:
                logger.warning(f"  > 话题 '{item.get('outline', '未知')}' 缺少 chunk_index，将被跳过。")
        
        all_scored_clips = []
        # 2. 遍历每个块，批量处理其中的所有话题
        for chunk_index, chunk_items in timeline_by_chunk.items():
            logger.info(f"处理块 {chunk_index}，其中包含 {len(chunk_items)} 个话题...")
            try:
                # 3. 使用LLM进行批量评估
                scored_chunk_items = self._get_llm_evaluation(chunk_items)
                
                if scored_chunk_items:
                    all_scored_clips.extend(scored_chunk_items)
                else:
                    logger.warning(f"块 {chunk_index} 的LLM评估返回为空，跳过。")

            except Exception as e:
                logger.error(f"  > 处理块 {chunk_index} 进行评分时出错: {str(e)}")
                continue

        # 4. 按最终得分对所有结果进行排序
        if all_scored_clips:
            all_scored_clips.sort(key=lambda x: x.get('final_score', 0), reverse=True)
            # 保持Step 2分配的固定ID，不再重新分配
            logger.info("按评分排序完成，保持原有固定ID不变")
            
            # 最终按ID排序，确保时间顺序的一致性
            all_scored_clips.sort(key=lambda x: int(x.get('id', 0)))
            logger.info("按ID排序完成，保持时间顺序")
                
        logger.info("所有切片评分完成")
        return all_scored_clips
    
    def _get_llm_evaluation(self, clips: List[Dict]) -> List[Dict]:
        """
        使用LLM进行批量评估，为每个clip添加 final_score 和 recommend_reason
        """
        try:
            # 画面理解：开启时批量分析所有候选片段画面（静默失败不影响打分）
            frame_map: Dict[str, Any] = {}
            if self.frame_analysis_enabled:
                try:
                    frame_map = self._analyze_timeline_frames(clips, self.video_path)
                    if frame_map:
                        logger.info(f"画面分析完成，{len(frame_map)}/{len(clips)} 个片段获得画面描述")
                except Exception as e:
                    logger.warning(f"画面分析失败，降级为纯文本打分: {e}")
                    frame_map = {}

            # 输入给LLM的数据不需要包含所有字段，只给必要的
            # transcript 为该时间区间内的原始台词原文，是判分的最重要依据
            input_for_llm = [
                {
                    "outline": clip.get('outline'),
                    "content": clip.get('content'),
                    "start_time": clip.get('start_time'),
                    "end_time": clip.get('end_time'),
                    "transcript": self._extract_transcript(
                        clip.get('chunk_index'),
                        clip.get('start_time'),
                        clip.get('end_time'),
                    ),
                    # 画面理解：该片段的视觉描述（场景/动作/情绪/OCR/精彩度），可为空
                    "frame_info": frame_map.get(str(clip.get('id'))) or None,
                } for clip in clips
            ]
            
            # 高光识别模式：在共享评分提示词后追加一段"短高光"判定指令，
            # 让 LLM 聚焦 ≤highlight_max_duration 的"三秒留人"短爆点，并把 clip_type
            # 判定为 highlight（区别于常规 suspense_cut/full_highlight）。
            prompt_to_use = self.recommendation_prompt
            if self.highlight_mode:
                prompt_to_use = (
                    self.recommendation_prompt
                    + "\n\n## 高光识别模式（本次启用）\n"
                    + f"当前为「高光识别」模式：请从候选片段中挑出时长 ≤ {self.highlight_max_duration:.0f} 秒的短高光爆点（三秒留人、情绪浓度最高、最适合信息流黄金前几秒的片段）。\n"
                    + "`clip_type` 在本模式下只能取 `highlight`（短高光段）。评分请更看重：开头几秒的钩子强度、名场面/金句密度、情绪爆点的紧凑性。\n"
                )
            try:
                response = self.llm_client.call_with_retry(prompt_to_use, input_for_llm)
            except Exception as e:
                # 模型调用失败 → 显式上浮，让流水线以 failed 结束并保留真实错误，
                # 而非把所有片段标 0 分后由 clips 接口按 60 分阈值过滤成 0 片段。
                logger.error(f"LLM 批量评估调用失败: {e}")
                raise LLMCallError(str(e)) from e
            parsed_list = self.llm_client.parse_json_response(response)
            
            if not isinstance(parsed_list, list) or len(parsed_list) != len(clips):
                logger.error(f"LLM返回的评分结果数量与输入不匹配。输入: {len(clips)}, 输出: {len(parsed_list)}")
                return []
                
            # 将评分结果合并回原始的clips数据
            for original_clip, llm_result in zip(clips, parsed_list):
                score = llm_result.get('final_score')
                reason = llm_result.get('recommend_reason')
                clip_type = llm_result.get('clip_type')

                if score is None or reason is None:
                    logger.warning(f"LLM返回的某个结果缺少score或reason: {llm_result}")
                    original_clip['final_score'] = 0.0
                    original_clip['recommend_reason'] = "评估失败"
                else:
                    original_clip['final_score'] = round(float(score), 2)
                    original_clip['recommend_reason'] = reason
                    # 出片形态：suspense_cut（30-60s 悬念断点片）/ full_highlight（60-90s 完整高光段）/
                    # highlight（高光识别模式产出的短高光段）。兼容模型不返回或返回非法值的情况。
                    if self.highlight_mode:
                        # 高光识别模式：统一判为 highlight（短高光）
                        clip_type = "highlight"
                    elif clip_type not in ("suspense_cut", "full_highlight", "highlight"):
                        clip_type = self._infer_clip_type(
                            original_clip.get('start_time'),
                            original_clip.get('end_time'),
                        )
                    original_clip['clip_type'] = clip_type
                    # 安全地获取outline标题用于日志显示
                    outline = original_clip.get('outline', {})
                    if isinstance(outline, dict):
                        title = outline.get('title', '未知标题')
                    else:
                        title = str(outline)
                    logger.info(f"  > 评分成功: {title[:20]}... [分数: {score}, 形态: {clip_type}]")

            return clips

        except LLMCallError:
            raise
        except Exception as e:
            logger.error(f"LLM批量评估失败: {e}")
            # 如果批量失败，为所有clips标记为失败
            for clip in clips:
                clip['final_score'] = 0.0
                clip['recommend_reason'] = "批量评估失败"
            return clips

    def _extract_transcript(self, chunk_index, start_time, end_time) -> str:
        """
        从 Step1 产出的 SRT 分块中，按时间区间回填该片段的原始台词。

        这是本次短剧词典整合的核心：让打分模型真正看到原始台词，
        而非只依赖上游生成的话题摘要（outline + content）。

        Args:
            chunk_index: 片段所属的块索引（step1_srt_chunks/chunk_{i}.json）
            start_time: 片段开始时间（HH:MM:SS,mmm）
            end_time:   片段结束时间（HH:MM:SS,mmm）

        Returns:
            落在 [start_time, end_time] 区间内的台词拼接文本；
            若无法定位则返回空字符串（调用方会退回依据摘要评估）。
        """
        if chunk_index is None or not start_time or not end_time:
            return ""

        chunk_file = self.srt_chunks_dir / f"chunk_{chunk_index}.json"
        if not chunk_file.exists():
            logger.warning(f"  > 找不到 SRT 分块文件 {chunk_file}，无法回填台词")
            return ""

        try:
            with open(chunk_file, 'r', encoding='utf-8') as f:
                srt_entries = json.load(f)
        except Exception as e:
            logger.error(f"  > 读取 SRT 分块 {chunk_file} 失败: {e}")
            return ""

        try:
            start_sec = self.text_processor.time_to_seconds(start_time)
            end_sec = self.text_processor.time_to_seconds(end_time)
        except Exception as e:
            logger.error(f"  > 时间格式解析失败 ({start_time}~{end_time}): {e}")
            return ""

        # 收集落在区间内的字幕条目（含跨边界重叠的整句）
        matched = []
        for sub in srt_entries:
            try:
                sub_start = self.text_processor.time_to_seconds(sub['start_time'])
                sub_end = self.text_processor.time_to_seconds(sub['end_time'])
            except Exception:
                continue
            if sub_end >= start_sec and sub_start <= end_sec:
                matched.append(sub)

        if not matched:
            return ""

        transcript = " ".join(s.get('text', '') for s in matched).strip()
        return self._truncate_transcript(transcript)

    def _truncate_transcript(self, transcript: str) -> str:
        """
        Token 保护：过长时截断为「头 40% + 尾 40% + 中略」。
        开头钩子与结尾爆点最密集，中间可省。
        """
        if len(transcript) <= self._TRANSCRIPT_MAX_LEN:
            return transcript

        head_len = int(len(transcript) * self._TRANSCRIPT_HEAD_RATIO)
        tail_len = int(len(transcript) * self._TRANSCRIPT_TAIL_RATIO)
        head = transcript[:head_len]
        tail = transcript[-tail_len:]
        truncated = f"{head}……（中略，原始台词过长）……{tail}"
        logger.info(
            f"  > 台词超长已中略截断: {len(transcript)} -> {len(truncated)} 字"
        )
        return truncated

    def _infer_clip_type(self, start_time, end_time) -> str:
        """模型未返回 clip_type 时的兜底：按时长推断出片形态。"""
        if not start_time or not end_time:
            return "full_highlight"
        try:
            dur = (self.text_processor.time_to_seconds(end_time)
                   - self.text_processor.time_to_seconds(start_time))
        except Exception:
            return "full_highlight"
        # 60 秒以内且更接近短钩子节奏 → 悬念断点片
        return "suspense_cut" if dur <= 60 else "full_highlight"

    def save_scores(self, scored_clips: List[Dict], output_path: Path):
        """保存评分结果"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(scored_clips, f, ensure_ascii=False, indent=2)
        logger.info(f"评分结果已保存到: {output_path}")

def run_step3_scoring(timeline_path: Path, metadata_dir: Path = None, output_path: Optional[Path] = None, prompt_files: Dict = None, frame_analysis_enabled: Optional[bool] = None, highlight_mode: bool = False, highlight_max_duration: float = 10.0) -> List[Dict]:
    """
    运行Step 3: 内容评分与筛选
    
    Args:
        timeline_path: 时间线文件路径
        output_path: 输出文件路径
        prompt_files: 自定义提示词文件
        frame_analysis_enabled: 画面理解（MiniCPM-V）开关，None 时回退到环境变量
        highlight_mode: 高光识别开关，开启时找出多段 ≤highlight_max_duration 的短高光
        highlight_max_duration: 高光单段最大时长（秒，默认 10）
        
    Returns:
        高分切片列表
    """
    # 加载时间线数据
    with open(timeline_path, 'r', encoding='utf-8') as f:
        timeline_data = json.load(f)

    # 确定 metadata_dir（台词回填依赖 step1_srt_chunks）
    if metadata_dir is None:
        metadata_dir = METADATA_DIR

    # 画面理解开关：每次运行可传入覆盖环境变量（前端「画面理解」开关）
    if frame_analysis_enabled is None:
        frame_analysis_enabled = FRAME_ANALYSIS_ENABLED

    # 创建评分器
    scorer = ClipScorer(prompt_files, metadata_dir,
                        frame_analysis_enabled=frame_analysis_enabled,
                        highlight_mode=highlight_mode,
                        highlight_max_duration=highlight_max_duration)
    
    # 评分
    scored_clips = scorer.score_clips(timeline_data)
    
    # 筛选高分切片
    high_score_clips = [clip for clip in scored_clips if clip['final_score'] >= MIN_SCORE_THRESHOLD]
    
    # 保存所有评分后的片段（用于调试和分析）
    all_scored_path = metadata_dir / "step3_all_scored.json"
    scorer.save_scores(scored_clips, all_scored_path)
    
    # 保存筛选后的高分片段（用于后续步骤）
    if output_path is None:
        output_path = metadata_dir / "step3_high_score_clips.json"
        
    scorer.save_scores(high_score_clips, output_path)
    
    return high_score_clips