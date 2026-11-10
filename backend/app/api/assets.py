"""素材库 API（Asset Library，设计方案《素材库模块-设计方案-20261103.md》P0）。

P0 只补三件真正缺的事（其余能力复用既有链路）：
1. 跨批次链接去重     —— 导入时按归一化键命中「这条是不是有人传过」，提示 + 允许强制重复
2. 文件批量上传       —— 多文件一次投，落自有桶 raw-footage/asset/（不借智令 temp 桶，6 小时自删）
3. 钩子文案 + 审核队列 —— 反推出来的详规 → 3 条候选钩子文案 → 过审 → 按 N 出生产单

链路（每一环可单独重试）：
    导入 → 反推提示词(智令 doc/120) → 钩子文案(autoclip) → 审核 → 生产单(N 条差异化提示词) → 导出
    └ 11-05 批 H 起投递也有落点，两条路并存：
      ① `POST /assets/productions/dispatch`＝**机器连板**（建任务→轮询出片→成片落进产物），
         但**逐批人工确认**（`confirm=true`），且没配 `AIVIDEO_AUTH` 时当场白话拒收；
      ② 导出 payload → 人在企微后台建任务 → `POST /assets/productions/status` 回写
         queued/running/success/failed（11-03 拍板第 4 条，这条路一直没断）。
      **两条路的闸门与状态迁移是同一套判据**（同一个 `_dispatch_gate`＋同一个 `_build_delivery`），
      所以别在 ② 里把机器投的结果再报一遍。切片视频拼接、交付打包仍属 P1/P2。
      号池不做硬限（产能不限），只把数报清楚。

生产通道（2026-11-03 用户裁决）：**企微自动化后台「创建 AI 视频」任务板**
（`wework_aivideo`，`POST /api-g/aivideo/create`，payload 七键 tag/reqID/total/date/prompt/
name/picDatas），不是豆包网页 RPA、也不是火山方舟 Seedance 官方 API。这条通道**不扣现金**、
**没有时长/分辨率参数**（成片恒 10.08s / 720×1280），号池实测 ≈120 条/日。P1 前置是队列拆分：
`seedance_generate_task` 现在与视频号发布抢同一个 concurrency=1 的 publish 队列，不拆就开批量
接口生产＝发布链路一条都发不出去。

成本口径（为什么处处要闸门）：
- 反推按**计时上限**扣费，不是按视频实际时长 —— 0.00054 元/秒，600 档一条 0.324 元。
  所以默认档位是 180 而不是既有反推页用的 600，且批量提交前必须给「预估 + 余额 + 闸门」。
- 落库的 cost_prompt 是**按档位推算的额度**（智令不逐单回传金额），用于与账单对账，别当精确值。

权限口径（设计方案 §7 + 11-03 用户裁决）：
- **可见范围＝全部**：素材/批次/文案/生产单/产物对所有登录用户可见，不按导入人隔离（详见
  下面「可见范围口径」一段）。取消的是"谁能看"，没取消"谁能写"。
- 导入/上传/反推/出文案 = 素材专员（material）与运营（operator）、admin；发布专员不参与生产。
- 审核/投产 = operator/admin；**生产者不得自审**（谁建的素材谁不能过自己的文案，admin 除外）。
- 投递状态回写（`POST /assets/productions/status`）与投产同侧 = operator/admin：改的是生产台账，
  素材专员能导入反推出文案，但不能自己把单改成"成功"。
- 驳回必填理由；改后通过必须留痕（text_before_edit + AuditLog before/after）。
"""

import asyncio
import copy
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
import weakref
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List, Optional, Tuple

import json
import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_roles
from app.config import settings
# ⚠️ `async_session_factory` 走 `app.database` 的**模块属性**取（不在本模块 import 名字）：
# 后台任务的会话必须和 `init_db()`／测试 bootstrap 换引擎后的那个工厂是同一个，
# 直接 `from app.database import async_session_factory` 会把导入那一刻的对象绑死，
# 集成测试替换过引擎后，后台任务就会拿旧引擎去连一个根本不存在的库。
from app import database as _database
from app.database import get_db
from app.models.asset import (
    ASSET_FRAME_KINDS,
    ASSET_JOB_KINDS,
    AS_ARCHIVED,
    CH_WEWORK_AIVIDEO,
    DEFAULT_PRODUCTION_CHANNEL,
    EXPORTABLE_PRODUCTION_STATES,
    FRAME_GRID,
    FRAME_OUTPUT_THUMB,
    FRAME_THUMB,
    JB_FAILED,
    JB_INTERRUPTED,
    JB_QUEUED,
    JB_RUNNING,
    JB_SUCCEEDED,
    JOB_ANALYZE,
    JOB_DISPATCH,
    JOB_DOWNLOAD,
    JOB_FRAMES,
    JOB_PROMPT_PREVIEW,
    JOB_PRODUCE,
    JOB_SUMMARY_GENERATE,
    MEDIA_IMAGE,
    MEDIA_KINDS,
    MEDIA_VIDEO,
    PR_CANCELLED,
    PR_FAILED,
    PR_ORDER_READY,
    PR_QUEUED,
    PR_RUNNING,
    PR_SKIPPED,
    PR_SUCCESS,
    PR_SUPERSEDED,
    PRODUCTION_CHANNELS,
    REVIEW_PASSED_STATES,
    REVIEW_STATES,
    RV_APPROVED,
    RV_NEED_REWRITE,
    RV_PASSED_EDITED,
    RV_PENDING,
    RV_REJECTED,
    SOURCE_FILE,
    SOURCE_LINK,
    STAGE_FAILED,
    STAGE_PENDING,
    STAGE_RUNNING,
    STAGE_SKIPPED,
    STAGE_STATES,
    STAGE_SUCCESS,
    AssetBatch,
    AssetCategory,
    AssetFrame,
    AssetItem,
    AssetJob,
    AssetOutput,
    AssetProduction,
    AssetSummary,
    gen_asset_code,
    gen_batch_code,
)
from app.models.audit import AuditLog
from app.models.material import Episode, Project, SliceOutput, SliceTask, SystemConfig
from app.models.models import User
from app.models.user import UserRole
from app.services import asset_compose_service as compose
from app.services import asset_frame_service as framesvc
from app.services import asset_prompt_elements as pesvc
from app.services import asset_service as svc
from app.services import aivideo_board as board
from app.services.data_scope import check_project_access_by_episode
from app.services.net_guard import UnsafeURLError, assert_public_http_url_async
from app.services.minio_service import (
    delete_file,
    download_file,
    download_to_file,
    get_presigned_url,
    upload_file_from_path,
)
from app.api.slice_helpers import _ffprobe_duration
from app.services.upload_service import validate_file_name
from app.utils.helpers import utc_iso
from wechat_download.models import PST_UPLOAD, PT_FAILED, PT_SUCCESS, WechatDlPromptTask
from wechat_download.provider_registry import ProviderParseError, dispatch_parse
# 批 J（11-05）：下载原片复用采集侧同一个拉流下载器（断点续传/HLS 都在里面），
# 不从 service 导——那份还连着采集侧的 session/任务表，借了就会把两条链搅在一起。
from wechat_download.downloader import get_downloader
from wechat_download.prompt_service import (
    EXT_CONTENT_TYPES,
    create_prompt_task,
    create_upload_prompt_task,
    get_prompt_task,
    refresh_prompt_task,
    serialize_prompt_task,
    upload_max_bytes,
    validate_upload_ext,
    validate_upload_size,
)
from wechat_download.provider_registry import fetch_provider_balances

logger = logging.getLogger(__name__)

router = APIRouter()

# 角色集合（导入/反推/出文案：素材专员 + 运营 + 管理员；发布专员排除在外）
_PROD_ROLES = (UserRole.material, UserRole.operator, UserRole.admin)
# 审核与放批：运营 + 管理员（素材专员不能审自己产的东西）
_REVIEW_ROLES = (UserRole.operator, UserRole.admin)


def require_functions(*funcs: str):
    """A′（2026-11-08 评审定稿）：职能开关判定**单点**——审核（质检）/投产（挑选、投板）
    两个岗位拆职能不拆账号（users.can_review / users.can_produce，默认双开兼容现状），
    需要岗位隔离的组由管理员在用户管理里按人关闭。角色闸（require_roles）之外再拦一道，
    admin 恒过。⚠️ 职能判定只许走这里，禁止各端点散落 if（重造第二套口径的前车之鉴：
    assets.py 曾同时存在 data_scope 与跨人两套口径）。"""
    from fastapi import Depends as _Depends

    async def _dep(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.admin.value:
            return current_user
        fn_map = {
            "review": bool(getattr(current_user, "can_review", True)),
            "produce": bool(getattr(current_user, "can_produce", True)),
        }
        for f in funcs:
            if not fn_map.get(f, True):
                label = "审核（质检）" if f == "review" else "投产（挑选、投板）"
                raise HTTPException(
                    status_code=403,
                    detail=f"你的账号未启用「{label}」职能——管理员可在用户管理里按人开启",
                )
        return current_user

    return _dep

# 单次请求最多处理多少条 —— 反推/出文案都是**同步等外部接口**的，
# 100 条串跑会把请求挂到网关超时。P1 上队列后这个上限交给队列，不由 HTTP 层扛。
# 取值走 Settings（原直接 os.getenv 会让运维只能在代码里硬调，且 .env.example 无从登记）。
def _analyze_max_per_call() -> int:
    return max(1, int(settings.ASSET_ANALYZE_MAX_PER_CALL))


def _summary_max_per_call() -> int:
    return max(1, int(settings.ASSET_SUMMARY_MAX_PER_CALL))


# ──────────────────────────────────────────────
# Pydantic 入参
# ──────────────────────────────────────────────


class ImportBatchRequest(BaseModel):
    """链接批量导入。超过单批上限**由服务端自动拆批**（A4-1，方案 §四），不再打回。"""
    links: List[str] = Field(default_factory=list, description="分享链接列表（可含中文文案，自动提取 http token）")
    name: Optional[str] = Field(None, description="批次名，默认「链接导入 MMDD」；拆批时自动加「第 i/k 批」")
    project_id: Optional[str] = Field(None, description="归属项目（可选，用于后续拼接取正文）")
    prompt_max_duration: Optional[int] = Field(None, description="本批反推计时上限档位（秒），默认取配置 180")
    force_duplicates: bool = Field(False, description="跨批次重复**整批**强制入库（默认只提示不建）")
    force_urls: Optional[List[str]] = Field(
        None,
        description="逐条强制入库的链接（去重提示返回的 source_url 或原链接都行）：只放行点名的这几条，"
                    "别拿整批 force_duplicates 陪跑（A4-2）",
    )
    category_id: Optional[str] = Field(
        None,
        description="11-04 拍板①：本批**整批默认钩子原型**（导入抽屉那个下拉）。"
        "可留空（不设为必填），入库后每条仍可单独改；文案出稿时默认继承所属素材的这一列",
    )
    auto_download: bool = Field(
        True,
        description=(
            "11-06 用户拍板：链接任务添加后就直接下载原片，不用等反推、也不管解析费"
            "（0.01 元/条照记账，不再人工确认）。False 只留给测试/特殊脚本"
        ),
    )


class AnalyzeRequest(BaseModel):
    """批量反推提示词（真金白银的一步，必须带成本确认）。"""
    asset_ids: List[str] = Field(default_factory=list)
    max_duration: Optional[int] = Field(None, description="计时上限档位 60/180/300/600")
    confirmed: bool = Field(False, description="前端成本确认弹窗已确认（need_approval 级别必须为 true）")
    force: bool = Field(False, description="仅 admin：余额闸门 blocked 时强行提交（余额接口有波动）")
    retry_failed: bool = Field(False, description="重跑 stage_prompt=failed 的素材（默认跳过已跑过的）")
    download: bool = Field(
        True,
        description="批 J（11-05）：反推提交后**顺带把链接素材的原片下载到自有桶**（默认开，"
        "用户口径：反推是常规动作，回看原片不该再靠时效直链）。免费渠道解析不花钱，"
        "落到付费渠道按 0.01 元/条计入批次成本；存储只在桶里占地方，不设过期",
    )
    batch_id: Optional[str] = Field(
        None,
        description="A4-6 整批排队：不传 asset_ids，改按批次取「还没反推」的下一段（与 offset/limit 用）",
    )
    offset: int = Field(0, ge=0, description="游标：跳过队列头部 N 条。默认 0——提交成功的条会自己离开队列")
    limit: Optional[int] = Field(None, description="本段条数，默认取 ASSET_ANALYZE_MAX_PER_CALL，上限同它")
    cross_person_confirm: bool = Field(
        False,
        description="11-06 拍板②：涉及别人导入的批次时必须为 true（界面确认「替他人批次花钱」后带上）；"
        "自己的批次不用管这个字段",
    )
    async_mode: bool = Field(
        False,
        description="D-1：true＝闸门与成本确认全过之后当场回任务号，提交＋收敛在后台跑"
        "（页面按钮走 true）；false＝同步等提交跑完（收敛仍靠前端轮询）。"
        "行级单条重试保持 false——一条几秒就提交完，没必要过任务台账",
    )
    wait_converge: bool = Field(
        False,
        description="系统内部：后台任务（JOB_ANALYZE）提交完原地等智令收敛（含快速失败自动重试"
        "一次）。前端不要传这个字段——页面路径 async_mode=true 时由接口自己置上",
    )


class SummaryGenerateRequest(BaseModel):
    asset_ids: List[str] = Field(default_factory=list)
    count: Optional[int] = Field(None, description="每条候选数，默认 ASSET_HOOK_CANDIDATE_COUNT=1（11-06 起）")
    extra_requirements: Optional[str] = Field(None, description="给模型的补充要求（如题材/口吻）")
    overwrite: bool = Field(False, description="已有文案时是否重生成（默认保留历史候选，只补差额）")
    batch_id: Optional[str] = Field(
        None,
        description="A4-6 整批排队：不传 asset_ids，按批次取「反推已成功但还没出文案」的下一段",
    )
    offset: int = Field(0, ge=0, description="游标：跳过队列头部 N 条（某条反复失败时往后挪，默认 0）")
    limit: Optional[int] = Field(None, description="本段条数，默认取 ASSET_SUMMARY_MAX_PER_CALL，上限同它")
    retry_failed: bool = Field(
        False, description="整批排队时把 stage_summary=failed 的也捞回（默认只排没跑过的）"
    )
    async_mode: bool = Field(
        False,
        description="D-1：true＝立即回一个任务号（后台继续跑，前端轮询 /assets/jobs/任务号），"
        "false＝同步等到模型跑完（等几十秒到十几分钟，浏览器/nginx 都可能先掐）。"
        "页面按钮走 true；脚本/回归用例保持默认",
    )
    cross_person_confirm: bool = Field(
        False,
        description="11-06 拍板②：涉及别人导入的批次时必须为 true（界面确认「替他人批次花钱」后带上）",
    )


class RefreshBatchRequest(BaseModel):
    """A4-6：一次收敛整批在跑的反推任务（旧口径 200 条要发 200 次单条 refresh）。"""
    batch_id: Optional[str] = Field(None, description="按批次收敛 stage_prompt=running 的那批")
    asset_ids: List[str] = Field(default_factory=list, description="或点名若干条（两种都给 → 400）")
    limit: Optional[int] = Field(
        None, description="单次最多收敛多少条，默认/上限 = ASSET_ANALYZE_MAX_PER_CALL"
    )


class ResolveRequest(BaseModel):
    """D-5（11-03 拍板）：链接素材**按需回源解析**——显式点、显认、显付费的一次动作。

    没有 `force`：0.01 元/次不是大额，但它是一笔**会进批次成本的真实支出**，
    admin 也不该有一个跳过确认的按键；批次闸门 blocked 时正确动作是充值或改用直链。
    """
    asset_ids: List[str] = Field(default_factory=list, description="点名若干条链接素材")
    batch_id: Optional[str] = Field(
        None,
        description="整批排队：按批次取「链接素材且还没有时长」的下一段（与 asset_ids 二选一）",
    )
    offset: int = Field(0, ge=0, description="游标：跳过队列头部 N 条，默认 0")
    limit: Optional[int] = Field(None, description="本段条数，默认/上限 = ASSET_ANALYZE_MAX_PER_CALL")
    retake: bool = Field(
        False,
        description=(
            "11-06 播放直链修复：缓存直链过期后的唯一自愈出口。"
            "默认 False——有时长的条目走缓存回放（免费）或被跳过；"
            "True＝无视缓存强制重新解析（按渠道记账 0.01 元/次），给「直链打不开」的人重取用"
        ),
    )
    confirmed: bool = Field(False, description="≥2 条时必须为 true（成本确认弹窗已确认）")
    cross_person_confirm: bool = Field(
        False,
        description="11-06 拍板②：涉及别人导入的批次时必须为 true（界面确认「替他人批次花钱」后带上）",
    )


class AssetDownloadRequest(BaseModel):
    """批 J（11-05）：把链接素材的**原片**拉回自有桶。

    一般不用手工调——反推弹窗勾了「顺带下载原片」（默认勾）时，反推提交完会自动排上；
    这个口是下载任务的执行体，也留给「某条下载失败了想单独重试」的场景。
    """
    asset_ids: List[str] = Field(default_factory=list, description="要点名：只下载这些链接素材")
    async_mode: bool = Field(
        False,
        description="D-1：页面走 true 提交即回任务号；后台复跑时运行器会把它摘掉，防止无限套娃",
    )
    cross_person_confirm: bool = Field(
        False,
        description="11-06 拍板②：涉及别人导入的批次时必须为 true（界面确认「替他人批次花钱」后带上）",
    )


class PromptPreviewRequest(BaseModel):
    """批 J（11-05）：过审文案 → 豆包生产提示词**预览**。

    同样是任务的执行体：文案一过审，审核口自动排上；某条预览失败想补，
    也点名 summary_ids 走这个口。
    """
    summary_ids: List[str] = Field(default_factory=list, description="要备提示词的文案（必须是已过审的）")
    async_mode: bool = Field(False, description="D-1：过审口自动排 true；手工补跑同口")


class FramesExtractRequest(BaseModel):
    """抽帧（批 F）：给素材抽 3 张单帧 + 1 张九宫格，给产物抽 1 张首帧。

    这条请求模型同时是**后台任务 params 的形状**（`_job_endpoint(JOB_FRAMES)` 回到这里），
    所以字段必须能 `model_dump(mode="json")` 后原样再喂给自己。
    """
    asset_ids: List[str] = Field(default_factory=list, description="点名若干条素材")
    output_ids: List[str] = Field(default_factory=list, description="点名若干产物（每个补 1 张 output_thumb）")
    force: bool = Field(False, description="已有帧也重抽（默认跳过，省一次下载＋ffmpeg）")
    async_mode: bool = Field(False, description="true＝排后台任务立即回任务号；导入侧自动排的那条走这里")


class ReviewRequest(BaseModel):
    """批量审核。action: approve / reject / need_rewrite / pass_edited（改后通过）。"""
    summary_ids: List[str] = Field(default_factory=list)
    action: str
    reason: Optional[str] = Field(None, description="驳回/需改写必填理由")
    new_text: Optional[str] = Field(None, description="pass_edited 时的改后文案")
    waive_reason: Optional[str] = Field(
        None,
        description="仅 admin：复核未过但确需过审时的豁免理由，会写进 AuditLog。"
        "R-6 后真拦点只剩超字数(shape)与高风险词(risk)——一致性已降为预警，不再需要豁免",
    )
    waive_codes: Optional[List[str]] = Field(
        None,
        description="R-6：只豁免这几类问题（shape/risk，可选其一）；留空＝沿用「整条全豁免」。"
        "只想放过字数不想放过违禁词时就传 [\"shape\"]",
    )


class ResubmitRequest(BaseModel):
    """改后重新提审：被驳回/需改写的文案，改完交回待审队列。

    谁可以提：**这条素材的负责人（导入人，＝出文案的人）或 admin**。
    为什么不给「谁点的审核谁就能改」——那等于审核人自己给自己擦屁股；
    也不给「所有有写权限的人」——文案责任人是素材负责人，不是路人。
    """
    summary_ids: List[str] = Field(default_factory=list)
    new_text: Optional[str] = Field(None, description="改后的文案；留空＝不改文案直接回队列重审")
    note: Optional[str] = Field(None, description="给审核人的说明（会写进审计）")


class ProduceRequest(BaseModel):
    """过审文案 → N 条差异化提示词（生产单）。N 的语义见 asset_models 注释。

    ⚠️ 这里**没有** account_id / browser_port：生产走企微后台任务板（`wework_aivideo`），
    豆包号由后台自己派，我们侧不指定号、也没有端口（旧 RPA 概念）。两列保留在表里
    只为不丢历史，P0 起不接受前端传。
    """
    summary_ids: List[str] = Field(default_factory=list)
    n: Optional[int] = Field(None, description="每条文案派生的份数（N 份差异化提示词=N 个任务），默认 ASSET_PRODUCE_DEFAULT_N")
    duration: Optional[int] = Field(None, description="**意图字段**：板上无时长开关，成片恒 10.08s；只接受 10，更长请拆上/下集两条各 10s")
    channel: Optional[str] = Field(None, description="wework_aivideo（默认，= 企微后台 AI 视频任务板）/ doubao_rpa(deprecated) / seedance_api")
    accounts: Optional[int] = Field(None, description="准备用几个豆包号跑（仅用于折算天数；后台派号，本系统无号池表）")
    expand: bool = Field(True, description="是否调 autoclip 按 11-02 权威模板展开成可投提示词")
    board_total: Optional[int] = Field(None, description="板上 total＝**同一条提示词出几版**（1..20，默认 1）。与 n 是两个量，混用会白烧 n×total")
    board_tag: Optional[str] = Field(None, description="板上 tag（拥有者标记），缺省用 ASSET_BOARD_TAG；不填=无主任务、按天筛不到")
    hook_codes: Optional[List[str]] = Field(None, description="五位钩子编号（hook_id.py 取来的，按 n 的顺序对应）；后端不自己编号")
    character_card_key: Optional[str] = Field(None, description="角色卡在自有桶的 key → 板上 picDatas 来源（同剧同卡，按剧分组投）")
    cross_person_confirm: bool = Field(
        False,
        description="A′ 归属跨人确认：投**别人过审**的候选（reviewed_by≠操作者）必须 true——谁投账算谁，候选过审人进审计；投自己过审的或无主公共候选不用带",
    )

    @field_validator("character_card_key")
    @classmethod
    def _card_key_must_be_asset_key(cls, v: Optional[str]) -> Optional[str]:
        # 客户端可控的对象 key 直接读 raw 桶（审计 S5）。历史 key 形状杂（asset-cards/、
        # cards/ 等），前缀白名单会误伤存量单——降级为形状校验：禁绝对路径/穿越/反斜杠，
        # 防 key 逃出预期目录；桶内素材本就对全员可见，跨对象引用风险审计定级低。
        if v is not None:
            if v.startswith("/") or v.startswith("\\") or ".." in v or "\\" in v:
                raise ValueError("character_card_key 不允许绝对路径或 .. 穿越")
        return v
    card_asset_ids: Optional[List[str]] = Field(
        None,
        description="批 G：从素材库挑的角色卡（asset_items.id 数组，**顺序＝板上 picDatas 顺序**）。"
        "传了它就以它为准，`character_card_key` 只作旧前端的兼容路径。"
        "只收图片素材：视频当卡用＝投一张会动的图，板侧不认且没人看得出问题",
    )
    recommended_title_count: Optional[int] = Field(None, description="K＝该剧发布号数，决定推荐视频标题条数（11-02 版：不再固定 5 条）")
    drama_abbr: Optional[str] = Field(
        None,
        description="剧名缩写（取自 NAS《剧名缩写表.json》，全团队统一、禁止临时造）。"
                    "推荐标题按 3.1 精简规范要写「剧缩·编号·精简钩子」；不传则模板降级写"
                    "「编号·精简钩子」并在偏差说明里标注缺剧缩，缩写表在容器里读不到，只能由一线带",
    )
    waive_reason: Optional[str] = Field(
        None,
        description="仅 admin：投产前复核（超字数/高风险词）未过仍要投递时的豁免理由，写进 AuditLog",
    )
    waive_codes: Optional[List[str]] = Field(
        None,
        description="R-6：只豁免这几类问题（shape/risk）；留空＝整条全豁免。"
        "展开后复扫新发现的 risk 命中（模型自己加的违禁词）不在豁免范围内，仍会拦下",
    )
    element_values: Optional[Dict[str, List[str]]] = Field(
        None,
        description="批 P（11-10 用户口径「可自定义填入多个场景词、动物名称，一次性生成多条钩子视频」）："
        "槽位键 → **要换上去的多个值**，一个值一条片。0 元、不再调模型——它是在已经展开好的那份正文上"
        "做字面替换后另立单，与 `n`（调模型派生差异化提示词）是两回事。留空＝不扇出，走今天同一条路径。",
    )
    element_base: Optional[Dict[str, str]] = Field(
        None,
        description="槽位键 → **这份稿子里现在的值**（④开单屏从原稿自动提取、或人手抄的原句）。"
        "没有原值就无从替换：那一行照原文落单并在结果里点名（不拿旧值当新值、也不静默跳过）",
    )
    element_base_by_summary: Optional[Dict[str, Dict[str, str]]] = Field(
        None,
        description="批 P：一次开多条文稿时，各篇的**原值本来就不一样**（这条的场景是「河边」、下条是「工地」），"
        "共用一份 `element_base` 会把第二篇的替换悄悄做在错误的词面上。这里按 summary_id 各给一份原值；"
        "`element_base` 退化成公共兜底（同键以这里的值优先）。",
    )
    element_mode: str = Field(
        "zip",
        description="多值怎么配对：zip＝按行配对（第1个场景配第1只动物…，只填一个值的每行复用；默认）、"
        "product＝全组合（场景数×动物数条，上限 100 行）",
    )
    async_mode: bool = Field(
        False,
        description="D-1：true＝立即回一个任务号（展开提示词要等模型，后台跑完再轮询取结果），"
        "false＝同步等到底（脚本/回归用例走这条，页面按钮走 true）",
    )


class ProductionStatusRequest(BaseModel):
    """投递状态回写（11-03 拍板第 4 条：号池**不做硬限**，但要知道投了多少、成多少、败多少）。

    这条路是「**人工投板之后补账**」：导出 payload → 人在企微后台任务板建任务 → 回这里记账。
    11-05 批 H 起多了另一条入口 `POST /assets/productions/dispatch`（机器连板、自动回收成片），
    四条状态由此变成**两个写入方**——所以别在这里把机器已经投好的结果再报一遍。
    没有回写口时列表会永远停在 order_ready，对账页也就无从解释「昨天投的 120 条到手几条」。
    只做三件事：改状态、补 board_tid 回读主键、记审计——不碰成本、不建产物、不自动重试。
    """
    ids: List[str] = Field(default_factory=list, description="生产单 id 列表（单次上限 ASSET_ANALYZE_MAX_PER_CALL）")
    status: str = Field(
        ...,
        description="投递态：queued（已投上板）/ running（出片中）/ success（成片到手）/ failed（失败或不出片）",
    )
    error: Optional[str] = Field(
        None,
        description="失败成因（我们侧判读；板上失败行没有原因字段，别当成豆包给的成因）；判 failed 时必填",
    )
    board_tid: Optional[str] = Field(None, description="回读主键（info?date= 返回的 tid），逐条钉上便于二次对账")


class DispatchRequest(BaseModel):
    """自动投板（11-05 批 H）：把已经建好的生产单真投上企微后台任务板，并回收成片。

    拍板口径是「**可自动投板，但逐批人工确认**」——机器连板、人负责点那一下确认，
    所以这里没有"整批自动排队今晚全投掉"的入口：`ids` 必须是**点名的一批**，
    且 `confirm` 不带 true 就当没确认过（400 回去，绝不代签）。
    """
    ids: List[str] = Field(
        default_factory=list,
        description="要点名投板的生产单 id（单次上限 ASSET_DISPATCH_MAX_PER_CALL，默认 20）",
    )
    confirm: bool = Field(
        False,
        description="人工确认位：必须 true。投出去占的是当天号池额度，且板侧失败行没有原因字段，"
        "所以这一下只能由人点，不能由脚本代签",
    )
    force_risk: bool = Field(
        False,
        description="仅 admin：文案过审后词表又加过词、仍要投这几张（和导出侧 R-4 同一道闸、同一个口径）",
    )
    force_reason: Optional[str] = Field(
        None, description="force_risk 的理由（必填，进 AuditLog）"
    )
    recover_only: bool = Field(
        False,
        description="true＝**一个都不新建**，只对已有 board_tid 的单做回读＋回收下载。"
        "进程重启把在等的协程带走之后（任务台账显示已中断），用这个把片子取回来；"
        "它不烧任何号池额度，所以不看 confirm",
    )
    async_mode: bool = Field(
        True,
        description="默认 true：投板＝建任务＋轮询出片＋下载落桶，整段几十分钟，"
        "同步等必然顶穿超时链（前端 960s / 后端 900s）。false 只留给后台协程与回归用例",
    )
    cross_person_confirm: bool = Field(
        False,
        description="11-06 拍板②：新建板任务涉及别人导入的批次时必须为 true（回收已投的单不花钱，不用这个字段）",
    )
    card_asset_ids: Optional[List[str]] = Field(
        None,
        description=(
            "投板前统一挂卡（人物三视图）。给出时（含空数组＝清卡）对**本次要新建**的每张单"
            "覆盖写入 card_asset_ids／兼容单值列（与 produce 同一套写法，第 1 张＝板上主形象），"
            "并走 _resolve_card_assets 同一道校验（脏 id 当场 400）。单行从此带这张卡——"
            "卡是生产输入，改的就是单本身；回收档（已有 tid）不动。"
            "不传＝各单沿用自己已带的卡。"
        ),
    )
    prompt_overrides: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "11-06 拍板：投递稿可改。生产单 id → **这一次投出去**的提示词正文。"
            "只改投出去的那一份：库里的 prompt_text／过审文案一字不动，漂移判定不受影响，"
            "下一次再投仍用原稿。改后的正文照走 block 级风险词重扫（命中照样拦，"
            "或 admin 带 force_risk+理由放行——与原稿同一道闸），逐条留审计"
        ),
    )
    concat_asset_id: Optional[str] = Field(
        None,
        description=(
            "11-10 批 Q（需求⑤）：这几张单回收到的**每一支豆包成片**，出片后自动和这条素材"
            "（asset_items.id）拼成一条可投放素材。传空串＝取消自动拼。"
            "当场验三段：素材存在／不是图片／桶里有文件——和图片拼会在 ffmpeg 解码时炸，"
            "和没文件的链接素材拼会在下载那步炸，两种都要在投出去之前拦（号池已经烧了才发现"
            "拼不了，只能重投一遍）"
        ),
    )
    concat_order: Optional[str] = Field(
        None,
        description=(
            f"拼的顺序：{' 或 '.join(compose.AUTO_CONCAT_ORDERS)}"
            f"（留空＝{compose.DEFAULT_AUTO_CONCAT_ORDER}，钩子片在前）。"
            "和手工口 /assets/concat 的 order 不是同一套词：那两边段的位置含义不同，"
            "共用字面量会拼反"
        ),
    )


# 投递稿改后的长度上限（板上 prompt 字段没有硬上限，这里是防呆：把整篇文档粘进来）
_PROMPT_OVERRIDE_MAX_LEN = 8000


class CategoryUpsertItem(BaseModel):
    """字典行（PUT /assets/categories 的一条）。`id` 留空＝新增，带 id＝改这一行。"""
    id: Optional[str] = Field(None, description="已有行的 id；留空＝新增")
    name: str = Field(..., description="原型名（唯一）。初始 7 行照《钩子模版换皮参数设定.docx》原名")
    sort: Optional[int] = Field(None, description="展示顺序，小的在前；留空＝排到最后")
    active: bool = Field(True, description="false＝下线：不再供新条目挑选，历史条目仍显示仍可筛")
    note: Optional[str] = Field(None, description="行内说明（纯展示，不参与任何判定）")


class CategoriesUpdateRequest(BaseModel):
    """改字典（仅 admin）。

    ⚠️ **整单语义**：`items` 是"你希望字典长这样"。带 id 的改、不带 id 的增、
    **本次没列出来的既有行＝下线（active=false），不硬删**。
    为什么不硬删：素材/文案上的 category_id 是真实引用，删行会让一线点好的分类
    静默变空（而且 FK 是 SET NULL，数据库不会拦你）。
    """
    items: List[CategoryUpsertItem] = Field(default_factory=list)


class CategoryAssignRequest(BaseModel):
    """给素材/文案点分类（11-04 拍板①：纯人工点）。

    `category_id` 留空＝**清空分类**（回到"未分类"），不是删素材。
    两个 id 列表至少给一个；同一次请求里素材与文案各自计数、各自留审计。
    """
    asset_ids: List[str] = Field(default_factory=list, description="点名若干条素材")
    summary_ids: List[str] = Field(default_factory=list, description="点名若干条文案")
    category_id: Optional[str] = Field(None, description="目标原型 id；留空＝清成未分类")


class HookCodeParkItem(BaseModel):
    """一行＝一个号钉在一行上。`summary_id` / `production_id` 二选一。"""
    summary_id: Optional[str] = Field(None, description="文案 id（预取：号先挂在文案上等开单）")
    production_id: Optional[str] = Field(None, description="生产单 id（补号：号直接钉在已建好的单上）")
    hook_code: Optional[str] = Field(None, description="五位编号；留空＝把这一行的预取位/编号清空")


class HookCodeParkRequest(BaseModel):
    items: List[HookCodeParkItem] = Field(default_factory=list, description="逐行点名，一次最多 100 行")


# ──────────────────────────────────────────────
# 通用辅助
# ──────────────────────────────────────────────


async def _write_audit(
    db: AsyncSession,
    *,
    action: str,
    operator: Optional[User],
    target_type: str,
    target_id: Optional[str],
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    strict: bool = False,
) -> None:
    """写一条审计（与 api/auth.py 的 _write_audit 同形，默认 fail-soft）。

    默认 fail-soft：审计写失败绝不拖垮主流程——批量操作里一条审计异常把整批回滚
    是更严重的事故。
    `strict=True`（11-06 拍板①）只给 **force/waive 类**动作用：这类动作恰恰是最
    必须留痕的（绕过闸门/豁免复核），审计写失败就拒绝整个操作——宁可让人重做一次，
    也不能留下「绕过了闸门却查无此事」的记录。普通动作一律不要开 strict。
    """
    try:
        db.add(
            AuditLog(
                operator_id=operator.id if operator else None,
                operator_name=operator.username if operator else None,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id else None,
                before=before,
                after=after,
            )
        )
        await db.flush()
    except Exception:
        if strict:
            raise
        logger.exception("素材库审计写入失败 action=%s target=%s", action, target_type)


_CROSS_MARKER = "替他人批次花钱"
# A′：归属跨人（投别人过审的候选）的固定点名短语，前端 withCrossOwnerConfirm 靠它识别
_CROSS_OWNER_MARKER = "替他人过审候选投产"


async def _user_names(db: AsyncSession, uids: set) -> Dict[str, str]:
    """id → 显示名（display_name 优先，退 username）。

    A′（2026-11-07 按运营隔离）：序列化层**一次聚合**用——三读口的归属人灰字
    全走这里，绝不在行循环里逐行查用户表（先例：_cross_person_gate 的 names 段）。
    """
    ids = {u for u in uids if u}
    if not ids:
        return {}
    return {
        str(uid): (dn or un) or "未知（账号已删）"
        for uid, dn, un in (
            await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids)))
        ).all()
    }


async def _cross_person_gate(
    db: AsyncSession,
    *,
    operator: Optional[User],
    batch_ids: List[Any],
    action_label: str,
    confirmed: bool,
) -> List[dict]:
    """11-06 拍板②：跨人批次的花钱动作先拦一道，确认后再放行并留痕。

    「跨人」＝这批素材的导入人（`asset_batches.created_by`）不是本次操作者。
    内容全量可见（11-03 拍板）不受影响——看、审、导 payload 都照旧零门槛；只有
    **会花钱/占号池**的动作才走这里：费用记到批次成本上，替别人批次花了钱，
    事后对账会找不到是谁的手笔。所以要么当场拦下来让人确认（400，前端弹窗），
    要么确认后把「发起人≠批次主人」原样写进审计。批次归属未知（created_by 为空、
    老数据）不拦——没有凭据说它跨人，就不预判。
    """
    ids = {b for b in batch_ids if b}
    if not ids or operator is None:
        return []
    rows = list((await db.execute(select(AssetBatch).where(AssetBatch.id.in_(ids)))).scalars().all())
    if not rows:
        return []
    owner_uids = {r.created_by for r in rows if r.created_by}
    names: Dict[str, str] = {}
    if owner_uids:
        for uid, dn, un in (
            await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(owner_uids)))
        ).all():
            names[str(uid)] = (dn or un) or "未知（账号已删）"
    op_key = str(operator.id)
    crosses: List[dict] = []
    for r in rows:
        if r.created_by is None or str(r.created_by) == op_key:
            continue
        crosses.append({
            "batch_id": str(r.id),
            "batch_code": r.code,
            "batch_owner_id": str(r.created_by),
            "batch_owner": names.get(str(r.created_by), "未知（账号已删）"),
            "operator_id": op_key,
            "operator": operator.username,
        })
    if crosses and not confirmed:
        shown = "；".join(f"{c['batch_code']}（导入人 {c['batch_owner']}）" for c in crosses[:5])
        more = f"（另有 {len(crosses) - 5} 批，本条只列前 5 批）" if len(crosses) > 5 else ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"{action_label}涉及{_CROSS_MARKER}：{shown}{more}。费用会记到批次成本上，"
                "请先确认你确实是替这位同事操作（补单/代班）；界面弹窗里点「确认替他人批次操作」"
                "后再发一次（带 cross_person_confirm=true），这一次没有动账。"
            ),
        )
    return crosses


def _as_uuid(value: Any, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail=f"{field} 不是合法 ID")


# ─────────────────────────  可见范围口径  ─────────────────────────
# 11-03 用户拍板（覆盖设计方案 §七 与审核报告 D-3）：**素材内容全量可见，不分权限**。
# 原先两套口径（素材 data_scope=own + 审核投产跨人）一并取消——两套口径在交付链上是
# 矛盾的：运营能把别人导入的素材导出成投放提示词，却下不到它自己的产物，只能借导入人
# 的账号下载，一借，A2-4 那条交付审计就记成别人了。
# 保留的是**角色权限**（谁能写）：导入/反推/出文案 = 素材专员+运营+管理员，
# 审核/投产 = 运营+管理员，「生产者不得自审」仍由 review 接口的 created_by 判据兜住；
# 取消的是**行级可见范围**（谁能看），全部登录用户看得到全部素材/批次/文案/生产单/产物。
# `created_by` 列照旧写入并出现在列表里，只是不再用来过滤。


async def _get_asset_or_404(db: AsyncSession, asset_id: Any) -> AssetItem:
    aid = _as_uuid(asset_id, "asset_id")
    asset = (
        await db.execute(select(AssetItem).where(AssetItem.id == aid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return asset


# 余额闸门的单位口径：budget_gate 全程按**元**比较，而余量接口返回的数是什么单位
# 取决于 WECHAT_DL_<P>_QUOTA_UNIT（默认是「次」）。硬比会把「剩 30000 次」当成
# 「剩 3 万元」——那不叫熔断，叫假保险。换算不出来就按「余额未知」处理。
# 0.001 元/点 由单价本身反推：0.00054 元/秒 == 0.54 点/秒（prompt_client.py:11）。
_QUOTA_UNIT_TO_YUAN = {"元": 1.0, "cny": 1.0, "rmb": 1.0, "点": 0.001, "点数": 0.001}


async def _query_zhiling_balance_detail() -> Dict[str, Any]:
    """查智令余量并折算成**元**。

    只认 zhiling 通道：`fetch_provider_balances` 会遍历 WECHAT_DL_PROVIDERS 全链，
    别的钱包（wxshares 等）的余额不是智令的额度，"取第一个有数值的通道"那种兜底
    等于拿别人的钱包给自己的消费设限（A1-1）。查不到就如实返回 None + 原因。
    """
    detail: Dict[str, Any] = {"balance": None, "unit": None, "note": None}
    try:
        balances = await fetch_provider_balances()
    except Exception as e:
        logger.warning("智令余额查询异常：%s", e)
        detail["note"] = f"余额查询异常：{e}"
        return detail
    hit: Dict[str, Any] = {}
    raw: Dict[str, Any] = {}
    for channel in ("zhiling", "17zhiling"):
        cand = balances.get(channel) or {}
        if cand:
            raw = cand
        if isinstance(cand.get("balance"), (int, float)):
            hit = cand
            break
    if not hit:
        detail["note"] = _balance_miss_note(raw)
        return detail
    unit = str(hit.get("unit") or "").strip().lower()
    factor = _QUOTA_UNIT_TO_YUAN.get(unit)
    if factor is None:
        detail["unit"] = unit or None
        detail["note"] = (
            f"余量单位「{unit or '未声明'}」换算不到元，本批按余额未知处理"
            "（次/秒/条不能当元比较；确认单位后配 WECHAT_DL_ZHILING_QUOTA_UNIT）"
        )
        return detail
    detail["balance"] = round(float(hit["balance"]) * factor, 4)
    detail["unit"] = unit
    return detail


def _balance_miss_note(raw: Dict[str, Any]) -> str:
    """余量查不到时说清**到底卡在哪一环**——原来一句话全推给「未配置」，可现网实测
    是另一种情况：三行都配了、服务商根本没有余量接口，运维照着提示再配一遍也还是无数。

    三种原因分开报（11-03 接 163 现网时按实测口径拆的）：
      ① 链里没 zhiling / 没 BASE → build_providers 直接跳过，压根没建这个适配器；
      ② 建起来了但没配 QUOTA_PATH → 不查询；
      ③ 查了但接口报错（智令实测：/api/user/balance 等 12 个候选路径全 404）→ 带原始错误。
    """
    chain = (os.getenv("WECHAT_DL_PROVIDERS", "") or "").lower()
    base = (os.getenv("WECHAT_DL_ZHILING_BASE", "") or "").strip()
    if "zhiling" not in chain or not base:
        return (
            "余额闸门未生效：智令适配器没建起来——"
            f"WECHAT_DL_PROVIDERS 需含 zhiling（当前「{chain or '未配置'}」），"
            f"WECHAT_DL_ZHILING_BASE 必填（当前{'已配' if base else '未配置'}）"
        )
    if not (os.getenv("WECHAT_DL_ZHILING_QUOTA_PATH", "") or "").strip():
        return (
            "余额闸门未生效：未配 WECHAT_DL_ZHILING_QUOTA_PATH（不配＝不查询＝余额未知）。"
            "注意智令**实测无对外余量接口**，填了也可能是 404，先确认接口存在再配"
        )
    err = str(raw.get("error") or "").strip()
    return (
        f"余额闸门未生效：余量接口已调用但未取到数（{err or '响应里没找到该字段'}）"
        "——智令 11-03 实测无对外余量接口，本批按「余额未知＝放行 + 事后对账」执行，"
        "不是接口故障，也不代表闸门已开"
    )


# 风险词表 TTL 缓存：审核/投产/导出每个动作都要扫几遍，逐条查 system_config 太碎；
# 但绝不能像原来那样硬编码在代码里（改一个词要发版）。运维改配置最多等一个 TTL 生效。
_RISK_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}


async def _risk_lexicon(db: AsyncSession) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
    """读风险词表（A2-3）：`system_config.key='asset_risk_lexicon'`，带 TTL 缓存。

    配置形态（block/warn 是词数组，exempt 是「词 → 豁免正则」）：
        {"block": ["新禁词"], "warn": ["全网最低价"], "exempt": {"第一": "第一次|第一时间"},
         "inherit": true}
    `inherit` 缺省为 true＝在默认表上**追加**（运营加几个词不会把主表清空）；写 false 才整体替换。
    查不到、结构不合法、级别写错 → 一律回落默认表：**宁可多拦，不能因配置写错变成全放行**。
    """
    ttl = max(0, int(settings.ASSET_RISK_LEXICON_TTL_SECONDS))
    now = time.monotonic()
    if ttl and _RISK_CACHE["payload"] is not None and now - _RISK_CACHE["at"] < ttl:
        return _RISK_CACHE["payload"]

    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.key == svc.RISK_LEXICON_CONFIG_KEY))
    ).scalar_one_or_none()
    value = row.value if row is not None else None
    lexicon, exemptions = svc.merge_risk_config(value)

    payload = svc.normalize_risk_lexicon(lexicon, exemptions)
    _RISK_CACHE["at"], _RISK_CACHE["payload"] = now, payload
    return payload


def _risk_cache_invalidate() -> None:
    """改完词表立刻失效缓存（不等 TTL）：运营加一个词就要马上拦得住。"""
    _RISK_CACHE["at"], _RISK_CACHE["payload"] = 0.0, None


# ─────────────────────  钩子原型字典（11-04 拍板①）  ─────────────────────
# 字典与风险词表是同一类东西（"运营能改、全员要读、不进模型提示词"），所以形态照
# risk-lexicon：读用 `_PROD_ROLES`、写只 admin、改动写 AuditLog。
# 与词表不同的一点：字典是**表**不是 system_config——素材/文案要按它筛选，
# JSON 里存的名单没法 join，也没法给每行挂"下线"状态与引用计数。

async def _category_rows(db: AsyncSession, *, include_inactive: bool = True) -> List[AssetCategory]:
    """整张字典（行数是个位数，不做分页）。默认含下线行：历史条目挂在下线行上，
    列表页要能显示它的名字，审核台也要能按它筛。"""
    stmt = select(AssetCategory)
    if not include_inactive:
        stmt = stmt.where(AssetCategory.active.is_(True))
    stmt = stmt.order_by(AssetCategory.sort.asc(), AssetCategory.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


def _serialize_category(c: AssetCategory, usage: Optional[dict] = None) -> dict:
    data = {
        "id": str(c.id),
        "name": c.name,
        "parent_id": str(c.parent_id) if c.parent_id else None,
        "sort": c.sort,
        "active": bool(c.active),
        "note": c.note,
        "created_at": utc_iso(c.created_at),
        "updated_at": utc_iso(c.updated_at),
    }
    if usage:
        data.update(usage)
    return data


async def _category_usage(db: AsyncSession) -> Dict[str, Dict[str, int]]:
    """每个分类被引用了多少次（素材 / 文案各算各的），给字典抽屉显示"这条挂着 N 条素材"。

    为什么要在意这个数：下线容易、删干净难。admin 看到引用数是 0 才谈得上真删，
    有引用的行只能 `active=false`（见 CategoriesUpdateRequest 的整单语义）。
    """
    usage: Dict[str, Dict[str, int]] = {}
    for model, key in ((AssetItem, "asset_count"), (AssetSummary, "copy_count")):
        rows = (
            await db.execute(
                select(model.category_id, func.count(model.id))
                .where(model.category_id.is_not(None))
                .group_by(model.category_id)
            )
        ).all()
        for cid, cnt in rows:
            if cid is None:
                continue
            usage.setdefault(str(cid), {"asset_count": 0, "copy_count": 0})[key] = int(cnt or 0)
    return usage


async def _resolve_category_or_400(db: AsyncSession, category_id: Optional[str], field: str = "category_id") -> Optional[uuid.UUID]:
    """把入参的分类 id 校验成 UUID；留空＝未分类（**不是"不改"，是"清成空"**）。

    只认存在的行；`active=false` 的行**允许写**吗——不允许：新条目挑一个已下线的原型
    说明字典和一线对不上，与其静默收下不如当场说清（历史引用仍然可读可筛，只有写入这条路拦）。
    """
    if category_id is None or not str(category_id).strip():
        return None
    cid = _as_uuid(category_id, field)
    row = (await db.execute(select(AssetCategory).where(AssetCategory.id == cid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail=f"{field} 指向一个不存在的原型分类，请重新挑选")
    if not row.active:
        raise HTTPException(status_code=400, detail=f"「{row.name}」已下线，不能再挂新条目，请改挑在用的原型")
    return cid


async def _category_name_map(db: AsyncSession) -> Dict[str, str]:
    """id → 名称（序列化时补 `category_name`，避免逐行查）。"""
    return {str(c.id): c.name for c in await _category_rows(db)}


def _category_cond(category_id: Optional[str]):
    """列表筛选：传 id 按该原型筛；传 `none`／`unclassified` 筛未分类；留空不筛。"""
    if category_id is None or not str(category_id).strip():
        return None
    token = str(category_id).strip().lower()
    if token in ("none", "unclassified", "null"):
        return "none"
    return _as_uuid(category_id, "category_id")


@router.get("/assets/categories")
async def list_categories(
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """读钩子原型字典（11-04 拍板①）。全员可读——被分类筛出来的人有权知道自己被归到哪。

    读到空表时兜底种一次初始 7 行：老库刚建完表、服务还没重启过的窗口，
    抽屉不该是空的（种入按 name 幂等，重复调用不会插出第二份）。
    """
    if not await _category_rows(db):
        from app.database import ensure_default_asset_categories

        await ensure_default_asset_categories(db)
        await db.flush()
    rows = await _category_rows(db)
    usage = await _category_usage(db)
    unclassified = {
        "asset_count": int(
            (
                await db.execute(
                    select(func.count(AssetItem.id)).where(AssetItem.category_id.is_(None))
                )
            ).scalar_one()
            or 0
        ),
        "copy_count": int(
            (
                await db.execute(
                    select(func.count(AssetSummary.id)).where(AssetSummary.category_id.is_(None))
                )
            ).scalar_one()
            or 0
        ),
    }
    return {
        "items": [_serialize_category(c, usage.get(str(c.id))) for c in rows],
        "unclassified": unclassified,
        "can_edit": current_user.role == UserRole.admin.value,
        "note": (
            "分类是**纯人工点**的（11-04 拍板③）：不填也能走完全链，"
            "但出文案的提示词模板不读这一列，所以没分类的素材不会自动归类。"
        ),
    }


@router.put("/assets/categories")
async def update_categories(
    data: CategoriesUpdateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """改钩子原型字典（仅 admin，形态与风险词库一致：保存即生效、改动进审计）。

    整单语义（见 `CategoriesUpdateRequest`）：带 id 改、不带 id 增、没列出来的既有行**下线**。
    下线的行不删——素材/文案上还挂着引用，删了会把一线点好的分类静默清空。
    """
    items = data.items or []
    names: List[str] = []
    for it in items:
        nm = str(it.name or "").strip()
        if not nm:
            raise HTTPException(status_code=400, detail="原型名称不能为空")
        if nm in names:
            raise HTTPException(status_code=400, detail=f"字典里有重名的原型：{nm}（同名会撞唯一约束，请先去掉一个）")
        names.append(nm)

    existing = {str(c.id): c for c in await _category_rows(db)}
    before = [
        {"id": str(c.id), "name": c.name, "sort": c.sort, "active": bool(c.active), "note": c.note}
        for c in existing.values()
    ]

    touched: List[AssetCategory] = []
    added = updated = retired = 0
    for seq, it in enumerate(items):
        cid = it.id.strip() if it.id else ""
        if cid:
            row = existing.get(cid)
            if row is None:
                raise HTTPException(status_code=400, detail=f"字典里没有 id={cid} 这一行，请刷新后再改")
            row.name = str(it.name).strip()
            row.sort = int(it.sort) if it.sort is not None else row.sort
            row.active = bool(it.active)
            row.note = (it.note or None)
            updated += 1
        else:
            row = AssetCategory(
                name=str(it.name).strip(),
                # 新增行没给 sort 就排到最后（按提交顺序依次后延），不要挤进 A–G 中间
                sort=int(it.sort) if it.sort is not None else 1000 + seq,
                active=bool(it.active),
                note=(it.note or None),
                created_by=current_user.id,
            )
            db.add(row)
            added += 1
        touched.append(row)
    await db.flush()

    # 没列出来的既有行＝下线（不硬删）
    touched_ids = {str(r.id) for r in touched}
    retired_names: List[str] = []
    for cid, row in existing.items():
        if cid in touched_ids or not row.active:
            continue
        row.active = False
        retired += 1
        retired_names.append(row.name)
    await db.flush()

    after = [
        {"id": str(r.id), "name": r.name, "sort": r.sort, "active": bool(r.active), "note": r.note}
        for r in touched
    ]
    await _write_audit(
        db,
        action="asset.categories.update",
        operator=current_user,
        target_type="asset_categories",
        target_id="asset_categories",
        before={"items": before},
        after={"items": after, "retired": retired_names},
    )
    usage = await _category_usage(db)
    rows = await _category_rows(db)
    return {
        "ok": True,
        "added": added,
        "updated": updated,
        "retired": retired,
        "items": [_serialize_category(c, usage.get(str(c.id))) for c in rows],
        "notes": (
            [f"已下线（未删除）：{n}" for n in retired_names]
            if retired_names
            else []
        )
        + ["改名/调整顺序会即时反映到列表与下拉；历史条目的引用不受影响"],
    }


@router.post("/assets/categories/assign")
async def assign_category(
    data: CategoryAssignRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """给素材/文案点钩子原型（11-04 拍板①：纯人工点，可不填，也可改回来）。

    审计：素材侧记 before/after 的 category_id；文案侧同样留痕（手法同 `text_before_edit`——
    改前的值一定要能查回来，否则"这条为什么算 D"事后没人答得上）。
    """
    asset_ids = [str(x) for x in (data.asset_ids or []) if str(x or "").strip()]
    summary_ids = [str(x) for x in (data.summary_ids or []) if str(x or "").strip()]
    if not asset_ids and not summary_ids:
        raise HTTPException(status_code=400, detail="请至少点名一条素材或一条文案")
    total = len(set(asset_ids)) + len(set(summary_ids))
    # 单次条数借「单批导入上限」这个旋钮（`ASSET_IMPORT_BATCH_MAX`）：语义是
    # "一次批量动作最多动多少行"，与反推/出文案的 20 条上限不是一回事——
    # 点分类不花钱、不等模型，卡 20 会让人一次只能挑一屏。
    cap = int(settings.ASSET_IMPORT_BATCH_MAX)
    if total > cap:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多点 {cap} 条，当前 {total} 条——分批点，别一把改完整个库",
        )
    cid = await _resolve_category_or_400(db, data.category_id)

    changed_assets: List[dict] = []
    missing_assets: List[str] = []
    if asset_ids:
        uuids = [_as_uuid(x, "asset_ids") for x in dict.fromkeys(asset_ids)]
        rows = list((await db.execute(select(AssetItem).where(AssetItem.id.in_(uuids)))).scalars().all())
        found = {str(r.id) for r in rows}
        missing_assets = [x for x in dict.fromkeys(asset_ids) if x not in found]
        for row in rows:
            if row.category_id == cid:
                continue
            changed_assets.append({"id": str(row.id), "before": str(row.category_id) if row.category_id else None})
            row.category_id = cid
    changed_copies: List[dict] = []
    missing_summaries: List[str] = []
    if summary_ids:
        uuids = [_as_uuid(x, "summary_ids") for x in dict.fromkeys(summary_ids)]
        rows = list((await db.execute(select(AssetSummary).where(AssetSummary.id.in_(uuids)))).scalars().all())
        found = {str(r.id) for r in rows}
        missing_summaries = [x for x in dict.fromkeys(summary_ids) if x not in found]
        for row in rows:
            if row.category_id == cid:
                continue
            changed_copies.append({"id": str(row.id), "before": str(row.category_id) if row.category_id else None})
            row.category_id = cid
    await db.flush()

    await _write_audit(
        db,
        action="asset.category.assign",
        operator=current_user,
        target_type="asset_category",
        target_id=str(cid) if cid else None,
        before={"assets": changed_assets, "summaries": changed_copies},
        after={"category_id": str(cid) if cid else None,
               "asset_ids": [c["id"] for c in changed_assets],
               "summary_ids": [c["id"] for c in changed_copies]},
    )
    missing = missing_assets + missing_summaries
    return {
        "ok": not missing,
        "asset_changed": len(changed_assets),
        "summary_changed": len(changed_copies),
        "category_id": str(cid) if cid else None,
        "not_found": missing,
        "notes": ([f"这些 id 在库里查不到，已跳过：{', '.join(missing[:5])}"] if missing else []),
    }


async def _batch_pending_prompt_units(
    db: AsyncSession, *, batch_ids: set, exclude_ids: List[Any]
) -> int:
    """同批次里**还没反推**的条数（不含本次已选中的），用于批次累计熔断（A1-4）。

    口径：pending/skipped/failed 都算"将来要花钱"，success/running 不算
    （running 已扣过费，重复计入会把余额预估抬高成假警报）。

    ⚠️ 批 G 加了 `media_kind == video`：图片的 `stage_prompt` 就是 **skipped**，
    按上面那句口径它会被算成"将来要花钱"——但图永远不会去反推（四个口都硬拒），
    算进来等于每存一张角色卡就把这批的钱估高一点，攒到 50 元闸门前是一个永远打不开的假警报。
    """
    ids = [b for b in batch_ids if b]
    if not ids:
        return 0
    rows = (
        await db.execute(
            select(func.count(AssetItem.id))
            .where(AssetItem.batch_id.in_(ids))
            .where(AssetItem.media_kind == MEDIA_VIDEO)
            .where(AssetItem.stage_prompt.in_([STAGE_PENDING, STAGE_FAILED, STAGE_SKIPPED]))
            .where(AssetItem.id.notin_(list(exclude_ids)))
        )
    ).scalar_one()
    return int(rows or 0)


async def _batch_video_count(db: AsyncSession, batch_id: Any) -> int:
    """批内**视频**条数（导入侧预算的计费口径，11-05 批 G）。

    只数 video 而不是 `item_count - 图片数`：`item_count` 是历史累计，可能与真实行数已经
    对不上（导入中途失败、手工补行），预算既然要拿它拦钱就按库里现查的行数算。
    """
    rows = (
        await db.execute(
            select(func.count(AssetItem.id))
            .where(AssetItem.batch_id == batch_id)
            .where(AssetItem.media_kind == MEDIA_VIDEO)
        )
    ).scalar_one()
    return int(rows or 0)


def _tier_or_400(max_duration: Optional[int]) -> int:
    # 显式判 None：`max_duration or DEFAULT` 会把 0 档悄悄变成 180 档（0 该报错，不是默认）
    tier = settings.ASSET_PROMPT_MAX_DURATION if max_duration is None else int(max_duration)
    if tier not in svc.PROMPT_MAX_DURATION_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"计时上限只支持 {'/'.join(map(str, svc.PROMPT_MAX_DURATION_TIERS))} 秒，收到 {tier}",
        )
    return tier


def _apply_import_budget(batch: AssetBatch, *, count: int, tier: int, need_upload: bool) -> dict:
    """导入侧的**真实**预算预警（A1-4：原来硬写 `budget_gate="ok"`，对账页永远绿灯）。

    导入本身不扣费，这里算的是「这批若全按 tier 档反推要多少钱」。不查余额
    （省一次外部调用、也让导入接口没有网络副作用），所以只可能出 ok / need_approval；
    blocked 由反推那一步按累计与余额判。
    """
    est = svc.estimate_batch_cost(count, max_duration=tier, need_upload=need_upload)
    gate = svc.budget_gate(
        est["total_cost"],
        None,
        batch_cap=settings.ASSET_BATCH_BUDGET_CAP,
        safety_ratio=settings.ASSET_BALANCE_SAFETY_RATIO,
    )
    batch.cost_estimate = est["total_cost"]
    batch.budget_gate = gate["level"]
    batch.budget_note = (gate.get("reason") or "")[:500] or None
    return {
        "tier": tier,
        "cost_estimate": batch.cost_estimate,
        "gate": gate["level"],
        "note": batch.budget_note,
        "unit_cost": est["unit_cost"],
        "cap": float(settings.ASSET_BATCH_BUDGET_CAP),
    }


def _serialize_batch(b: AssetBatch) -> dict:
    return {
        "id": str(b.id),
        "code": b.code,
        "name": b.name,
        "source_kind": b.source_kind,
        "item_count": b.item_count,
        "prompt_max_duration": b.prompt_max_duration,
        "cost_estimate": b.cost_estimate,
        "cost_actual": b.cost_actual,
        "budget_cap": b.budget_cap,
        "budget_gate": b.budget_gate,
        "budget_note": b.budget_note,
        "created_at": utc_iso(b.created_at),
    }


def _serialize_item(a: AssetItem, agg: Optional[dict] = None) -> dict:
    data = {
        "id": str(a.id),
        "code": a.code,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "source_kind": a.source_kind,
        # 批 G：前端按这一列分流（图片走"角色卡"卡片、视频走播放器），并据此隐藏
        # 「反推/出文案/拼接」入口。存量行由 ADD COLUMN 的 DEFAULT 'video' 兜住。
        "media_kind": getattr(a, "media_kind", None) or MEDIA_VIDEO,
        # 批 G：图片在"挑卡"列表里要直接说画幅（这张 9:16 出竖屏 / 这张横版出横屏）。
        # 判据留在后端一处：前端自己另拼一张宽高比表，日后口径一改就是两边各说一套
        # ——而这条口径的来源是实测（卡决定成片画幅），不是显示偏好。
        #
        # 11-09 起视频也给：这批横屏原片要收进库并在界面标「横屏」（用户拍板），而
        # orientation 只能从 resolution 推。此前恒回 null，界面那一列对视频永远显示
        # 「画幅未知」——不是量不到，是这一行只喂图片。resolution 已补齐（文件上传
        # 当场量、链接素材下载后回写），所以这里不加新口径，只把已有的一列对两类摊开；
        # 量不到时仍是 null，界面照样显示「画幅未知」。
        "aspect": _card_ratio_fields(a.resolution),
        "source_url": a.source_url,
        "platform": a.platform,
        "file_name": a.file_name,
        "file_key": a.file_key,
        "bucket": a.bucket,
        "file_size": a.file_size,
        # 批 J：下载动作自己的状态（NULL=没有要下的/还没排到），前端画成小图标
        "download_status": getattr(a, "download_status", None),
        "project_id": str(a.project_id) if a.project_id else None,
        "episode_id": str(a.episode_id) if a.episode_id else None,
        "prompt_task_id": str(a.prompt_task_id) if a.prompt_task_id else None,
        "title": a.title,
        "cover_image_key": a.cover_image_key,
        "duration": a.duration,
        "resolution": a.resolution,
        "prompt_max_duration": a.prompt_max_duration,
        # 11-04 拍板①：钩子原型（category_name 由列表侧一次性批量补，避免逐行查）
        "category_id": str(a.category_id) if a.category_id else None,
        "category_name": None,
        "stage_import": a.stage_import,
        "stage_prompt": a.stage_prompt,
        "stage_summary": a.stage_summary,
        "stage_produce": a.stage_produce,
        "stage_compose": a.stage_compose,
        "status": a.status,
        "has_approved_copy": bool(a.has_approved_copy),
        "cost_prompt": a.cost_prompt,
        "cost_produce": a.cost_produce,
        "cost_parse": a.cost_parse,
        "note": a.note,
        "created_by": str(a.created_by) if a.created_by else None,
        "created_at": utc_iso(a.created_at),
        "updated_at": utc_iso(a.updated_at),
    }
    if agg:
        data.update(agg)
    return data


def _can_resubmit(summary: AssetSummary, asset: AssetItem, current_user: User) -> bool:
    """这条文案现在能不能「改后重新提审」。

    状态门槛：只有**被驳回 / 需改写**的才谈得上重提（待审的本来就在队列里，
    过审的撤审走审核动作，不需要重提）。
    权限门槛：这条**素材的负责人（导入人，＝实际出文案的人）**或 admin。
    为什么不放开给所有有写权限的人：文案责任人是素材负责人，路人改了就等于
    审核人自己给自己擦屁股（和生产者不得自审是同一条线）。
    """
    if summary.audit_status not in (RV_REJECTED, RV_NEED_REWRITE):
        return False
    if current_user.role == UserRole.admin.value:
        return True
    return asset.created_by == current_user.id


def _serialize_summary(
    s: AssetSummary, asset: Optional[AssetItem] = None, *, can_resubmit: bool = False,
    category_name: Optional[str] = None, output_count: Optional[int] = None,
    reviewer_name: Optional[str] = None,
    production_count: Optional[int] = None,
) -> dict:
    data = {
        "id": str(s.id),
        "asset_id": str(s.asset_id),
        "seq": s.seq,
        "text": s.text,
        "style_tag": s.style_tag,
        "formula_tag": s.formula_tag,
        # 11-04 拍板①：文案的原型（出稿时继承素材，审核台可逐条改）
        "category_id": str(s.category_id) if s.category_id else None,
        "category_name": category_name,
        "word_count": s.word_count,
        "is_recommended": bool(s.is_recommended),
        "consistency_ok": s.consistency_ok,
        "consistency_note": s.consistency_note,
        "risk_hit": s.risk_hit,
        # P1（评审定稿⑯）：已开过几张生产单（挑选器防重复开单白烧号池）
        "production_count": production_count,
        "audit_status": s.audit_status,
        "reviewed_by": str(s.reviewed_by) if s.reviewed_by else None,
        # A′：过审人显示名（12px 灰字标注用）；None=调用方没聚合（详情口）或无主
        "reviewed_by_name": reviewer_name,
        "reviewed_at": utc_iso(s.reviewed_at) if s.reviewed_at else None,
        "reject_reason": s.reject_reason,
        # P1（评审定稿⑩）：作者重提说明（改后重提时写，审核卡展示）
        "resubmit_note": s.resubmit_note,
        "text_before_edit": s.text_before_edit,
        # 批 J：过审后备好的豆包提示词预览（NULL=还没备好/没排上；备好了审核台直接能看）
        "prompt_preview": s.prompt_preview,
        "prompt_preview_at": utc_iso(s.prompt_preview_at) if s.prompt_preview_at else None,
        "cost_preview": float(s.cost_preview or 0.0),
        # 11-06 双产出：出文案时同步生成的豆包网页版完整提示词（NULL=失败/未生成，可单独补）
        "doubao_prompt": s.doubao_prompt,
        # 批 N（11-09）：**预取**好、还没用掉的钩子编号（不是已投出去的号——那种号钉在
        # 生产单行上，看 production 的 hook_code）。开单时后端自动顶到缺号槽位并清空，
        # 所以这个键有值＝这条文案还欠着一张没开的单、手里有个能用的号。
        "hook_code": s.hook_code,
        "created_at": utc_iso(s.created_at),
        # 「改后重提」按钮要不要亮：前端不猜权限，按后端给的行级判定画
        "can_resubmit": bool(can_resubmit),
    }
    if asset is not None:
        data["asset_code"] = asset.code
        data["asset_title"] = asset.title
        data["asset_source_url"] = asset.source_url
        data["asset_platform"] = asset.platform
        data["asset_status"] = asset.status
    if output_count is not None:
        # 批 F 卡片右侧「已产 N 条」：只有 list_summaries 会查（整页一次聚合），
        # 别的调用方不传 = 这个键**不存在**，而不是 0——0 和"没查"是两回事，
        # 卡片拿 0 会画成「这条还没产出」，那是假信息。
        data["output_count"] = int(output_count)
    return data


def _serialize_production(
    p: AssetProduction,
    output_count: int = 0,
    owner_name: Optional[str] = None,
    category_name: Optional[str] = None,
) -> dict:
    return {
        "id": str(p.id),
        "asset_id": str(p.asset_id),
        "summary_id": str(p.summary_id),
        "batch_id": str(p.batch_id) if p.batch_id else None,
        # A′：投产人显示名（谁投账算谁的灰字标注）；None=调用方没聚合
        "owner_name": owner_name,
        "seq": p.seq,
        "hook_code": p.hook_code,
        # 批 M（11-10）：这条单所属文案的钩子原型名（列表口一次性批量补，口径与审核台一致）。
        # 投产弹窗的「可替换元素」按原型筛槽位，靠的就是这一列——单行口为 null。
        "category_name": category_name,
        "project_title": p.project_title,  # 废弃：11-02 版取消项目标题行，只读历史
        "prompt_text": p.prompt_text,
        "dispatch_note": p.dispatch_note,  # 只给人看，不进 payload
        "prompt_snapshot": p.prompt_snapshot,
        "video_titles": p.video_titles or [],
        "variant_basis": p.variant_basis,
        "drift": bool(p.drift),
        "drift_reason": p.drift_reason,
        "duration": p.duration,
        "channel": p.channel,
        # 后台任务板对账字段
        "board_total": p.board_total,
        "board_tag": p.board_tag,
        "board_date": utc_iso(p.board_date) if p.board_date else None,
        "board_name": p.board_name,
        "board_tid": p.board_tid,
        "board_rgid": p.board_rgid,
        # 批 L（投放进度可视化）：板子侧最后看到的行状态＋检查时间。null=没投过板
        # /回收动作没走到轮询（人工回写、刚建未投）。前端拿它显示「板子：出片中·上轮检查 …」。
        "board_last_status": p.board_last_status,
        "board_last_check_at": utc_iso(p.board_last_check_at) if p.board_last_check_at else None,
        "character_card_key": p.character_card_key,
        # 批 G：多卡数组（顺序＝板上 picDatas 顺序）。旧单这里是 []——
        # 读侧要区分"没挂卡"和"挂了一张旧 key"，看 character_card_key 那一列。
        "card_asset_ids": [str(x) for x in (p.card_asset_ids or []) if str(x or "").strip()],
        # 批 Q（11-10 需求⑤）：这张单投板时点名「出片后自动和哪条素材拼、拼在前还是拼在后」。
        # NULL＝没勾过，回收完就停（存量单全是这个态，行为与今天一致）。
        "concat_asset_id": str(p.concat_asset_id) if p.concat_asset_id else None,
        "concat_order": p.concat_order,
        # 最近一次自动拼的结果（拼成几支／失败几支／成因）。**只给界面看**，不参与任何判定——
        # 判据在 asset_outputs.composed_from_output_id 那侧，这里坏了也不影响业务。
        "concat_last_result": p.concat_last_result,
        "status": p.status,
        "error": p.error,
        # 投递台账（11-03 第 4 条）：一线要知道「这条投了几次、什么时候投的、什么时候出片」
        "attempts": int(p.attempts or 0),
        "started_at": utc_iso(p.started_at) if p.started_at else None,
        "completed_at": utc_iso(p.completed_at) if p.completed_at else None,
        "created_at": utc_iso(p.created_at),
        # 批 I（链路收敛）：行上「成片」列的数字——本单已收进几段片。口径与审核台
        # 卡片「已产 N 条」一致：排除 package/copy 附属文件，拼接产物没挂生产单天然不计。
        "output_count": int(output_count),
    }


# ──────────────────────────────────────────────
# 成本预览（前端确认弹窗先调这个，不落库）
# ──────────────────────────────────────────────


@router.get("/assets/cost/estimate")
async def estimate_cost(
    count: int = 1,
    max_duration: Optional[int] = None,
    need_upload: bool = False,
    need_parse: bool = False,
    current_user: User = Depends(get_current_user),
):
    """返回「预估费 + 当前余额 + 闸门结论」，供批量按钮的二次确认单展示。

    `need_parse`（D-5 拍板后新增）：把 doc/107 的 0.01 元/次**计进预估**。回源解析口
    在动手前先调这里拿预估；注意预估按「全部走付费渠道」算，实际命中 yuanbao/preview
    免费兜底时库里记的是 0，对账只会偏高不会偏低。
    """
    tier = _tier_or_400(max_duration)
    estimate = svc.estimate_batch_cost(
        count=count, max_duration=tier, need_upload=bool(need_upload),
        need_parse=bool(need_parse),
    )
    detail = await _query_zhiling_balance_detail()
    gate = svc.budget_gate(
        estimate["total_cost"],
        detail["balance"],
        batch_cap=settings.ASSET_BATCH_BUDGET_CAP,
        safety_ratio=settings.ASSET_BALANCE_SAFETY_RATIO,
    )
    # 确认单必须看得见"闸门到底生效了没"——余额查不到时不能只回一个 null 让人以为有钱
    return {
        **estimate,
        "balance": detail["balance"],
        "balance_unit": detail["unit"],
        "balance_note": detail["note"],
        "gate": gate,
    }


# ── P1（评审定稿⑫）：审计读口——此前 30+ 处 asset.* 审计只写不读，对账回查没有入口。
# 仅 admin；action/operator_id/created_at 都有索引，分页走 offset。明细（before/after
# 含完整文案与豁免理由）不下放非 admin。 ──
@router.get("/assets/audit-logs")
async def list_asset_audit_logs(
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
    action: Optional[str] = None,
    operator_id: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    conds = []
    if action:
        conds.append(AuditLog.action == action)
    if operator_id:
        conds.append(AuditLog.operator_id == _as_uuid(operator_id, "operator_id"))
    if target_id:
        conds.append(AuditLog.target_id == target_id)
    base = select(AuditLog).where(and_(*conds)) if conds else select(AuditLog)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    )
    rows = (
        await db.execute(
            base.order_by(AuditLog.created_at.desc())
            .offset(max(0, offset))
            .limit(min(max(1, limit), 200))
        )
    ).scalars().all()
    names = await _user_names(db, {r.operator_id for r in rows if r.operator_id})
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id),
                "action": r.action,
                "operator": names.get(str(r.operator_id), "未知"),
                "target_type": r.target_type,
                "target_id": r.target_id,
                "before": r.before,
                "after": r.after,
                "created_at": utc_iso(r.created_at),
            }
            for r in rows
        ],
    }


# ──────────────────────────────────────────────
# 导入：链接 / 文件
# ──────────────────────────────────────────────


# ── P1（评审定稿⑦）：取号进界面——后端代理 hook_id.py（服务器脚本），保留手工旁路。
# ASSET_HOOK_ID_CMD 未配置时 501（前端提示走手工粘贴）。命令须输出每行一个五位编号；
# 一钩一号「发了即烧」的铁律不变：代取的号也走既有硬查重＋白名单校验。 ──

# 11-09 批 O：把「取号」下沉成界面代取与新文案自动预取共用的底层，两个坑在这里一起解决：
#   ① `hook_id.py` 有 TAKE_MAX=50（一次最多发 50 个号），整批 85 条一口要过去 → 脚本 rc=2、
#      一个号都拿不到（现网第一次钉 88 个号就是在服务器上分 50＋38 两枪取的）。所以分块取。
#   ② 「发了即烧」是硬铁律：号一旦发出就记在共享台账上，后面一块失败也**不能把前面已经
#      拿到手的号扔掉重来**——扔掉等于白烧。所以本函数返回 (已拿到的号, 失败说明)，
#      而不是抛异常。调用方自己决定「够不够」。
_HOOK_TAKE_CHUNK = 50  # 与 hook_id.py 的 TAKE_MAX 对齐；放宽只会让脚本 rc=2，改这里没用
_HOOK_TAKE_TIMEOUT_SECONDS = 30


async def _take_hook_codes(count: int) -> Tuple[List[str], Optional[str]]:
    """跑 `ASSET_HOOK_ID_CMD` 取 `count` 个钩子编号，返回 (编号列表, 错误说明或 None)。

    **永不抛异常**（除非调用方自己没接住 `asyncio` 取消）：自动预取那条路上取不到号
    不该把导入整体拒掉，界面代取那条路则把 `error` 原文转成白话 502/501。
    """
    want = max(0, int(count))
    if want == 0:
        return [], None
    cmd = (getattr(settings, "ASSET_HOOK_ID_CMD", "") or "").strip()
    if not cmd:
        return [], "未配置自动取号命令（ASSET_HOOK_ID_CMD）"
    got: List[str] = []
    blocks = 0
    while len(got) < want:
        need = min(want - len(got), _HOOK_TAKE_CHUNK)
        blocks += 1
        try:
            proc = await asyncio.create_subprocess_shell(
                f"{cmd} {need}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=_HOOK_TAKE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            return got, (
                f"取号脚本第 {blocks} 枪超过 {_HOOK_TAKE_TIMEOUT_SECONDS} 秒没回话（要 {need} 个）"
            )
        except Exception as exc:  # noqa: BLE001 — 命令不存在/权限问题都要回人话，不是回栈
            return got, f"取号脚本没能跑起来：{type(exc).__name__}: {exc}"
        raw_err = (err or b"").decode("utf-8", "ignore").strip()
        # 脚本可能把说明打在 stdout（"已取 N 个"），只认五位 0-9A-Z，且同一次不许重号
        codes = [
            c for c in re.findall(r"[0-9A-Z]{5}", (out or b"").decode("utf-8", "ignore"))
            if svc.HOOK_CODE_RE.match(c)
        ]
        gained = 0
        for c in codes:
            if c not in got:
                got.append(c)
                gained += 1
        if gained == 0:
            rc = proc.returncode
            return got, (
                f"取号脚本第 {blocks} 枪没发新号（要 {need} 个、得 {len(codes)} 个，退出码 {rc}）："
                f"{raw_err[:200] or '脚本没给原因'}"
            )
    return got, None


async def _auto_park_hook_codes(
    db: AsyncSession,
    rows: List[AssetSummary],
    *,
    operator: Optional[User],
    source: str,
) -> Dict[str, Any]:
    """新建的文案**当场**挂上预取编号（11-09 批 O，用户口径「以后的新文案也自动预取吧」）。

    为什么要自动化：一钩一号，开单那一屏现取现贴每次都把人挡在服务器上跑一次
    `hook_id.py`；11-09 那批 85 条就是手工钉的（见 8-9）。号先挂在 `asset_summaries.hook_code`
    上等着，开单时后端自动顶到缺号的槽位、顶上即清空（`create_productions` 的 parked_code）。

    三条设计约束：
    - **fail-soft**：号是外部动作（脚本没配、台账锁不上、当天池子用光），任何一种都不能
      把「文案已经建好」这件事回滚掉——稿是人写的，比号金贵。所以本函数不抛 HTTPException，
      只回统计；哪条没挂上号，开单时照旧手工填或点「代取」。
    - **不重复发号**：只给 `hook_code` 还是空的行取号（重投同一批、或已经挂过号的行不再烧号）。
    - **一钩一号**：拿回来的号先对着库里两张表（`asset_productions.hook_code` /
      `asset_summaries.hook_code`）扫一遍，撞上的号不钉（号已烧掉，界面如实报出来）。

    留痕与手工钉号口共用同一套动作名 `asset.hook_code.park`，靠 `after.source` 区分
    「自动预取」和「人工钉」；只在真钉上号时写审计，取不到号不写（同 8-9 的判据：
    审计的价值在变化点，不在调用点）。**不 commit**，由调用方那一枪一起提交。
    """
    targets = [r for r in rows if not str(r.hook_code or "").strip()]
    result: Dict[str, Any] = {
        "attempted": len(targets),
        "parked": 0,
        "codes": [],
        "collisions": [],
        "reason": None,
    }
    if not targets:
        return result
    if not bool(getattr(settings, "ASSET_AUTO_PARK_HOOK_CODES", True)):
        # attempted 归零：旋钮关了不是「这批没配上号」，是「本批不打算配号」——
        # 前者要在导入回话里提醒人去补，后者提醒了只会让一线以为坏了。
        result["attempted"] = 0
        result["reason"] = "自动预取未开启（ASSET_AUTO_PARK_HOOK_CODES=false）"
        return result
    try:
        codes, err = await _take_hook_codes(len(targets))
        if not codes:
            result["reason"] = err or "取号脚本没返回编号"
            return result
        wanted = list(dict.fromkeys(codes))[: len(targets)]  # 脚本多给了也不多吃号：一条文案一个位
        used = {
            str(c)
            for (c,) in (
                await db.execute(
                    select(AssetProduction.hook_code).where(
                        AssetProduction.hook_code.in_(wanted)
                    )
                )
            ).all()
            if c
        }
        parked = {
            str(c)
            for (c,) in (
                await db.execute(
                    select(AssetSummary.hook_code).where(
                        AssetSummary.hook_code.in_(wanted)
                    )
                )
            ).all()
            if c
        }
        collisions = sorted(used | parked)
        free = [c for c in wanted if c not in used and c not in parked]
        changed: List[dict] = []
        for row, code in zip(targets, free):
            row.hook_code = code
            changed.append({"id": str(row.id), "before": None, "after": code})
        result["collisions"] = collisions
        if changed:
            await db.flush()
            result["parked"] = len(changed)
            result["codes"] = [c["after"] for c in changed]
            if len(changed) < len(targets):
                result["reason"] = err or (
                    f"可用号只有 {len(free)} 个（{len(collisions)} 个撞了库里已占的号）"
                    if collisions else f"取号脚本只给到 {len(free)} 个号"
                )
            await _write_audit(
                db,
                action="asset.hook_code.park",
                operator=operator,
                target_type="asset_hook_code",
                target_id="asset_hook_code",
                before={"summaries": [{"id": c["id"], "hook_code": None} for c in changed]},
                after={
                    "summaries": [{"id": c["id"], "hook_code": c["after"]} for c in changed],
                    "productions": [],
                    "source": f"auto_park:{source}",
                    "collisions": collisions,
                },
            )
        elif err:
            result["reason"] = err
        else:
            result["reason"] = "取到的号在库里全都占着了（异常，请手工取号）"
    except Exception as exc:  # noqa: BLE001 — 预取是便利，不是前置条件；任何意外都不拦导入
        logger.warning("新文案自动预取编号失败（source=%s）：%s", source, exc)
        result["reason"] = result["reason"] or f"自动预取异常：{type(exc).__name__}: {exc}"
    return result


def _park_payload(park: Dict[str, Any]) -> Dict[str, Any]:
    """自动预取统计的回包形状（三个建文案入口共用，别各写一套漏字段）。

    `collisions` 必须在：界面报「没全配上」时，一线要能看见是哪几个号撞了库，
    不然只会反复点同一个入口。
    """
    return {
        "attempted": park["attempted"],
        "parked": park["parked"],
        "codes": park["codes"],
        "collisions": park["collisions"],
        "reason": park["reason"],
    }


def _park_note(park: Dict[str, Any]) -> str:
    """把自动预取的统计说成一句人话，塞进导入响应的 message（空串＝没什么要说）。"""
    if not park.get("attempted"):
        return ""
    parked = int(park.get("parked") or 0)
    if parked:
        tail = ""
        if park.get("collisions"):
            tail = f"；{len(park['collisions'])} 个号库里已占用，已跳过"
        if parked < park["attempted"]:
            return (
                f"已自动预取 {parked} 个编号（本批 {park['attempted']} 条没全配上："
                f"{park.get('reason') or '取号脚本给的号不够'}）{tail}"
            )
        return f"已自动预取 {parked} 个编号，开单时自动带上{tail}"
    return (
        f"本批 {park['attempted']} 条没预取到编号（{park.get('reason') or '原因未知'}）——"
        "不影响导入，开单时手工填或点「代取」即可"
    )


@router.post("/assets/hook-codes/take")
async def take_hook_codes(
    current_user: Annotated[User, Depends(require_roles(*_REVIEW_ROLES))],
    count: int = Query(..., ge=1, le=500, description="要取几个号"),
):
    codes, err = await _take_hook_codes(count)
    if len(codes) < count:
        if (getattr(settings, "ASSET_HOOK_ID_CMD", "") or "").strip() == "" and not codes:
            raise HTTPException(
                status_code=501,
                detail="未配置自动取号命令（ASSET_HOOK_ID_CMD）——请按原流程在服务器跑 hook_id.py 取号后手工粘贴",
            )
        raise HTTPException(
            status_code=502,
            detail=f"取号脚本没返回足够的编号（要 {count}、得 {len(codes)}）：{err or '脚本没给原因'}",
        )
    return {"codes": codes[: int(count)]}


# ── P1 新增（用户需求 2026-11-08）：直接贴文案导入——已有外部生成好的钩子文案，
# 跳过"收集链接→反推"直接进审核队列。建一批无视频素材壳（stage_prompt=skipped），
# 直挂 AssetSummary 候选。一致性校验无脚本时优雅退化（ok=True 跳过比对），
# 风险词/形态校验照走。后面审核→投产→投板全链路不变。 ──
@router.post("/assets/summaries/import-copy")
async def import_copy_summaries(
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
    # 两个都用 Body：两个 body 参数时 FastAPI 自动 embed 成 {"batch_name":…, "texts":[…]}
    # （单个 body 参数时会期望 body 就是 list——前端发的是对象，必须双参数）
    batch_name: str = Body("", description="批次名（留空自动「贴文案导入 MMDD」）"),
    texts: List[str] = Body(..., description="钩子文案列表（一条一个元素；前端可按空行/换行拆）"),
):
    """直接贴文案导入：跳过"收集链接→反推"全流程，文案直挂候选进审核队列。

    适用场景：外部 LLM / 人工写好的一批钩子文案，不想再从链接反推一遍。
    - 建一个批次（AssetBatch）＋每条文案一个素材壳（AssetItem，stage_prompt=skipped，
      无视频无链接——纯文本容器）；
    - 每条文案建一条 AssetSummary（pending，推荐=第一条）；
    - 后续审核（形态/风险词/豁免）→ 投产（expand=True 展开提示词）→ 投板全链路照走。
    形态校验（≤80 字/首句≤25 字/不以逗号结尾）在这里**只提示不拦**——跟出文案口的
    做法一致（硬拦在审核口的 recheck 里做，这里拦了用户就得回文本编辑器改）。
    """
    if not texts or not [t for t in texts if (t or "").strip()]:
        raise HTTPException(status_code=400, detail="没有可导入的文案")

    from datetime import timedelta as _td

    batch = AssetBatch(
        name=batch_name.strip() or f"贴文案导入 {time.strftime('%m%d')}",
        source_kind=SOURCE_LINK,
        created_by=current_user.id,
    )
    db.add(batch)
    await db.flush()

    created = []
    skipped: List[dict] = []
    summary_rows: List[AssetSummary] = []
    seq_offset = 0
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        if not text:
            continue
        # 形态提示（只提示不拦——硬拦在审核口 recheck）
        shape = svc.check_copy_shape(text)
        if not shape["ok"]:
            skipped.append({"index": i + 1, "problems": shape["problems"], "text": text[:60]})
            continue

        seq_offset += 1
        asset = AssetItem(
            batch_id=batch.id,
            source_kind=SOURCE_LINK,
            source_url=None,
            media_kind=MEDIA_VIDEO,
            stage_import=STAGE_SKIPPED,
            stage_prompt=STAGE_SKIPPED,
            title=text[:40],
        )
        db.add(asset)
        await db.flush()

        summary = AssetSummary(
            asset_id=asset.id,
            seq=1,
            text=text,
            is_recommended=seq_offset == 1,
            audit_status=RV_PENDING,
        )
        db.add(summary)
        # 必须在这里 flush：`summary.id` 是 SQLAlchemy 的 Python 端默认值，
        # **到 INSERT 那一刻才生成**。不 flush 就取 `str(summary.id)`，最后一条
        # （循环里再没有别的 flush 触发点）会拿到 None，接口回体里就成了字符串
        # "None"——11-09 现网冒烟实测到的，前端今天没读这个字段所以没炸，
        # 但它是个谎报的主键，下一句「点这条进投产」就会拿它去查库查无此人。
        await db.flush()
        summary_rows.append(summary)
        created.append({
            "asset_id": str(asset.id),
            "summary_id": str(summary.id),
            "text": text[:60],
        })

    # 11-09 批 O：新建的文案当场自动挂预取编号（用户口径「以后的新文案也自动预取吧」）。
    # 先 commit 再取号：取号是本机子进程、最坏 30s×块数，而 PG 侧
    # idle_in_transaction_session_timeout=60s 会把"事务开着等外部调用"的连接直接掐掉
    # （11-03 预览栈真链路就是这么整口 500 丢候选的）。文案先落库，号随后一枪补上——
    # 预取是便利不是前置条件，取不到号也不该把这批稿回滚掉。
    await db.commit()
    park = await _auto_park_hook_codes(db, summary_rows, operator=current_user, source="import_copy")
    await db.commit()
    note = _park_note(park)
    return {
        "batch_id": str(batch.id),
        "batch_code": batch.code,
        "created": len(created),
        "skipped": skipped,
        "items": created,
        "hook_codes": _park_payload(park),
        "message": f"已导入 {len(created)} 条文案进审核队列（{batch.code}）"
        + (f"；{len(skipped)} 条形态不合格被跳过" if skipped else "")
        + (f"；{note}" if note else ""),
    }


def _paired_reason_digest(rows: List[dict], key: str = "error", limit: int = 2) -> str:
    """把逐条明细里的原因去重拼一句，塞进整体失败时的 `detail`。

    为什么不能只写"明细见 errors"：全拒的那一枪调用方（一线用的是界面弹窗）只会读
    `detail` 这一句，errors 里的逐条原因埋在响应体第二层没人翻。而"配对失败"最需要的
    恰恰是**为什么**（重名？没传？库里有同名？）——说不清原因，人就只会反复重投同一份清单。
    """
    seen: List[str] = []
    for r in rows:
        msg = str(r.get(key) or "").strip()
        if msg and msg not in seen:
            seen.append(msg)
        if len(seen) >= limit:
            break
    return "；".join(seen)


# ── 11-09 成稿配对导入（外部已经产好稿的一批原片）────────────────────────
# 为什么不是把两条老路拼起来用：拼不了。
#   · `/assets/upload/batch` 建出来的素材停在「待反推」，而出文案口硬要求先有反推稿
#     （`generate_summaries` 的 `require_prompt_success=True` ＋ "反推脚本尚未就绪"），
#     人工稿在手里也喂不进去；
#   · `/assets/summaries/import-copy` 建的是**无视频的文本壳**，原片进不去。
# 走老路等于把 86 条真素材重新反推一遍：0.00054×档位 ≈ 每条 0.03~0.10 元、
# 86 次智令调用，买的却是一份库里本来就能放下的稿。
# 落点全部是既有表、**不新增一列**：批次 → 素材（含 resolution，横屏在这一步才量得出来）
# → `wechat_dl_prompt_tasks` 一行 success（content＝人工稿）→ 候选文案（pending，进审核队列）。
# 反推任务这一行是唯一的新写法：status 直接给 success、不带 provider_task_id。安全性靠两件事
# 兜住——① `refresh_prompt_task` 对非 processing 任务是**只读原样返回**（不会去轮询、更不会扣费）；
# ② `_prompt_script_of` 命中 success 就把 stage_prompt 写成 success 并回填标题（已有标题不覆盖）。
# 费用三列一律 0 并写进 note：稿是人工产的，对账页不能出现一笔从没发生的钱。
@router.post("/assets/import/paired", status_code=201)
async def import_paired_batch(
    files: List[UploadFile] = File(
        ..., description="原片视频文件；multipart 里的文件名＝清单项 `video` 的 basename"
    ),
    manifest: str = Form(
        ...,
        description=(
            "配对清单 JSON：{batch_name?, items:[{video, title?, category?, script_text?, "
            "hook_copy?, doubao_prompt?, note?, skip?, skip_reason?}]}"
        ),
    ),
    max_duration: Optional[int] = Form(None, description="登记用的反推计时上限档位（秒）；本口不产生反推费"),
    project_id: Optional[str] = Form(None, description="归属项目（可选）"),
    force_duplicates: bool = Form(False, description="库里已有同名素材时仍要再入一份（默认跳过不重复占位）"),
    current_user: User = Depends(require_roles(*_PROD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """成稿配对导入：原片 + 人工反推稿 + 一句话钩子文案 + 豆包提示词，一次进四个槽位，0 模型费。

    一条清单项 = 一条素材。缺哪个槽位就留哪个口子，**不硬编**：
    - 有 `hook_copy` → 建 pending 候选，直接进审核队列（形态不合格**照样入库**、
      只在响应里点名——文案是人写的，丢掉等于把稿扔掉；真正的硬拦在审核口 recheck）；
    - 有 `script_text` → 登记一条 success 的反推任务行（不带 provider_task_id，见上面的
      安全论证），出文案口能直接吃它，不再花一次反推钱；
    - 两样各缺一半的，**两条欠账轴分开报**（`need_copy` / `need_prompt`）：有稿没文案＝
      点一下出文案就补上；没稿（哪怕它有文案）＝要补只能跑反推，那步花钱，不补则过审时
      没有稿做一致性对照。宁可报多一条，也不能让「有文案没稿」这种在响应里两头都不提。
    批次按 `category`（钩子原型**名称**）分组，一个原型一批次，方便按类别验收与回滚；
    字典里没有这个名字的，落未分类并点名——写共享字典是管理员的口子（PUT /assets/categories），
    导入不替人建字典行。
    """
    try:
        spec = json.loads(manifest or "")
    except Exception as exc:  # noqa: BLE001 — 脏 JSON 要回人话，不是回一句 JSON decode error
        raise HTTPException(status_code=400, detail=f"配对清单不是合法 JSON：{exc}")
    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="配对清单要是一个对象：{\"items\": [...]}")
    raw_items = spec.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=400, detail="配对清单里没有 items")

    items: List[dict] = []
    dropped: List[dict] = []
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            dropped.append({"index": i + 1, "reason": "清单里这一项不是对象"})
            continue
        video = str(raw.get("video") or "").strip()
        if not video:
            dropped.append({"index": i + 1, "reason": "缺 video 字段（原片文件名）"})
            continue
        if raw.get("skip"):
            dropped.append({
                "index": i + 1, "video": video,
                "reason": str(raw.get("skip_reason") or "清单标了 skip，默认不收"),
            })
            continue
        items.append({
            "index": i + 1,
            "video": video,
            "name": os.path.basename(video.replace("\\", "/")),
            "title": str(raw.get("title") or "").strip(),
            "category": str(raw.get("category") or "").strip(),
            "script_text": str(raw.get("script_text") or "").strip(),
            "hook_copy": str(raw.get("hook_copy") or "").strip(),
            "doubao_prompt": str(raw.get("doubao_prompt") or "").strip(),
            "note": str(raw.get("note") or "").strip(),
            "file_pos": None,
        })

    if not items:
        raise HTTPException(
            status_code=400,
            detail=f"清单里没有可导入的条目（{len(dropped)} 项被丢弃：{_paired_reason_digest(dropped, 'reason')}）",
        )
    if len(items) > int(settings.ASSET_IMPORT_BATCH_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"单请求最多 {settings.ASSET_IMPORT_BATCH_MAX} 条；请按钩子原型分几次投",
        )

    # ── 配对：清单项 ↔ multipart 文件，**按文件名一一对应，两边都不许重名** ──
    # 为什么宁可在门口拦也不猜：`validate_file_name` 只留 basename，两个目录里同名的
    # 两支 mp4 落到素材表上就是同一个名字（本批实测有一对 `260825-小男孩遇贵人.mp4`，
    # 11.07s 与 10.87s 是两个不同版本）。按大小或顺序去猜，猜错的那条会把 A 的画面配上
    # B 的稿——这条链路上没有任何后续环节会发现，因为稿和画面对不上是"内容问题"不是"数据问题"。
    # 所以调用方（前端和脚本）都按同一条规矩准备：**只投清单里非 skip 的那些文件**。
    by_name: Dict[str, List[int]] = {}
    for pos, f in enumerate(files):
        base = os.path.basename((f.filename or "").replace("\\", "/")).strip()
        if base:
            by_name.setdefault(base, []).append(pos)
    errors: List[dict] = []
    item_names = [it["name"] for it in items]
    repeated_items = {n for n in item_names if item_names.count(n) > 1}
    keep: List[dict] = []
    for it in items:
        if it["name"] in repeated_items:
            errors.append({
                "index": it["index"], "video": it["video"],
                "error": f"清单里有 {item_names.count(it['name'])} 条同名原片（{it['name']}），"
                         "按文件名配不出一一对应；同名只留一条，其余标 skip 或改名后重投",
            })
            continue
        cands = by_name.get(it["name"], [])
        if not cands:
            errors.append({"index": it["index"], "video": it["video"], "error": "请求里没收到这个文件"})
            continue
        if len(cands) > 1:
            errors.append({
                "index": it["index"], "video": it["video"],
                "error": f"请求里有 {len(cands)} 个同名文件但清单只有 1 条，无法判断配哪一个；"
                         "只投清单引用的那些文件（重名的另一份别一起传）",
            })
            continue
        it["file_pos"] = cands[0]
        keep.append(it)
    items = keep
    matched = {it["file_pos"] for it in items}
    leftover_files = [
        os.path.basename((files[p].filename or "").replace("\\", "/"))
        for p in range(len(files)) if p not in matched
    ]
    if not items:
        raise HTTPException(
            status_code=400,
            detail=(
                f"一条都没配上（{len(errors)} 条）——{_paired_reason_digest(errors)}"
                + (f"；另有 {len(leftover_files)} 个文件清单没引用" if leftover_files else "")
            ),
        )

    # ── 重复预检：库里已有同名素材就不静默再入一份（口径与链接导入一致：提示＋可放行）──
    if not force_duplicates:
        names = sorted({it["name"] for it in items})
        rows = (
            await db.execute(
                select(
                    AssetItem.file_name, AssetItem.code, AssetItem.created_at
                ).where(
                    AssetItem.source_kind == SOURCE_FILE,
                    AssetItem.file_name.in_(names),
                )
            )
        ).all()
        # 同名只出现过一次才点名到具体是哪条；出现过两次就说"库里已有 N 条同名"，
        # 报第一个 code 会让人觉得那一条就是它、而实际库里还有另一条。
        hits_by_name: Dict[str, List[tuple]] = {}
        for fn, code, created_at in rows:
            hits_by_name.setdefault(fn, []).append((code, utc_iso(created_at) if created_at else None))
        keep = []
        dup_start = len(dropped)  # 只把"重名"这一段喂给 detail，别和清单里 skip 的话术混在一句里
        for it in items:
            hits = hits_by_name.get(it["name"])
            if not hits:
                keep.append(it)
                continue
            who = (
                f"{hits[0][0]}（{hits[0][1] or '日期未知'} 导入）"
                if len(hits) == 1 else f"{len(hits)} 条同名"
            )
            dropped.append({
                "index": it["index"], "video": it["video"],
                "reason": f"库里已有同名素材 {who}，默认不收；确要再入一份带 force_duplicates=true",
            })
        items = keep
        if not items:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{len(dropped) - dup_start} 条全部因库里同名没入库——"
                    f"{_paired_reason_digest(dropped[dup_start:], 'reason')}"
                ),
            )

    tier = _tier_or_400(max_duration)
    project_uuid = _as_uuid(project_id, "project_id") if project_id else None

    # ── 字典按**名字**解析（清单吃的是人话类别，不是 UUID）──
    cat_names = sorted({it["category"] for it in items if it["category"]})
    cat_map: Dict[str, Optional[uuid.UUID]] = {}
    unknown_cats: List[str] = []
    if cat_names:
        rows = (
            await db.execute(
                select(AssetCategory.name, AssetCategory.id, AssetCategory.active).where(
                    AssetCategory.name.in_(cat_names)
                )
            )
        ).all()
        found = {}
        for name, cid, active in rows:
            found[name] = (cid, active)
        for name in cat_names:
            cid, active = found.get(name, (None, None))
            if cid is None:
                unknown_cats.append(name)
                cat_map[name] = None
            elif not active:
                # 下线行不新建引用（与 `_resolve_category_or_400` 同一口径），但也不拦导入
                unknown_cats.append(f"{name}（已下线）")
                cat_map[name] = None
            else:
                cat_map[name] = cid

    # ── 一个原型一个批次，先建行（`_ingest_one_video_file` 要用 batch.code 拼 file_key）──
    prefix = str(spec.get("batch_name") or "").strip()
    groups: Dict[Optional[str], List[dict]] = {}
    for it in items:
        groups.setdefault(it["category"] or None, []).append(it)
    batches: Dict[Optional[str], AssetBatch] = {}
    for key, group in groups.items():
        batch = AssetBatch(
            code=gen_batch_code(),
            name=(f"{prefix} " if prefix else "") + (f"成稿导入·{key} {len(group)} 条" if key
                                                    else f"成稿导入 {len(group)} 条"),
            source_kind=SOURCE_FILE,
            prompt_max_duration=tier,
            # 成稿导入**真不花钱**：稿是人工产的，这里不套 `_apply_import_budget`
            # （那算的是"这批若全去反推要多少钱"，而这批永远不会去反推，写上去就是一笔
            #  对账页里凭空多出来的预估）。0 元是事实，不是乐观。
            cost_estimate=0.0,
            cost_actual=0.0,
            budget_cap=settings.ASSET_BATCH_BUDGET_CAP,
            budget_gate=svc.budget_gate(
                0.0, None,
                batch_cap=settings.ASSET_BATCH_BUDGET_CAP,
                safety_ratio=settings.ASSET_BALANCE_SAFETY_RATIO,
            )["level"],
            budget_note="成稿配对导入：原片与稿都是外部已产好的，本口 0 模型费",
            created_by=current_user.id,
        )
        db.add(batch)
        batches[key] = batch
    await db.flush()

    # ── I/O 段并发（落盘/探时长量画幅/传桶），建行留给下面串行（AsyncSession 非并发安全，A4-5）──
    max_bytes = upload_max_bytes()
    sem = asyncio.Semaphore(_UPLOAD_CONCURRENCY)
    tmp_dir = os.path.join(tempfile.gettempdir(), f"asset_paired_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        results = await asyncio.gather(*[
            _ingest_one_video_file(
                files[it["file_pos"]],
                tmp_dir=tmp_dir,
                batch_code=batches[it["category"] or None].code,
                max_bytes=max_bytes,
                sem=sem,
            )
            for it in items
        ])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    created: List[dict] = []
    need_copy: List[str] = []
    need_prompt: List[str] = []
    shape_warnings: List[dict] = []
    park_rows: List[AssetSummary] = []  # 11-09 批 O：本轮新建的文案，出料后统一自动预取号
    audit_rows = 0
    for it, res in zip(items, results):
        if not res["ok"]:
            errors.append({"index": it["index"], "video": it["video"], "error": res["error"]})
            continue
        batch = batches[it["category"] or None]
        asset = AssetItem(
            code=gen_asset_code(),
            batch_id=batch.id,
            source_kind=SOURCE_FILE,
            media_kind=MEDIA_VIDEO,
            file_name=res["file_name"][:255],
            file_key=res["file_key"],
            bucket=settings.MINIO_BUCKET_RAW,
            file_size=res["size"],
            duration=res.get("duration"),
            # 画幅在这里量，是「界面上标横屏」的唯一数据源（链接素材是下载后回写，两条路都要有）
            resolution=(
                f"{res['width']}x{res['height']}"
                if res.get("width") and res.get("height") else None
            ),
            title=(it["title"] or os.path.splitext(it["name"])[0])[:500],
            project_id=project_uuid,
            category_id=cat_map.get(it["category"]) if it["category"] else None,
            stage_import=STAGE_SUCCESS,
            prompt_max_duration=tier if it["script_text"] else None,
            created_by=current_user.id,
            note=(
                "11-09 成稿配对导入：反推稿与文案为外部人工产出，未走模型（cost_prompt/cost_parse=0）"
                + (f"｜{it['note']}" if it["note"] else "")
            )[:1000],
        )
        if it["script_text"]:
            task = WechatDlPromptTask(
                created_by=current_user.id,
                source_type=PST_UPLOAD,
                # 这一列 NOT NULL，而这条任务从没属于任何链接/直链——用一个**明确不是 URL** 的
                # 哨兵值，而不是留空串：日后有人按 source_url 去回源，空串会让他以为数据坏了，
                # `paired://` 一眼就知道这是导入进来的稿，没有源可回。
                source_url=f"paired://{res['file_name']}"[:1000],
                file_name=res["file_name"][:255],
                status=PT_SUCCESS,
                content=it["script_text"],
                max_duration=tier,
            )
            db.add(task)
            await db.flush()
            asset.prompt_task_id = task.id
            svc.apply_stage(asset, "prompt", STAGE_SUCCESS)
        else:
            svc.apply_stage(asset, "prompt", STAGE_PENDING)
        db.add(asset)
        await db.flush()

        summary_id = None
        if it["hook_copy"]:
            shape = svc.check_copy_shape(it["hook_copy"])
            summary = AssetSummary(
                asset_id=asset.id,
                seq=1,
                text=it["hook_copy"],
                word_count=shape["chars"],
                category_id=cat_map.get(it["category"]) if it["category"] else None,
                # 外部稿没有"三候选选一"这回事：这条就是唯一候选，默认推荐
                is_recommended=True,
                audit_status=RV_PENDING,
                doubao_prompt=it["doubao_prompt"] or None,
                source_prompt_task_id=asset.prompt_task_id,
            )
            db.add(summary)
            park_rows.append(summary)
            svc.apply_stage(asset, "summary", STAGE_SUCCESS)
            await db.flush()
            summary_id = str(summary.id)
            if not shape["ok"]:
                shape_warnings.append({
                    "code": asset.code, "video": it["video"], "problems": shape["problems"],
                    "text": it["hook_copy"][:60],
                })
        # 两条**独立**的欠账轴各记各的（11-09 实测口径：这批 86 条里四种组合都有）：
        # - 没稿 → 欠一次反推（那步花钱），不管它有没有文案；
        # - 有稿没文案 → 欠一次出文案（免费吃稿）。
        # 以前只在"没文案"那一支里二选一，于是「人工文案＋没稿」这条两头都不报，
        # 一线看不见它还欠反推稿——而一致性闸门没有对照物，过审时才暴露。
        if not it["script_text"]:
            need_prompt.append(asset.code)
        elif not it["hook_copy"]:
            need_copy.append(asset.code)

        await _write_audit(
            db,
            action="asset.import_paired",
            operator=current_user,
            target_type="asset_item",
            target_id=str(asset.id),
            before=None,
            after={
                "code": asset.code,
                "batch_code": batch.code,
                "file_name": asset.file_name,
                "category": it["category"] or None,
                "has_script": bool(it["script_text"]),
                "has_copy": bool(it["hook_copy"]),
                "has_doubao_prompt": bool(it["doubao_prompt"]),
                "summary_id": summary_id,
                "cost": 0.0,
                "from_manifest_index": it["index"],
            },
        )
        audit_rows += 1
        created.append({
            "asset_id": str(asset.id),
            "code": asset.code,
            "batch_code": batch.code,
            "title": asset.title,
            "resolution": asset.resolution,
            "duration": asset.duration,
            "status": asset.status,
            "has_copy": bool(it["hook_copy"]),
            "has_script": bool(it["script_text"]),
        })

    # 空批次不留行：这里的批次全是本请求新建的，一条都没进来就该撤掉，
    # 否则对账页会出现一个「0 条素材」的批次，一线以为文件丢了
    # （同 `_upload_into_batch` 里 `batch_is_new` 那条判据）。
    kept = [b for b in batches.values() if any(c["batch_code"] == b.code for c in created)]
    if not created:
        # 桶里可能已经落了对象（落盘传桶成功、建行前失败），那是既有上传口同样的既有行为：
        # 不留数据库行、孤儿对象由桶生命周期规则兜；宁可回 400 让人重投，也不留半批数据。
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(errors)} 条全部没入库，批次未创建——{_paired_reason_digest(errors)}"
                "（修正后可直接重投同一份清单）"
            ),
        )
    for b in batches.values():
        if b not in kept:
            await db.delete(b)
    for b in kept:
        b.item_count = len([c for c in created if c["batch_code"] == b.code])
    # 序列化**必须在 commit 之前**：commit 会 expire 所有属性，之后读 `b.name` 触发懒加载，
    # 而异步会话在非 greenlet 上下文里懒加载直接抛 MissingGreenlet（既有序列化都遵循这个次序）
    batch_payload = [_serialize_batch(b) for b in kept]

    await db.commit()

    # 11-09 批 O：真入库了才自动预取编号——放在 `if not created` 那道回滚闸门与首次 commit
    # 之后：① 全批没入库被回滚时一个号都不该发（号是烧掉的东西）；② 取号是本机子进程、
    # 最坏 30s×块数，事务开着等它会被 PG 的 idle_in_transaction 60s 掐连接（11-03 预览栈
    # 真链路实测踩过：模型回来时连接已闭，整口 500、候选一条没落库）。
    # 一次导入只跑一枪脚本，不在逐条循环里取：86 条各取一次 = 86 次台账锁 + 86 倍失败面。
    park = await _auto_park_hook_codes(db, park_rows, operator=current_user, source="import_paired")
    await db.commit()

    # 与文件上传口同一套收尾：入库即自动排抽帧（审核台卡片靠它，0 元、纯本机 ffmpeg）。
    # `_enqueue_frames` 自己 fail-soft，排不上只回一条 note，不会把已经落库的导入带崩。
    frames = await _enqueue_frames(
        db,
        asset_ids=[c["asset_id"] for c in created],
        output_ids=[],
        operator=current_user,
        why=f"成稿配对导入 {len(created)} 条",
    )

    parts = [f"已配对入库 {len(created)} 条（{len(batch_payload)} 个批次），本口 0 模型费"]
    if need_copy:
        parts.append(f"{len(need_copy)} 条有稿没文案，可直接点「出文案」（这一步不吃反推钱）")
    if need_prompt:
        parts.append(f"{len(need_prompt)} 条没有反推稿（要补只能跑一次反推，那步花钱；不补则过审时没有稿做对照）")
    if shape_warnings:
        parts.append(f"{len(shape_warnings)} 条文案形态不合格已照样入库，过审前需按审核口提示改")
    if unknown_cats:
        parts.append(f"字典里没有这些原型、已按未分类入库：{'、'.join(unknown_cats)}（要归类请管理员先在字典加行）")
    if dropped:
        parts.append(f"{len(dropped)} 条未入库（清单标注/库里重名），明细在 skipped")
    if errors:
        parts.append(f"{len(errors)} 条失败，明细在 errors")
    if leftover_files:
        parts.append(f"{len(leftover_files)} 个文件清单里没引用，未入库")
    if not frames.get("queued"):
        parts.append(
            f"抽帧没排上（{frames.get('note') or '原因未知'}）：不影响导入，"
            "审核台卡片暂时没图，可就地补抽"
        )
    park_note = _park_note(park)
    if park_note:
        parts.append(park_note)

    return {
        "created": len(created),
        "batches": batch_payload,
        "items": created,
        "need_copy": need_copy,
        "need_prompt": need_prompt,
        "shape_warnings": shape_warnings,
        "unknown_categories": unknown_cats,
        "skipped": dropped,
        "errors": errors,
        "leftover_files": leftover_files,
        "audit_rows": audit_rows,
        "frames": frames,
        "hook_codes": _park_payload(park),
        "message": "；".join(parts),
    }


@router.post("/assets/import/preflight")
async def import_preflight(
    data: ImportBatchRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """导入前重复预检（P1·评审定稿⑪，**0 元、不建任何行**）：粘贴完就地知道哪些已
    入库（几月几日 谁 导入 AS-XXXX），不用先发一次导入再逐条点「仍要入库」。
    归一化口径与正式导入同一套（svc.normalize_source_url 的 source_url_norm）。"""
    urls, _skipped = svc.normalize_source_list(data.links)
    if not urls:
        return {"items": []}
    norms = {}
    for u in urls:
        n, _platform = svc.normalize_source_url(u)
        if n:
            norms[n] = u
    if not norms:
        return {"items": []}
    rows = (
        await db.execute(
            select(
                AssetItem.source_url_norm,
                AssetItem.code,
                AssetItem.created_at,
                AssetItem.title,
            ).where(AssetItem.source_url_norm.in_(list(norms)))
        )
    ).all()
    out = [
        {
            "source_url_norm": r[0],
            "url": norms.get(r[0]),
            "code": r[1],
            "title": r[3],
            "imported_at": utc_iso(r[2]) if r[2] else None,
        }
        for r in rows
    ]
    return {"items": out}


@router.post("/assets/import/batch", status_code=201)
async def import_links_batch(
    data: ImportBatchRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """链接批量导入 + 跨批次去重提示 + 超量自动拆批。

    去重口径（`asset_service.normalize_source_url`）：
    - 归一化键**只用来命中提示**，真正提交给智令的永远是原始 source_url；
    - 命中已导入的素材默认**跳过不建**，并回「几月几日 谁 导入（AS-XXXX）」（A4-2）——
      只回 code 和日期等于让一线自己再去查库判断该不该放行；
    - 放行支持两种粒度：`force_duplicates`（整批）与 `force_urls`（逐条，只放行点名的几条）；
    - 库里 source_url_norm 只有索引、没有唯一约束（硬唯一会静默丢素材，审核席位明确反对）。

    超单批上限（A4-1，方案 §四）：服务端按 limit 切片、**每片各建一个批次**并回
    `split_into`，不是 400 打回。让一线自己数到 100 分三次提交＝把系统约束变成人工劳动，
    还会拆出三个来路不明的批次名；这里批次名自动带「第 i/k 批」，成本与闸门逐批各算各的。
    """
    limit = int(settings.ASSET_IMPORT_BATCH_MAX)
    urls, skipped = svc.normalize_source_list(data.links)
    if not urls:
        raise HTTPException(status_code=400, detail="没有可用链接")

    project_uuid = _as_uuid(data.project_id, "project_id") if data.project_id else None
    # 11-04 拍板①：导入抽屉的「整批默认原型」在这里落到每一条素材（可留空＝未分类）
    category_uuid = await _resolve_category_or_400(db, data.category_id)
    tier = _tier_or_400(data.prompt_max_duration)

    # 归一化（无法解析的先记 skipped，不入库——入库了也反推不了）
    # R-2（11-04 第二轮审核）：`normalize_source_list` 只按**原始字符串**去同批重复，
    # 而抖音/小红书的同一个视频常有多种写法（`v.douyin.com/x` 与
    # `www.iesdouyin.com/share/video/x`），归一化后才撞成一条 → 原来两条都会建素材行，
    # 反推按行计费＝同一条片子付两遍钱。这里补一道**按归一化键**的同批去重。
    entries: List[tuple] = []
    seen_norm: Dict[str, str] = {}
    for raw in urls:
        norm, platform = svc.normalize_source_url(raw)
        if not norm:
            skipped.append(f"无法识别的链接已跳过: {raw[:40]}")
            continue
        if norm in seen_norm:
            skipped.append(
                f"同一条视频的另一种写法已跳过（与 {seen_norm[norm][:40]} 是同一素材）"
            )
            continue
        seen_norm[norm] = raw
        entries.append((raw, norm, platform))
    if not entries:
        raise HTTPException(status_code=400, detail="链接均无法识别，请检查是否为有效分享链接")

    # A4-2：逐条放行的集合也按归一化口径建，前端拿 dup["source_url"] 或原链接回填都认
    force_norm = set()
    for raw in (data.force_urls or []):
        candidate = (raw or "").strip()
        if not candidate:
            continue
        norm, _ = svc.normalize_source_url(candidate)
        force_norm.add(norm or candidate)

    norms = [n for _, n, _ in entries]
    existing = (
        await db.execute(
            select(
                AssetItem.source_url_norm, AssetItem.code, AssetItem.title,
                AssetItem.created_at, AssetItem.created_by,
                User.display_name, User.username,
            )
            .outerjoin(User, User.id == AssetItem.created_by)
            .where(AssetItem.source_url_norm.in_(norms))
            .where(AssetItem.status != AS_ARCHIVED)
            .order_by(AssetItem.created_at.asc())
        )
    ).all()
    hit_map: Dict[str, dict] = {}
    for norm, code, title, created_at, created_by, display_name, username in existing:
        who = (display_name or username) or "未知（账号已删）"
        # 板面/一线都按 CST 看日期，库里存 UTC：直接印 created_at 会差一天
        local = (created_at + timedelta(hours=8)) if created_at else None
        hit_map.setdefault(norm, {
            "code": code,
            "title": title,
            "created_at": utc_iso(created_at),
            "imported_by": who,
            "imported_by_user_id": str(created_by) if created_by else None,
            "hint": f"{local.strftime('%m月%d日') if local else '未知日期'} {who} 导入（{code}）",
        })

    shards = svc.chunk_by_limit(entries, limit)
    base_name = (data.name or "").strip() or f"链接导入 {tier}s"
    batches: List[AssetBatch] = []
    budgets: List[dict] = []
    created: List[AssetItem] = []
    # 每个拆批各自圈住自己那几条素材 id：自动下载按批次排任务，台账上批次对得上号
    batch_asset_ids: List[List[str]] = []
    duplicates: List[dict] = []

    for idx, shard in enumerate(shards, start=1):
        batch = AssetBatch(
            code=gen_batch_code(),
            name=base_name if len(shards) == 1 else f"{base_name}（第{idx}/{len(shards)}批）",
            source_kind=SOURCE_LINK,
            prompt_max_duration=tier,
            budget_cap=settings.ASSET_BATCH_BUDGET_CAP,
            created_by=current_user.id,
        )
        db.add(batch)
        await db.flush()

        shard_created: List[AssetItem] = []
        shard_dupes: List[dict] = []
        for raw, norm, platform in shard:
            hit = hit_map.get(norm)
            if hit and not (data.force_duplicates or norm in force_norm or raw in force_norm):
                shard_dupes.append({
                    "source_url": raw[:300],
                    "source_url_norm": norm[:300],
                    "existing": hit,
                    "hint": hit["hint"],
                })
                continue
            asset = AssetItem(
                code=gen_asset_code(),
                batch_id=batch.id,
                source_kind=SOURCE_LINK,
                source_url=raw[:2000],
                source_url_norm=norm[:2000],
                platform=platform,
                project_id=project_uuid,
                category_id=category_uuid,
                prompt_max_duration=None,
                # 链接形态「导入」只是把地址登记进库，真正花钱的是下一步反推
                stage_import=STAGE_SUCCESS,
                status=svc.derive_status({"import": STAGE_SUCCESS}),
                created_by=current_user.id,
            )
            db.add(asset)
            shard_created.append(asset)

        batch.item_count = len(shard_created)
        # A1-4：导入侧接真实闸门（链接形态不需要中转上传，故 need_upload=False）
        # 拆批后**每批各算一份成本与闸门**：合在一起算等于把单批预算墙变成摆设
        budget = _apply_import_budget(batch, count=len(shard_created), tier=tier, need_upload=False)
        await db.flush()
        await _write_audit(
            db,
            action="asset.import_links",
            operator=current_user,
            target_type="asset_batch",
            target_id=batch.id,
            after={
                "batch_code": batch.code,
                "submitted": len(shard),
                "created": len(shard_created),
                "duplicates": len(shard_dupes),
                "tier": tier,
                "cost_estimate": batch.cost_estimate,
                "budget_gate": batch.budget_gate,
                # 拆批是服务端行为，审计要能还原「这一次提交被拆成了几批」
                "shard": idx,
                "shards_total": len(shards),
                "force_duplicates": data.force_duplicates,
                "force_urls": len(force_norm) or None,
                "auto_download": data.auto_download,
            },
        )
        batches.append(batch)
        budgets.append({**budget, "batch_id": str(batch.id), "batch_code": batch.code})
        created.extend(shard_created)
        batch_asset_ids.append([str(a.id) for a in shard_created])
        duplicates.extend(shard_dupes)

    await db.commit()

    # 11-06 用户拍板：链接任务**导入即下载原片**，不用等反推、也不用任何人确认解析费
    # （0.01 元/条照记账进批次成本）。放在 commit 之后——排程函数要自己 commit，
    # 且后台协程只读得到已提交的行。排不上只回 note，绝不连累导入结果（与反推搭车同口径）。
    download_kicks: List[dict] = []
    if data.auto_download and created:
        for b, ids in zip(batches, batch_asset_ids):
            if ids:
                download_kicks.append(
                    await _enqueue_download(db, asset_ids=ids, operator=current_user, batch_id=str(b.id))
                )

    worst = max(budgets, key=lambda b: ["ok", "need_approval", "blocked"].index(b["gate"]))
    budget = {**worst, "batches": len(batches),
              "cost_estimate": round(sum(b["cost_estimate"] or 0 for b in budgets), 4)}
    return {
        "batch": _serialize_batch(batches[0]),
        "batches": [_serialize_batch(b) for b in batches],
        "split_into": (
            {
                "shards": len(shards),
                "limit": limit,
                "per_shard": [len(s) for s in shards],
                "note": f"提交 {len(entries)} 条 > 单批上限 {limit}，已自动拆成 {len(shards)} 个批次（顺序不变、一条不丢）",
            }
            if len(shards) > 1 else None
        ),
        "items": [_serialize_item(a) for a in created],
        "duplicates": duplicates,
        "skipped": skipped,
        "budget": budget,
        "budgets": budgets,
        "download": download_kicks or None,
        "message": (
            f"导入 {len(created)} 条"
            + (f"（拆成 {len(shards)} 批）" if len(shards) > 1 else "")
            + (f"，跳过重复 {len(duplicates)} 条" if duplicates else "")
            + (f"，{len(skipped)} 条提示" if skipped else "")
            + _auto_download_phrase(download_kicks, len(created))
            + (
                f"；这批若全按 {tier}s 档反推预估 {budget['cost_estimate']} 元，"
                f"超单批上限 {budget['cap']} 元，反推时需管理员放批或拆批"
                if budget["gate"] != "ok" else ""
            )
        ),
    }


def _auto_download_phrase(kicks: List[dict], total: int) -> str:
    """导入后自动下载的一句白话：排上了说几条在跑，没排上说为什么（不吓人也不装没事）。"""
    if not kicks:
        return ""
    queued = sum(1 for k in kicks if k.get("queued"))
    if queued:
        return f"；原片已自动开始下载（{sum(k.get('queued_count') or 0 for k in kicks)} 条，解析 0.01 元/条照记账），进度看任务条"
    note = next((k.get("note") for k in kicks if k.get("note")), None)
    return f"；原片下载没自动排上：{str(note)[:120]}（可在列表勾选后手工点下载）" if note else ""


_UPLOAD_CONCURRENCY = 3
# 单请求整包上限 = nginx `client_max_body_size 500M`（nginx.conf:92）。逐文件并发把
# N 个文件拆成 N 个请求，等于绕开"200 个文件一次提交必然 413、而且回的是 nginx 的 HTML
# 不是 JSON"这一坑（A4-5）；前端一次建批次、按 batch_id 分批投即可。


async def _probe_duration(path: str) -> Optional[float]:
    """ffprobe 探本地文件时长（A4-4：duration 列全链路无一处写入 → 列表「时长」列必空）。

    同步 subprocess 放线程里跑，别在事件循环里等 30 秒；探不到就回 None——
    「没探到」和「0 秒」是两件事，写 0 会让前端显示 0:00 并让人以为素材是空的。
    """
    loop = asyncio.get_running_loop()
    try:
        seconds = await loop.run_in_executor(None, _ffprobe_duration, path)
    except Exception as exc:  # ffprobe 不在 PATH / 文件损坏
        logger.warning("ffprobe 探测失败 %s: %s", path, exc)
        return None
    return round(float(seconds), 2) if seconds and seconds > 0 else None


async def _probe_url_duration(url: str, budget_seconds: float = 8.0) -> Optional[float]:
    """直链素材探时长（A4-4 的链接侧回写）。

    ffprobe 自带 30s 超时，但那是**线程**的超时，不是请求的：一线点「刷新状态」不该
    被一个远端站点的慢响应挂住 30 秒，所以外面再套一层 `wait_for` 收在 8 秒。
    超时只是**放弃等结果**（那条素材时长留空，下次刷新再探），不会写错数、也不花钱。

    SSRF 防护：url 可能是用户贴的任意地址，先过公网校验（net_guard），内网/环回/非
    http(s) 一律拒绝且只记 warning——拒绝不花钱也不影响主流程（时长留空下次再探）。
    """
    loop = asyncio.get_running_loop()
    try:
        await assert_public_http_url_async(url)
    except UnsafeURLError as exc:
        logger.warning("直链未过 SSRF 校验，跳过时长探测 %s: %s", url[:120], exc)
        return None
    try:
        seconds = await asyncio.wait_for(
            loop.run_in_executor(None, _ffprobe_duration, url), timeout=budget_seconds
        )
    except asyncio.TimeoutError:
        logger.info("ffprobe 探直链超时（%.0fs），跳过时长回写", budget_seconds)
        return None
    except Exception as exc:
        logger.info("ffprobe 探直链失败 %s: %s", url[:120], exc)
        return None
    return round(float(seconds), 2) if seconds and seconds > 0 else None


async def _ingest_one_video_file(
    f: UploadFile,
    *,
    tmp_dir: str,
    batch_code: str,
    max_bytes: int,
    sem: "asyncio.Semaphore",
) -> dict:
    """单个文件：落盘 → 探时长 → 传自有桶。**全程不碰 db**。

    AsyncSession 不是并发安全的，所以并发只做 I/O 这一段，建行留给调用方串行做（A4-5）。
    """
    name = (f.filename or "").strip()
    ext_err = validate_upload_ext(name)
    if ext_err:
        return {"ok": False, "file_name": name, "error": ext_err}
    try:
        safe_name = validate_file_name(name)
    except ValueError as e:
        return {"ok": False, "file_name": name, "error": str(e)}

    async with sem:
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.part")
        size = 0
        try:
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    # 这一行是全部意义的所在：只数长度不落盘，桶里就会躺一个 0 字节对象，
                    # 而接口照样回 201、file_size 照样记真实大小（11-04 拼接实测才发现，
                    # 单测把 MinIO 整个 mock 掉，这类"落盘漏字节"只有真链路能抓到）。
                    out.write(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        return {
                            "ok": False, "file_name": safe_name,
                            "error": (
                                f"文件过大（{size / 1024 / 1024:.1f}MB），上限 {max_bytes // 1024 // 1024}MB："
                                "本接口不分片，请先压一遍或用 /api/upload 的分片续传通道"
                            ),
                        }
            # 落盘字节数与读到的字节数必须相等：不相等就是"计数与写入脱钩"，
            # 与其把一个空壳对象传进桶（反推时拿它去 doc/125 会白扣一次钱），不如当场判失败。
            written = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if written != size:
                return {
                    "ok": False, "file_name": safe_name,
                    "error": f"落盘不完整（读到 {size} 字节、磁盘只有 {written} 字节），本个文件未入库",
                }
            size_err = validate_upload_size(size)
            if size_err:
                return {"ok": False, "file_name": safe_name, "error": size_err}
            duration = await _probe_duration(tmp_path)
            # 宽高同一条 ffprobe `stream=width,height` 查询，视频与图通用（`_probe_image_size`
            # 名字带 image 只是历史包袱）。为什么视频也要量：画幅是**素材自己的属性**，
            # 11-09 起横屏原片要在界面标出来（画幅由角色卡宽高比决定，投产前必须看得见），
            # 而 `resolution` 只有入库这一刻能免费量到——链接素材是下载后回写，文件素材此前
            # 一直没写，列表与投产口只能显示「画幅未知」。
            width, height = await _probe_image_size(tmp_path)
            file_key = f"asset/{batch_code}/{uuid.uuid4().hex}_{safe_name}"
            # content type 按真实扩展名给：写死 video/mp4 的话 .mov/.webm 在桶里是错标签，
            # 浏览器 presigned 直连会当 mp4 解（Safari 直接黑屏），下载侧也无法按类型还原
            ok = await upload_file_from_path(
                settings.MINIO_BUCKET_RAW,
                file_key,
                tmp_path,
                content_type=EXT_CONTENT_TYPES.get(
                    os.path.splitext(safe_name)[1].lower(), "video/mp4"
                ),
            )
            if not ok:
                return {
                    "ok": False, "file_name": safe_name,
                    "error": "对象存储写入失败。原文件没入库，带 batch_id 走 /assets/upload/retry 补投这一个",
                }
            return {"ok": True, "file_name": safe_name, "file_key": file_key,
                    "size": size, "duration": duration, "media_kind": MEDIA_VIDEO,
                    "width": width, "height": height}
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def _ffprobe_image_size(path: str) -> Tuple[Optional[int], Optional[int]]:
    """ffprobe 量图片宽高，探不到回 (None, None)。

    为什么不用 PIL：本仓库的 ffmpeg/ffprobe 已是既成依赖（抽帧、探时长、拼接都在用），
    PIL 是新增依赖；口径也和视频侧统一——"探不出"都只提醒、不拒收。
    """
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 — 量不出来不该影响入库
        logger.info("ffprobe 量图片尺寸失败 %s: %s", path, exc)
        return None, None
    parts = [p.strip() for p in (out.stdout or "").split() if p.strip()]
    if len(parts) < 2:
        return None, None
    try:
        return int(float(parts[0])), int(float(parts[1]))
    except ValueError:
        return None, None


async def _probe_image_size(path: str) -> Tuple[Optional[int], Optional[int]]:
    """executor 里跑 `_ffprobe_image_size`，别把事件循环卡在磁盘 I/O 上。"""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _ffprobe_image_size, path), timeout=45
        )
    except asyncio.TimeoutError:
        logger.info("ffprobe 量图片尺寸超时（45s），尺寸留空只提醒")
        return None, None
    except Exception as exc:  # noqa: BLE001
        logger.info("ffprobe 量图片尺寸异常：%s", exc)
        return None, None


async def _ingest_one_image_file(
    f: UploadFile,
    *,
    tmp_dir: str,
    batch_code: str,
    max_bytes: int,
    sem: "asyncio.Semaphore",
) -> dict:
    """图片入库（11-05 批 G）：落盘 → 量尺寸 → 传自有桶。**不碰 db**，与视频口同一个并发约束。

    为什么单独一条 ingest、不复用 `_ingest_one_video_file`：
    1. **白名单不能共用**。`wechat_download/prompt_service.py` 的 `UPLOAD_ALLOWED_EXTS`
       是素材库与采集侧**共用**的（`wechat_download/api.py` 也调 `validate_upload_ext`）。
       往那里加图片，等于让图片能喂进 doc/120 视频反推 —— 白扣一次钱，还得等超时才失败。
       所以图片走 `svc.validate_asset_image_ext`（素材库侧独立口径），视频侧一行不动。
    2. 视频探 `duration`，图片探 `width/height`：两套判读，混在一个函数里只会变成 if 套 if。

    尺寸超限**不拒收**（拍板③）：原因放进 `notes` 回给前端显示，入库照常。
    """
    name = (f.filename or "").strip()
    ext_err = svc.validate_asset_image_ext(name)
    if ext_err:
        return {"ok": False, "file_name": name, "error": ext_err, "media_kind": MEDIA_IMAGE}
    try:
        # 不用 `validate_file_name`：它按 ALLOWED_VIDEO_EXTENSIONS 判扩展名，图片必被拒。
        # 消毒的那一半（掐路径穿越）由 `sanitize_asset_file_name` 原样保留。
        safe_name = svc.sanitize_asset_file_name(name)
    except ValueError:
        return {"ok": False, "file_name": name, "error": "文件名为空或不是合法文件名，无法入库",
                "media_kind": MEDIA_IMAGE}

    async with sem:
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.part")
        size = 0
        try:
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        return {
                            "ok": False, "file_name": safe_name, "media_kind": MEDIA_IMAGE,
                            "error": (
                                f"图片过大（{size / 1024 / 1024:.1f}MB），上限 "
                                f"{max_bytes // 1024 // 1024}MB（ASSET_IMAGE_MAX_SIZE_MB）："
                                "角色卡不用原图那么大，先压到 2000px 以内再传"
                            ),
                        }
            # 与视频口同一条硬规矩：只数长度不落盘 = 桶里躺一个 0 字节对象、接口照样 201
            written = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if written != size:
                return {
                    "ok": False, "file_name": safe_name, "media_kind": MEDIA_IMAGE,
                    "error": f"落盘不完整（读到 {size} 字节、磁盘只有 {written} 字节），本个文件未入库",
                }
            size_err = svc.validate_asset_image_size(
                size, max_mb=settings.ASSET_IMAGE_MAX_SIZE_MB
            )
            if size_err:
                return {"ok": False, "file_name": safe_name, "error": size_err,
                        "media_kind": MEDIA_IMAGE}
            width, height = await _probe_image_size(tmp_path)
            ext = svc.file_ext(safe_name)
            file_key = f"asset/{batch_code}/{uuid.uuid4().hex}_{safe_name}"
            ok = await upload_file_from_path(
                settings.MINIO_BUCKET_RAW,
                file_key,
                tmp_path,
                # content type 按真实扩展名给：写死 image/jpeg 的话 .png/.webp 在桶里是错标签，
                # 浏览器 presigned 直连会按 jpeg 解（挑卡预览会花屏）
                content_type=svc.IMAGE_CONTENT_TYPES.get(ext, "application/octet-stream"),
            )
            if not ok:
                return {
                    "ok": False, "file_name": safe_name, "media_kind": MEDIA_IMAGE,
                    "error": "对象存储写入失败。原图没入库，带 batch_id 走 /assets/upload/retry 补投这一张",
                }
            return {
                "ok": True, "file_name": safe_name, "file_key": file_key, "size": size,
                "media_kind": MEDIA_IMAGE,
                "width": width, "height": height,
                "aspect": svc.image_aspect(width, height),
                "notes": svc.image_shape_notes(
                    width, height,
                    min_edge=settings.ASSET_IMAGE_MIN_EDGE,
                    max_edge=settings.ASSET_IMAGE_MAX_EDGE,
                ),
            }
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


async def _upload_into_batch(
    db: AsyncSession,
    batch: AssetBatch,
    files: List[UploadFile],
    *,
    project_uuid: Optional[uuid.UUID],
    current_user: User,
    action: str,
    batch_is_new: bool = False,
    category_uuid: Optional[uuid.UUID] = None,
) -> dict:
    """文件批量入库的共用内核（/upload/batch 与 /upload/retry 只差批次来源）。

    `batch_is_new` 决定"一个都没成功"时要不要回滚批次行：本次请求新建的批次必须回滚，
    否则留下 0 条素材的孤儿批次（对账页会出现一个空批次，一线以为丢了文件）；
    往已有批次追加（`batch_id` 入参 / retry）时批次是既成事实，回滚会把别人已经
    传进去的那批一起抹掉——所以只回传失败清单，批次行留着。
    """
    max_bytes = upload_max_bytes()
    # R-7（11-04 第二轮审核）：这里原来写的是 `settings.ASSET_PROMPT_MAX_DURATION_DEFAULT`——
    # **config.py 里没有这个字段**，取它会 AttributeError（本机 `hasattr` 实测为假）。
    # 眼下炸不到只是因为上一行 `or` 短路（建批两条路都必写档位），那是踩着运气：一旦出现
    # tier 为 NULL 的批次行（历史数据、手工建批），文件批量入库当场 500。
    # 改成走 `_tier_or_400`：没配就取默认档，配了个非白名单档位则**当场 400 说清楚**，
    # 不拿脏档位去算钱（与链接导入 `:495` 同一个口径）。
    tier = _tier_or_400(batch.prompt_max_duration)
    # 图片上限独立于视频（`upload_max_bytes()` 是视频那套），先按 MB 折成字节
    image_max_bytes = max(1, int(settings.ASSET_IMAGE_MAX_SIZE_MB)) * 1024 * 1024
    sem = asyncio.Semaphore(_UPLOAD_CONCURRENCY)
    tmp_dir = os.path.join(tempfile.gettempdir(), f"asset_upload_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        results = await asyncio.gather(*[
            (
                _ingest_one_image_file(
                    f, tmp_dir=tmp_dir, batch_code=batch.code,
                    max_bytes=image_max_bytes, sem=sem,
                )
                # 按扩展名分流**只在这里用一次**：入库之后所有环节看 media_kind 这一列
                if svc.is_image_file_name(f.filename)
                else _ingest_one_video_file(
                    f, tmp_dir=tmp_dir, batch_code=batch.code, max_bytes=max_bytes, sem=sem
                )
            )
            for f in files
        ])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    created: List[AssetItem] = []
    failed: List[dict] = []
    image_notes: List[dict] = []
    for res in results:
        if not res["ok"]:
            failed.append({"file_name": res["file_name"], "error": res["error"]})
            continue
        is_image = res.get("media_kind") == MEDIA_IMAGE
        asset = AssetItem(
            code=gen_asset_code(),
            batch_id=batch.id,
            source_kind=SOURCE_FILE,
            # 11-05 批 G：链接口只产 video，文件口两种都有。这一列是后面四环闸门的**唯一判据**
            media_kind=MEDIA_IMAGE if is_image else MEDIA_VIDEO,
            file_name=res["file_name"][:255],
            file_key=res["file_key"],
            bucket=settings.MINIO_BUCKET_RAW,
            file_size=res["size"],
            duration=res.get("duration"),      # A4-4：上传时就回写，列表「时长」列不再空转（图没有时长）
            title=res["file_name"],
            project_id=project_uuid,
            # 11-04 拍板①：文件导入同样吃"整批默认原型"（留空＝未分类，日后逐条点）
            category_id=category_uuid,
            stage_import=STAGE_SUCCESS,
            created_by=current_user.id,
        )
        # 画幅：视频和图片一律入库时就量（11-09 起横屏原片要在界面标出来，
        # 而 resolution 只有这一刻免费拿得到——链接素材是下载后回写，文件素材此前只给图写，
        # 视频行一直空着，列表与投产口只能显示「画幅未知」。
        asset.resolution = (
            f"{res['width']}x{res['height']}" if res.get("width") and res.get("height") else None
        )
        if is_image:
            # 图片四阶段一律 skipped（拍板③：图是**生产输入**，不参与反推/文案/投产/拼接）。
            # 不显式写 skipped 的话它们会停在 pending —— 于是既在「待反推」计数里碍事，
            # 又会被 `_batch_queue_assets` 的 `stage in (pending, skipped)` 捞进反推队列＝白扣钱。
            asset.stage_prompt = STAGE_SKIPPED
            asset.stage_summary = STAGE_SKIPPED
            asset.stage_produce = STAGE_SKIPPED
            asset.stage_compose = STAGE_SKIPPED
            # 抽帧对图没有意义（原图本身就是封面），直接把 file_key 当封面
            asset.cover_image_key = res["file_key"]
        # 派生态必须带 media_kind：不带的话图会一路落到 `waiting_prompt`（"待反推"），
        # 列表里每张角色卡都变成"卡着没人管"，而正确动作恰恰是**别提交**（批 G 立这一支的原因）
        asset.status = svc.derive_status(
            {"import": STAGE_SUCCESS}, media_kind=asset.media_kind
        )
        db.add(asset)
        created.append(asset)
        if is_image and res.get("notes"):
            image_notes.append({
                "file_name": res["file_name"],
                "resolution": asset.resolution,
                "ratio": (res.get("aspect") or {}).get("ratio"),
                "notes": res["notes"],
            })

    if not created:
        # 一个都没成功：本次新建的批次回滚不留孤儿行；往已有批次追加（batch_id / retry）
        # 只回失败清单，批次行是既成事实不能动
        if batch_is_new:
            await db.rollback()
        return {
            "batch": None if batch_is_new else _serialize_batch(batch),
            "batch_id": None if batch_is_new else str(batch.id),
            "items": [],
            "failed": failed,
            "failed_files": [x["file_name"] for x in failed],
            "budget": None,
            "image_notes": [],
            "message": (
                f"上传失败 {len(failed)} 个，没有成功入库的文件"
                + ("（批次未创建，修正后可直接重投）" if batch_is_new
                   else "（原批次没动，修好的文件带 batch_id 走 /assets/upload/retry）")
            ),
        }

    batch.item_count = (batch.item_count or 0) + len(created)
    # ⚠️ `video_ids` 必须算在 flush **之后**：SQLAlchemy 的客户端默认值（`id=uuid.uuid4`）
    # 是 INSERT 时才赋的，add() 之后 `a.id` 还是 None —— 早一步就得到一串 "None" 的
    # asset_ids，抽帧台账带着它去 `uuid.UUID("None")` 当场炸（11-05 加这一行时就踩在
    # flush 前面，批 F 的抽帧用例直接红了）。
    await db.flush()
    image_count = sum(1 for a in created if a.media_kind == MEDIA_IMAGE)
    video_ids = [str(a.id) for a in created if a.media_kind == MEDIA_VIDEO]
    # 图不计费（拍板③）：`count` 里混进图片，预估会把"永远不需要反推"的张数也算成钱，
    # 一线看到的"超单批预算"是假警报，而假警报喊多了人就真不看闸门了。
    billable_videos = await _batch_video_count(db, batch.id)
    # A1-4：文件形态反推要把自有桶对象经 doc/125 中转上传一次，故 need_upload=True。
    # 预算按**批次全量**重算（retry 追加后不能还挂着首次那批的旧数）
    budget = _apply_import_budget(batch, count=billable_videos, tier=tier, need_upload=True)
    await _write_audit(
        db,
        action=action,
        operator=current_user,
        target_type="asset_batch",
        target_id=batch.id,
        after={
            "batch_code": batch.code,
            "created": len(created),
            "failed": len(failed),
            "tier": tier,
            "item_count": batch.item_count,
            # 批 G：留痕分媒体类型，对账时能说清"这批的钱是按几条视频估的"
            "images": image_count,
            "billable_videos": billable_videos,
            "concurrency": _UPLOAD_CONCURRENCY,
            "cost_estimate": batch.cost_estimate,
            "budget_gate": batch.budget_gate,
        },
    )
    await db.commit()

    # 批 F：入库成功 = 系统自动排抽帧（只有文件形态抽得了帧，链接素材桶里没原片）。
    # 批 G：图片**不排**抽帧 —— 原图本身就是封面（上面已直接写 cover_image_key），
    # 排进去只是让 ffmpeg 去解一张 jpg，白占后台名额。
    frames = (
        await _enqueue_frames(
            db,
            asset_ids=video_ids,
            output_ids=[],
            operator=current_user,
            why=f"文件入库 {len(video_ids)} 个",
        )
        if video_ids
        else {
            "queued": False,
            "note": "这批只进图片，不抽帧（原图就是封面）",
        }
    )

    return {
        "batch": _serialize_batch(batch),
        "batch_id": str(batch.id),
        "items": [_serialize_item(a) for a in created],
        "failed": failed,
        "failed_files": [x["file_name"] for x in failed],
        "budget": budget,
        "frames": frames,
        # 尺寸提醒原样回传（超限**不拒收**，但必须让人看见）：前端在上传结果里逐张列
        "image_notes": image_notes,
        "message": (
            f"上传入库 {len(created)} 个"
            + (f"（其中图片 {image_count} 张：只作生产输入，不反推、不出文案、不计费）"
               if image_count else "")
            + (f"，失败 {len(failed)} 个（带 batch_id 走 /assets/upload/retry 只补投这几个）" if failed else "")
            + (f"；{'抽帧已排后台，卡片稍后出图' if frames['queued'] else '卡片图这次没排上'}"
               if video_ids else "")
            + (f"；有 {len(image_notes)} 张图尺寸/画幅要留意，明细在 image_notes"
               if image_notes else "")
            + (
                f"；这批 {billable_videos} 条视频若全按 {tier}s 档反推预估 {budget['cost_estimate']} 元，"
                f"超单批上限 {budget['cap']} 元，反推时需管理员放批或拆批"
                if budget["gate"] != "ok" else ""
            )
        ),
    }


@router.post("/assets/upload/batch", status_code=201)
async def upload_files_batch(
    files: List[UploadFile] = File(..., description="视频或图片文件（可多个，按扩展名自动分流）"),
    name: Optional[str] = Form(None, description="批次名"),
    project_id: Optional[str] = Form(None, description="归属项目（可选）"),
    max_duration: Optional[int] = Form(None, description="本批反推计时上限档位（秒）"),
    batch_id: Optional[str] = Form(None, description="已有批次 id：前端一次建批次、逐文件（或每 3 个）投同一批（A4-5）"),
    category_id: Optional[str] = Form(None, description="11-04 拍板①：本批整批默认钩子原型（可留空＝未分类）"),
    current_user: User = Depends(require_roles(*_PROD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """视频/图片文件批量上传 → 落自有 MinIO（raw-footage 的 asset/ 前缀）。

    11-05 批 G：同一口收图片（拍板③——图片是**真收进素材库的生产输入**，不是附件）。
    按扩展名自动分流：`.jpg/.jpeg/.png/.webp` 走 `_ingest_one_image_file`（独立白名单与
    尺寸上限），其余仍走视频那条。图片入库即 `media_kind=image`、四阶段 `skipped`、
    不计费、不抽帧（原图就是封面）、`status=image_ready`。

    为什么自有桶而不是智令 temp 桶：doc/125 的 S3 临时对象 6 小时后自删，
    素材库要的是「资产」不是「中转」；反推时再把对象取回走 doc/125 上传（见 analyze）。

    逐文件 fail-soft：一个文件失败不影响整批，失败原因在 failed[] 里回给前端，
    并给出 `failed_files` 文件名清单供一键重试。

    A4-5 的四件事：
    - `batch_id` 入参：没有它，前端逐文件提交会一请求一批次，200 文件 = 200 批次，对账页直接废；
    - 并发 3（`_UPLOAD_CONCURRENCY`）：落盘与对象写入段并发，建行仍串行（AsyncSession 非并发安全）；
    - 超限文件给明确引导语（本接口不分片），不再是 nginx 那页 413 HTML；
    - 失败补投走 `POST /assets/upload/retry`。
    """
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")
    # 11-04 拍板①：整批默认原型（与链接导入同一个入参口径）
    category_uuid = await _resolve_category_or_400(db, category_id)
    if len(files) > int(settings.ASSET_IMPORT_BATCH_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"单请求最多 {settings.ASSET_IMPORT_BATCH_MAX} 个文件；"
                   f"更多请带同一个 batch_id 分几次投（先建批次，再逐次 retry/upload）",
        )

    if batch_id:
        batch = await db.get(AssetBatch, _as_uuid(batch_id, "batch_id"))
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在，batch_id 传错了")
        if batch.source_kind != SOURCE_FILE:
            raise HTTPException(status_code=400, detail="该批次是链接批次，不接受文件上传")
        if batch.created_by != current_user.id and current_user.role != UserRole.admin.value:
            raise HTTPException(status_code=403, detail="只能往自己创建的批次里追加文件")
        project_uuid = _as_uuid(project_id, "project_id") if project_id else None
        if max_duration:
            batch.prompt_max_duration = _tier_or_400(max_duration)
        await db.flush()
        return await _upload_into_batch(
            db, batch, files, project_uuid=project_uuid, current_user=current_user,
            action="asset.upload_files", batch_is_new=False, category_uuid=category_uuid,
        )

    tier = _tier_or_400(max_duration)
    project_uuid = _as_uuid(project_id, "project_id") if project_id else None
    batch = AssetBatch(
        code=gen_batch_code(),
        name=(name or "").strip() or f"文件上传 {len(files)} 个",
        source_kind=SOURCE_FILE,
        prompt_max_duration=tier,
        budget_cap=settings.ASSET_BATCH_BUDGET_CAP,
        created_by=current_user.id,
    )
    db.add(batch)
    await db.flush()
    return await _upload_into_batch(
        db, batch, files, project_uuid=project_uuid, current_user=current_user,
        action="asset.upload_files", batch_is_new=True, category_uuid=category_uuid,
    )


@router.post("/assets/upload/retry")
async def retry_upload_files(
    batch_id: str = Form(..., description="首次上传返回的批次 id"),
    files: List[UploadFile] = File(..., description="只投上次失败的那几个文件"),
    current_user: User = Depends(require_roles(*_PROD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """把某批次里失败的文件补投进**同一批次**（A4-5 的「无失败一键重试」）。

    做不到的事说清楚：文件字节不在服务端留存（失败的那个根本没落库），所以重试必须
    由前端把手上的原文件再传一次——这里能省的是"重新建批次、重新对不上账"。
    批次行不新建、`item_count` 与预算按追加后的全量重算，成本对账页看到的仍是一个批次。
    """
    if not files:
        raise HTTPException(status_code=400, detail="没有要补投的文件")
    batch = await db.get(AssetBatch, _as_uuid(batch_id, "batch_id"))
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.source_kind != SOURCE_FILE:
        raise HTTPException(status_code=400, detail="该批次是链接批次，没有文件可补投")
    if batch.created_by != current_user.id and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="只能补投自己创建的批次")
    # 11-04 拍板①：补投的文件**跟原批走**同一个原型。判据只用"这批已入库素材里那一个
    # 非空分类"：原批里出现过两个不同分类就**不猜**，补投的落未分类（前端可再逐条点）。
    # 为什么不在这里收 category_id 入参：retry 的语义是"把上次没成功的补回同一批"，
    # 让前端再选一次原型等于给同一批次开出两种归属的机会。
    cat_rows = list(
        (
            await db.execute(
                select(AssetItem.category_id)
                .where(AssetItem.batch_id == batch.id, AssetItem.category_id.is_not(None))
                .distinct()
                .limit(2)
            )
        ).scalars().all()
    )
    category_uuid = cat_rows[0] if len(cat_rows) == 1 else None
    return await _upload_into_batch(
        db, batch, files, project_uuid=None, current_user=current_user,
        action="asset.upload_retry", batch_is_new=False, category_uuid=category_uuid,
    )


# ──────────────────────────────────────────────
# 列表 / 详情
# ──────────────────────────────────────────────


@router.get("/assets")
async def list_assets(
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
    platform: Optional[str] = None,
    source_kind: Optional[str] = None,
    # 批 G：`media_kind=image` 是前端「挑卡」列表的入口（投产时只该看见图），
    # 没有它就得让前端把整批拉回来自己按扩展名筛——那等于把 media_kind 的口径散到前端去。
    media_kind: Optional[str] = None,
    has_approved_copy: Optional[bool] = None,
    keyword: Optional[str] = None,
    created_by: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    audit_status: Optional[str] = None,
    stage_import: Optional[str] = None,
    stage_prompt: Optional[str] = None,
    stage_summary: Optional[str] = None,
    stage_produce: Optional[str] = None,
    stage_compose: Optional[str] = None,
    category_id: Optional[str] = None,
    sort: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """素材列表：一行 = 一条素材（批量筛选靠 batch_id/status，不做批次父行页）。

    A4-3 补齐的四个筛选（缺一线就没法用：昨天那 200 条里谁卡住、卡在哪一步，
    只能一页页翻）：`created_by`（创建人）、`date_from`/`date_to`（导入日期区间，
    含端点、按 CST 的自然日）、`audit_status`（审核态，命中"这条素材的候选里有该态的"）、
    `stage_*`（**阶段级**：status=failed 只说"失败了"，stage_prompt=failed 才说得出
    是反推挂的还是生产挂的）。`sort=failed_first` 把任一阶段 failed 的顶到最前。

    11-04 拍板①加的 `category_id`：按钩子原型筛；传 `none` 只看未分类——一线靠它清欠账
    （列表页顶部那个"未分类 N 条"就是拿 `category_id=none` 的 `total` 显示的，不另开口）。
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    conds = []
    if status:
        conds.append(AssetItem.status == status)
    if batch_id:
        conds.append(AssetItem.batch_id == _as_uuid(batch_id, "batch_id"))
    if platform:
        conds.append(AssetItem.platform == platform)
    if source_kind:
        conds.append(AssetItem.source_kind == source_kind)
    if media_kind:
        # 非法值当场 400 而不是默默筛成空集：拼错 `iamge` 时前端会显示"库里没有图"，
        # 那比报错更难查（同一类坑，11-04 风险词库级别键就是靠这条改的）
        if media_kind not in MEDIA_KINDS:
            raise HTTPException(
                status_code=400,
                detail=f"media_kind 只能是 {' 或 '.join(MEDIA_KINDS)}，收到 {media_kind}",
            )
        conds.append(AssetItem.media_kind == media_kind)
    if has_approved_copy is not None:
        conds.append(AssetItem.has_approved_copy.is_(bool(has_approved_copy)))
    # 11-04 拍板①：按钩子原型筛；`none`＝只看未分类（一线用它清欠账）
    cat_cond = _category_cond(category_id)
    if cat_cond == "none":
        conds.append(AssetItem.category_id.is_(None))
    elif cat_cond is not None:
        conds.append(AssetItem.category_id == cat_cond)
    if keyword:
        kw = f"%{keyword.strip()}%"
        conds.append(
            or_(AssetItem.code.ilike(kw), AssetItem.title.ilike(kw), AssetItem.source_url.ilike(kw))
        )

    # ── A4-3：创建人 / 日期区间 / 审核态 / 阶段级 ──
    if created_by:
        conds.append(AssetItem.created_by == _as_uuid(created_by, "created_by"))
    for param, value in (("date_from", date_from), ("date_to", date_to)):
        if not value:
            continue
        try:
            moment = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{param} 要 YYYY-MM-DD（按 CST 自然日），当前={value}")
        # 库里 created_at 是 UTC naive，一线说的是"几号导入的"→ 边界按 CST 换算回 UTC。
        # from 取当日 00:00（含），to 取次日 00:00（不含）——写成 `<= 当日00:00` 会只捞到
        # 零点整那一分钟，看着能用、实际永远筛不出东西。
        utc_day_start = moment - timedelta(hours=8)
        if param == "date_from":
            conds.append(AssetItem.created_at >= utc_day_start)
        else:
            conds.append(AssetItem.created_at < utc_day_start + timedelta(days=1))
    if audit_status:
        if audit_status not in REVIEW_STATES:
            raise HTTPException(status_code=400, detail=f"audit_status 只认 {'/'.join(REVIEW_STATES)}")
        conds.append(
            AssetItem.id.in_(
                select(AssetSummary.asset_id).where(AssetSummary.audit_status == audit_status)
            )
        )
    stage_columns = {
        "stage_import": AssetItem.stage_import,
        "stage_prompt": AssetItem.stage_prompt,
        "stage_summary": AssetItem.stage_summary,
        "stage_produce": AssetItem.stage_produce,
        "stage_compose": AssetItem.stage_compose,
    }
    for name, value in (
        ("stage_import", stage_import), ("stage_prompt", stage_prompt),
        ("stage_summary", stage_summary), ("stage_produce", stage_produce),
        ("stage_compose", stage_compose),
    ):
        if value is None:
            continue
        if value not in STAGE_STATES:
            raise HTTPException(
                status_code=400, detail=f"{name} 只认 {'/'.join(STAGE_STATES)}，当前={value}")
        conds.append(stage_columns[name] == value)

    order_keys = ("created_desc", "created_asc", "failed_first")
    order = (sort or "created_desc").strip().lower()
    if order not in order_keys:
        raise HTTPException(status_code=400, detail=f"sort 只认 {'/'.join(order_keys)}")
    stuck = or_(*(column == STAGE_FAILED for column in stage_columns.values()))

    base = select(AssetItem).where(and_(*conds)) if conds else select(AssetItem)
    total = (
        await db.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    if order == "failed_first":
        # 卡住的排最前，同组内仍按导入时间倒序（"哪条要人看"是这一排序的唯一目的）
        ordering = [stuck.desc(), AssetItem.created_at.desc()]
    elif order == "created_asc":
        ordering = [AssetItem.created_at.asc()]
    else:
        ordering = [AssetItem.created_at.desc()]
    items = list(
        (
            await db.execute(base.order_by(*ordering).offset((page - 1) * page_size).limit(page_size))
        ).scalars().all()
    )

    # 候选/过审/生产数量：一次聚合补齐整页，避免逐行 N+1
    ids = [a.id for a in items]
    agg: Dict[uuid.UUID, dict] = {
        # 先给整页铺零：聚合只回命中行，缺了键前端就得自己判 nil（列表角标会闪空）
        aid: {"summary_count": 0, "approved_count": 0, "pending_review_count": 0,
              "production_count": 0}
        for aid in ids
    }
    if ids:
        srows = (
            await db.execute(
                select(
                    AssetSummary.asset_id,
                    func.count(AssetSummary.id),
                    func.count(AssetSummary.id).filter(AssetSummary.audit_status.in_(REVIEW_PASSED_STATES)),
                    func.count(AssetSummary.id).filter(AssetSummary.audit_status == RV_PENDING),
                )
                .where(AssetSummary.asset_id.in_(ids))
                .group_by(AssetSummary.asset_id)
            )
        ).all()
        for aid, total_c, approved_c, pending_c in srows:
            agg[aid] = {
                "summary_count": total_c,
                "approved_count": approved_c,
                "pending_review_count": pending_c,
            }
        prows = (
            await db.execute(
                select(AssetProduction.asset_id, func.count(AssetProduction.id))
                .where(AssetProduction.asset_id.in_(ids))
                .group_by(AssetProduction.asset_id)
            )
        ).all()
        for aid, cnt in prows:
            agg.setdefault(aid, {})["production_count"] = cnt

    # 原型名一次批量补齐（字典是个位数行，不逐行查）
    cat_names = await _category_name_map(db)

    return {
        "items": [
            _serialize_item(
                a,
                {**(agg.get(a.id) or {}),
                 "category_name": cat_names.get(str(a.category_id)) if a.category_id else None},
            )
            for a in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "sort": order,
    }


@router.get("/assets/batches")
async def list_batches(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批次列表（含成本预估/实扣，对账页用）。"""
    limit = min(max(1, limit), 200)
    rows = (
        await db.execute(select(AssetBatch).order_by(AssetBatch.created_at.desc()).limit(limit))
    ).scalars().all()
    return {"items": [_serialize_batch(b) for b in rows]}


# ──────────────────────────────────────────────
# 反推提示词（智令 doc/120，花钱的一步）
# ──────────────────────────────────────────────


async def _batch_queue_assets(
    db: AsyncSession,
    *,
    batch_id: str,
    stage: str,
    limit: int,
    offset: int = 0,
    include_failed: bool = False,
    require_prompt_success: bool = False,
) -> Tuple[List[AssetItem], int]:
    """按批次取「本阶段还没跑」的下一段素材，返回 (本段行, 队列剩余条数)。

    为什么要有这一段（A4-6）：反推/出文案单次硬顶 20/10（同步等外部接口，多了网关超时），
    而前端一次排的是**整批 200 条**。没有排队口就只能让前端自己攒 id 列表、自己记进度，
    攒错一个就重复提交（重复＝重复扣费）。这里让服务端按阶段态取队列头，
    提交成功的条会自己从 eligible 集合里消失，所以 `offset` 平时就该留 0。

    `offset` 唯一有用的场景：队列头部某一条反复提交失败（它留在 pending 里挡住后面），
    一线拿它当「跳过这条」的手动逃生阀，不是分页浏览器。**不做成游标状态机**——
    真要有并发跑批，那是 P1 队列（Celery Job）的活，HTTP 层不造第二套调度。

    11-03 口径变更后这里**不套可见范围**：整批排队就是整批排队，谁提交都看得见全队。
    """
    if stage not in ("prompt", "summary"):
        raise HTTPException(status_code=500, detail="内部错误：未知队列阶段")
    stage_col = AssetItem.stage_prompt if stage == "prompt" else AssetItem.stage_summary
    eligible = [stage_col.in_([STAGE_PENDING, STAGE_SKIPPED])]
    if include_failed:
        eligible.append(stage_col == STAGE_FAILED)
    where = [
        AssetItem.batch_id == _as_uuid(batch_id, "batch_id"),
        # ⚠️ 批 G 这条不能删：eligible 里含 STAGE_SKIPPED，而图片的四个阶段**就是** skipped
        # （入库时显式写成 skipped）。少这一行，"整批排队"会把每张角色卡捞进反推队列，
        # 一条条送进 doc/120 —— 图片反推不会成功，但钱是按提交计的，等于白扣。
        AssetItem.media_kind == MEDIA_VIDEO,
        or_(*eligible),
    ]
    # 上游前置条件是 **AND**，不能塞进上面那个 or 组里：写进 or 就等于
    # 「本阶段没跑 或 上游已成功」，后者会把已成功一整段的素材全捞出来重跑一遍
    if require_prompt_success:
        where.append(AssetItem.stage_prompt == STAGE_SUCCESS)

    total = (
        await db.execute(select(func.count()).select_from(AssetItem).where(and_(*where)))
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(AssetItem)
                .where(and_(*where))
                .order_by(AssetItem.created_at, AssetItem.code)
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )
    return rows, max(0, int(total) - offset - len(rows))


def _queue_or_ids(data: Any, cap: int, *, what: str) -> Tuple[Optional[str], int, List[str]]:
    """两种入参形态（点名 asset_ids / 整批 batch_id）归一：返回 (batch_id, 本段条数, asset_ids)。"""
    has_ids = bool(getattr(data, "asset_ids", None))
    has_batch = bool(getattr(data, "batch_id", None))
    if has_ids and has_batch:
        raise HTTPException(
            status_code=400,
            detail="asset_ids 与 batch_id 二选一：点名若干条，或整批排队，别混着传",
        )
    if not has_ids and not has_batch:
        raise HTTPException(
            status_code=400,
            detail=f"请选择要{what}的素材：传 asset_ids，或传 batch_id 整批排队",
        )
    limit = int(getattr(data, "limit", None) or cap)
    if not 1 <= limit <= cap:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多{what} {cap} 条（同步等外部接口，多了会超时），limit 请在 1~{cap} 之间",
        )
    if has_ids and len(data.asset_ids) > cap:
        # 点名形态沿用旧口径的硬顶：点了 20 条就是 20 次串行外呼，网关先超时
        raise HTTPException(
            status_code=400,
            detail=f"单次最多{what} {cap} 条（同步等外部接口，多了会超时），当前 {len(data.asset_ids)} 条请分次提交",
        )
    return (data.batch_id if has_batch else None), limit, (data.asset_ids or [])


def _image_block_reason(asset: AssetItem, what: str) -> str:
    """图片进错口时的白话理由（反推/出文案/拼接三处共用，口径只有一套）。

    为什么单独写一句而不是直接 500：`media_kind` 之后图片在库里是合法行，一线完全可能
    在列表里勾中一张角色卡一起提交。这时给人看"internal error"没有任何信息量，
    而这句话要回答的是**"图能入库为什么不能用"**——答案是它是生产输入，不是内容源。
    """
    return (
        f"{asset.code}（{asset.file_name or '未命名'}）是图片，{what}只吃视频。"
        "图片收进素材库是给投产当角色卡/参考图用的，不参与反推、出文案和拼接——"
        "对一张静态图跑视频反推不会成功，但提交一次扣一次钱"
    )


async def _create_prompt_task_for_asset(
    db: AsyncSession, asset: AssetItem, *, operator: User, tier: int
):
    """给一条素材提交智令反推任务（页面批量提交与后台快速失败自动重试共用，口径只有一套）。

    R-6 的教训：闸门/口径分叉过一次就再没干净过。文件形态要「取回本地 → doc/125 中转
    上传」，链接形态直接 doc/120——这段两头都要走，抽成一个函数，重试时才不会出现
    「页面提交一套、自动重试另一套」。
    """
    if asset.source_kind == SOURCE_FILE:
        if not asset.file_key:
            raise ValueError("素材缺少文件对象，无法反推")
        # 自有桶在局域网内，智令拉不到 → 必须取回本地再走 doc/125 中转上传
        tmp_dir = os.path.join(tempfile.gettempdir(), f"asset_prompt_{uuid.uuid4().hex}")
        os.makedirs(tmp_dir, exist_ok=True)
        try:
            local_path = os.path.join(tmp_dir, f"{asset.code}.mp4")
            ok = await download_to_file(asset.bucket or settings.MINIO_BUCKET_RAW, asset.file_key, local_path)
            if not ok:
                raise RuntimeError("从对象存储取文件失败")
            size_err = validate_upload_size(os.path.getsize(local_path))
            if size_err:
                raise ValueError(size_err)
            with open(local_path, "rb") as fh:
                return await create_upload_prompt_task(
                    db,
                    created_by=operator.id,
                    file_obj=fh,
                    file_name=asset.file_name or f"{asset.code}.mp4",
                    size_bytes=os.path.getsize(local_path),
                    max_duration=tier,
                )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    if not asset.source_url:
        raise ValueError("素材缺少原始链接，无法反推")
    return await create_prompt_task(
        db,
        created_by=operator.id,
        source_url=asset.source_url,
        max_duration=tier,
    )


async def _converge_prompt_asset(db: AsyncSession, asset: AssetItem) -> Tuple[dict, Any]:
    """单条反推收敛核心（`refresh-batch` 接口与后台反推任务共用，口径只有一套）。

    返回 (JSON 安全的逐条结果, 智令任务对象或 None)。任务对象单独给：后台任务要按它
    判断「快速失败自动重试」，而 refresh-batch 的 HTTP 响应里绝不能混进 ORM 对象。
    阶段收敛（success/failed）只改内存里的行，落库由调用方的 commit 带上。
    """
    entry = {
        "asset_id": str(asset.id),
        "code": asset.code,
        "stage_prompt": asset.stage_prompt,
        "status": asset.status,
        "prompt_task_status": None,
        "error": None,
    }
    task = await get_prompt_task(db, asset.prompt_task_id) if asset.prompt_task_id else None
    if task is None:
        # 在跑却查不到任务行：等不出结果，判 failed 让一线能决定重跑
        svc.apply_stage(asset, "prompt", STAGE_FAILED)
        asset.note = (
            (asset.note or "")
            + "\n反推任务行缺失（提交后进程中断的残留），已判失败；重跑请带 retry_failed=true"
        )[:1000]
        entry.update(stage_prompt=asset.stage_prompt, status=asset.status,
                    error="任务行缺失，已判 failed", )
        return entry, None
    try:
        task = await refresh_prompt_task(db, task)
    except Exception as exc:  # 外呼抖动：保持 running，下轮再来
        entry["error"] = f"轮询失败，保持 running：{str(exc)[:200]}"
        return entry, task
    entry["prompt_task_status"] = task.status
    if task.status == PT_SUCCESS:
        svc.apply_stage(asset, "prompt", STAGE_SUCCESS)
        _backfill_title_on_prompt_success(asset, task.content)
    elif task.status == PT_FAILED:
        svc.apply_stage(asset, "prompt", STAGE_FAILED)
        asset.note = ((asset.note or "") + f"\n反推失败：{task.error}")[:1000]
        entry["error"] = task.error
    entry.update(stage_prompt=asset.stage_prompt, status=asset.status)
    return entry, task


async def _wait_prompt_convergence(
    db: AsyncSession,
    todo: List[AssetItem],
    *,
    operator: User,
    tier: int,
) -> dict:
    """后台反推任务的「原地等收敛」：轮询 + 快速失败自动重试一次（11-06 三连投诉的根治）。

    为什么必须在这里等：收敛原先**只靠前端轮询**（页面一关就没人收），搭车的
    「下载原片→抽帧」也跟着没人排——这就是「状态一直在反推中」的根因。
    到期没等完的行**不判失败**（智令还在跑，判死会让一线重跑重复扣费），留在 running
    交给「收取在跑结果」按钮。每轮 commit：中途崩了已收敛的行也不白跑。

    自动重试的口径：任务提交后 `ASSET_ANALYZE_FAST_FAIL_RETRY_SECONDS` 秒内就 failed
    才重试（实测「第一次总是出错」＝6 秒速死，重试一次就好）；跑了一阵才死的不是
    抖动，重试就是重复扣费。每条素材每次任务最多一次，逐条留审计。
    """
    poll = max(1.0, float(settings.ASSET_ANALYZE_JOB_POLL_SECONDS))
    deadline = time.monotonic() + max(60.0, float(settings.ASSET_ANALYZE_JOB_TIMEOUT_MINUTES) * 60.0)
    fast_window = max(5.0, float(settings.ASSET_ANALYZE_FAST_FAIL_RETRY_SECONDS))
    started = datetime.utcnow()
    retried: set = set()
    tally = {"success": 0, "failed": 0, "auto_retry": 0, "poll_error": 0}
    pending = [a for a in todo if a.stage_prompt == STAGE_RUNNING]
    deadline_hit = False
    try:
        while pending:
            still: List[AssetItem] = []
            for asset in pending:
                entry, task = await _converge_prompt_asset(db, asset)
                if (
                    entry["error"]
                    and entry["prompt_task_status"] is None
                    and "轮询失败" in entry["error"]
                ):
                    # 外呼抖动：保持 running，下一轮再来（任务行缺失的已判 failed，走下面终态分支）
                    tally["poll_error"] += 1
                    still.append(asset)
                    continue
                if entry["stage_prompt"] == STAGE_SUCCESS:
                    tally["success"] += 1
                    # 直链素材顺手探一次时长（与单条 /prompt-refresh 同口径；分享页探不出就留空）
                    if (
                        asset.duration is None
                        and asset.source_kind == SOURCE_LINK
                        and svc.looks_like_direct_url(asset.source_url)
                    ):
                        try:
                            probed = await _probe_url_duration(asset.source_url)
                            if probed is not None:
                                asset.duration = probed
                        except Exception:  # noqa: BLE001 — 探时长是搭车，别连累收敛
                            logger.info("反推收敛探直链时长失败 asset=%s", asset.code, exc_info=True)
                    continue
                if entry["stage_prompt"] == STAGE_FAILED:
                    fast = False
                    if task is not None:
                        try:
                            created = task.created_at
                            fast = (
                                datetime.utcnow() - created
                            ).total_seconds() <= fast_window if created else False
                        except Exception:  # noqa: BLE001
                            fast = False
                    if fast and str(asset.id) not in retried:
                        retried.add(str(asset.id))
                        tally["auto_retry"] += 1
                        try:
                            new_task = await _create_prompt_task_for_asset(
                                db, asset, operator=operator, tier=tier
                            )
                            asset.prompt_task_id = new_task.id
                            asset.prompt_max_duration = tier
                            retry_failed = new_task.status == PT_FAILED
                            svc.apply_stage(asset, "prompt", STAGE_FAILED if retry_failed else STAGE_RUNNING)
                            if not retry_failed:
                                asset.cost_prompt = round((asset.cost_prompt or 0) + svc.estimate_unit_cost(
                                    tier, need_upload=(asset.source_kind == SOURCE_FILE)
                                ), 4)
                                still.append(asset)
                            else:
                                tally["failed"] += 1
                            await _write_audit(
                                db,
                                action="asset.analyze.auto_retry",
                                operator=operator,
                                target_type="asset_item",
                                target_id=asset.id,
                                after={
                                    "asset_code": asset.code,
                                    "first_task_id": str(task.id),
                                    "first_error": (task.error or "")[:300],
                                    "retry_task_id": str(new_task.id),
                                    "retry_status": new_task.status,
                                    "tier": tier,
                                },
                            )
                        except Exception as exc:  # noqa: BLE001 — 重试失败按原失败落定
                            logger.exception("反推自动重试失败 asset=%s", asset.code)
                            tally["failed"] += 1
                            asset.note = ((asset.note or "") + f"\n自动重试也没提交上：{exc}")[:1000]
                        continue
                    tally["failed"] += 1
                    continue
                still.append(asset)
            await db.commit()
            pending = still
            if pending and time.monotonic() >= deadline:
                deadline_hit = True
                break
            if pending:
                await asyncio.sleep(poll)
    except Exception:  # noqa: BLE001 — 收敛循环炸了不能把已提交的活拖成无主，如实上报
        logger.exception("反推收敛循环异常（任务侧）")
        await db.rollback()
        raise
    tally["watched"] = len(todo)
    tally["left_running"] = len(pending)
    tally["deadline_hit"] = deadline_hit
    tally["seconds"] = round((datetime.utcnow() - started).total_seconds(), 1)
    return tally


@router.post("/assets/analyze/batch")
async def analyze_batch(
    data: AnalyzeRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """批量反推提示词：先给成本预估 + 余额闸门，通过才逐条提交智令 doc/120。

    确认单（A1-3）：只要**本批 ≥2 条**就必须带 `confirmed=true`（方案 §六.2 要的是
    「批量反推弹确认单」，不是"只有超预算才弹"）；单条不打扰。

    闸门三档（`asset_service.budget_gate`，按**批次累计**算，见 A1-4）：
    - ok            → 直接提交
    - need_approval → 批次累计超单批预算：必须 confirmed=true，且只有 admin 能确认
    - blocked       → 余额 < 累计预估×安全系数：一律拒绝，只有 admin 能 force=true 强推
                      （余额接口有波动，留一道逃生门，但责任在确认人身上）

    余额查不到／单位换算不到元 → 如实回 `balance_note` 说明闸门没生效，不假装有保障。

    已跑过的素材默认跳过（retry_failed=false），重试只针对 failed——
    每一环都是真金白银，整链重跑等于重复烧钱。
    """
    tier = _tier_or_400(data.max_duration)
    analyze_cap = _analyze_max_per_call()
    queue_batch_id, per_call, asset_ids = _queue_or_ids(data, analyze_cap, what="反推")

    queue: Optional[dict] = None
    if queue_batch_id:
        assets, remaining = await _batch_queue_assets(
            db,
            batch_id=queue_batch_id,
            stage="prompt",
            limit=per_call,
            offset=int(data.offset or 0),
            include_failed=bool(data.retry_failed),
        )
        queue = {
            "batch_id": queue_batch_id,
            "offset": int(data.offset or 0),
            "limit": per_call,
            "picked": len(assets),
            "remaining": remaining,
            "hint": "提交成功的条会自己离开队列，下一次仍用 offset=0；只有某条反复失败才用它跳过",
        }
    else:
        assets: List[AssetItem] = []
        for aid in asset_ids:
            assets.append(await _get_asset_or_404(db, aid))

    # 默认只跑「没跑过」的（pending/skipped）；retry_failed 才把 failed 再纳入；
    # running/success 任何情况下都不重复提交——反推按计时上限扣费，重跑就是重复烧钱。
    todo: List[AssetItem] = []
    skipped: List[dict] = []
    for a in assets:
        # 批 G：点名形态也要挡图片（整批形态已在 `_batch_queue_assets` 里过滤掉了）。
        # 放在 `stage_prompt` 判断**之前**：图片的阶段态是 skipped，按下面第一条规则
        # 它会被写成"反推已是 skipped"这种半句话，一线看不懂为什么。
        if a.media_kind == MEDIA_IMAGE:
            skipped.append({"code": a.code, "reason": _image_block_reason(a, "反推")})
            continue
        if a.stage_prompt in (STAGE_SUCCESS, STAGE_RUNNING):
            skipped.append({"code": a.code, "reason": f"反推已是 {a.stage_prompt}，不重复提交（重复＝重复扣费）"})
            continue
        if a.stage_prompt == STAGE_FAILED and not data.retry_failed:
            skipped.append({"code": a.code, "reason": "上次反推失败，需带 retry_failed=true 才重试"})
            continue
        todo.append(a)

    if not todo:
        if queue is None:
            # 11-06：这句话是「重试的机制也不清楚」投诉的一半源头——把它改成能照着做的指引
            n_run = sum(1 for a in assets if a.stage_prompt == STAGE_RUNNING)
            n_ok = sum(1 for a in assets if a.stage_prompt == STAGE_SUCCESS)
            n_fail = len(assets) - n_run - n_ok
            raise HTTPException(
                status_code=400,
                detail=(
                    f"所选 {len(assets)} 条里没有能新提交反推的："
                    f"在跑 {n_run} 条（后台任务会自己收，不用再点）、"
                    f"已成功 {n_ok} 条（不用再跑）、"
                    f"失败 {n_fail} 条（要重跑就勾上「重试失败项」再提交，重跑＝重新扣费）"
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"这批这一段没有可提交反推的素材（本段取 {queue['picked']} 条全被跳过，"
                f"队列剩余 {queue['remaining']} 条）。已提交在跑的等收敛即可，"
                "重复提交＝重复扣费"
            ),
        )

    # 11-06 拍板②：反推是真金白银的动作，替别人批次提交前先让人确认，确认后审计留痕
    crosses = await _cross_person_gate(
        db,
        operator=current_user,
        batch_ids=[a.batch_id for a in todo],
        action_label="反推提示词",
        confirmed=data.cross_person_confirm,
    )

    need_upload = any(a.source_kind == SOURCE_FILE for a in todo)
    estimate = svc.estimate_batch_cost(len(todo), max_duration=tier, need_upload=need_upload)
    balance_detail = await _query_zhiling_balance_detail()
    balance = balance_detail["balance"]

    # A1-4：闸门按**批次累计**算，不按单次。单次口径永远够不到上限——20 条封顶时
    # 20×0.334=6.68 元 < 50 元，那道「超单批预算要拆批/放批」的闸门是死的。
    batch_ids = {a.batch_id for a in todo if a.batch_id}
    cumulative_units = await _batch_pending_prompt_units(db, batch_ids=batch_ids, exclude_ids=[a.id for a in todo])
    # 同批未提交的兄弟条按**本次档位×本次单价**估：文件/链接单价差 0.001 元（中转费），
    # 这点误差在 50 元量级上可以接受，换掉一次全表逐条估算是值得的。
    cumulative_cost = round(estimate["unit_cost"] * (len(todo) + cumulative_units), 4)
    gate = svc.budget_gate(
        max(estimate["total_cost"], cumulative_cost),
        balance,
        batch_cap=settings.ASSET_BATCH_BUDGET_CAP,
        safety_ratio=settings.ASSET_BALANCE_SAFETY_RATIO,
    )
    if balance_detail["note"]:
        gate["note"] = f"{gate['note']}；{balance_detail['note']}" if gate.get("note") else balance_detail["note"]

    # A1-3：方案 §六.2 要求「批量反推必须弹确认单、用户确认才扣」，**不限 need_approval 档**。
    # 只有一条时不折腾人；≥2 条一律要 confirmed=true（否则把确认单数据回给前端）。
    if len(todo) >= 2 and not data.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ASSET_COST_CONFIRM_REQUIRED",
                "message": f"本批 {len(todo)} 条按 {tier} 秒档预估 {estimate['total_cost']} 元，须确认后提交",
                "estimate": estimate,
                "cumulative_cost": cumulative_cost,
                "balance": balance,
                "balance_note": balance_detail["note"],
                "gate": gate,
                "queue": queue,
                "hint": "确认单点「确认」后带 confirmed=true 重发（反推按计时上限扣费，选错档位白烧钱）",
            },
        )

    if not gate["allowed"]:
        if gate["level"] == "need_approval":
            is_admin = current_user.role == UserRole.admin.value
            if not (data.confirmed and is_admin):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "ASSET_BUDGET_NEED_APPROVAL",
                        "message": gate["reason"],
                        "estimate": estimate,
                        "cumulative_cost": cumulative_cost,
                        "balance": balance,
                        "hint": "本批累计超单批预算：拆批提交，或由管理员确认后带 confirmed=true 重发",
                    },
                )
        else:
            if not (data.force and current_user.role == UserRole.admin.value):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "ASSET_BALANCE_BLOCKED",
                        "message": gate["reason"],
                        "estimate": estimate,
                        "cumulative_cost": cumulative_cost,
                        "balance": balance,
                        "hint": "余额不足会跑一半卡死，已挡；充值后重试（admin 可用 force 强推）",
                    },
                )

    # 11-06：反推升级为正式后台任务（JOB_ANALYZE）。闸门与成本确认**必须**在排任务之前
    # 全过完——异步的任务号一发出智令就开始扣费，不能等后台跑起来才发现该拦。
    # params 里只把 wait_converge 置上（台账存的是**原请求体**，追溯口径与其他任务一致；
    # async_mode 由 `_run_asset_job` 重放时自己摘掉，这里不动它）。
    if data.async_mode:
        job = await _start_asset_job(
            db,
            kind=JOB_ANALYZE,
            data=data.model_copy(update={"wait_converge": True}),
            operator=current_user,
            batch_id=queue_batch_id,
            planned_units=len(todo),
            cross_person=crosses,
        )
        return _job_accepted(job, "反推文案")

    results: List[dict] = []
    # A1-2：下面**逐条 commit**，所以关掉 expire_on_commit —— 否则 commit 后对象全部失效，
    # 下一轮读 asset.source_kind 会触发惰性刷新，异步下直接 MissingGreenlet。
    db.sync_session.expire_on_commit = False
    for asset in todo:
        # 一条素材只留一行结果：先建好，异常/落库失败都改写这一行，前端按 asset_id 对得上
        entry = {
            "asset_id": str(asset.id),
            "code": asset.code,
            "prompt_task_id": None,
            "prompt_task_status": "failed",
            "error": None,
        }
        results.append(entry)
        try:
            # 提交动作抽成共用函数：后台快速失败自动重试走的是同一段（口径只有一套）
            task = await _create_prompt_task_for_asset(db, asset, operator=current_user, tier=tier)

            asset.prompt_task_id = task.id
            asset.prompt_max_duration = tier
            failed = task.status == PT_FAILED
            svc.apply_stage(asset, "prompt", STAGE_FAILED if failed else STAGE_RUNNING)
            if failed:
                asset.note = (asset.note or "")[:400] + f"\n反推提交失败：{task.error}"
            else:
                # 落的是按档位推算的额度（智令不逐单回传金额），供与账单对账
                asset.cost_prompt = round((asset.cost_prompt or 0) + svc.estimate_unit_cost(
                    tier, need_upload=(asset.source_kind == SOURCE_FILE)
                ), 4)
            entry["prompt_task_id"] = str(task.id)
            entry["prompt_task_status"] = task.status
            entry["error"] = task.error if failed else None
        except Exception as e:
            logger.exception("素材反推提交失败 asset=%s", asset.code)
            svc.apply_stage(asset, "prompt", STAGE_FAILED)
            asset.note = ((asset.note or "") + f"\n反推异常：{e}")[:1000]
            entry["error"] = str(e)[:300]
        # A1-2：**每条落库一次**。`create_prompt_task` 内部已把任务行与扣费 commit 了，
        # 素材状态却要到整循环跑完才落，中间崩溃＝「已扣费但素材仍 pending」，
        # 而 pending 会被下次重试再扣一遍；文件形态单条取回＋中转是分钟级 IO，窗口长达几十秒。
        try:
            await db.commit()
        except Exception as e:  # 单条落库失败不拖死整批，但必须如实报出来
            await db.rollback()
            logger.exception("素材反推状态落库失败 asset=%s", asset.code)
            entry["prompt_task_status"] = "persist_failed"
            entry["error"] = (
                "已提交但状态未落库，重试会重复扣费，请人工核对："
                if entry["prompt_task_id"]
                else "失败标记未落库（这条没扣费，重试安全），下批会再试："
            ) + str(e)[:200]

    # 批次成本：**由批内素材行重算，不做 +=**——+= 会把重试条目的历史值重复累加，
    # 对账页上就会出现"账单 3 元、系统 6 元"的虚高（智令不逐单回传金额，这里全是推算额度）。
    for bid in batch_ids:
        b = (await db.execute(select(AssetBatch).where(AssetBatch.id == bid))).scalar_one_or_none()
        if b is None:
            continue
        per_item = (
            await db.execute(
                select(AssetItem.prompt_max_duration, AssetItem.stage_prompt, AssetItem.cost_prompt)
                .where(AssetItem.batch_id == bid)
            )
        ).all()
        charged = round(sum((c or 0.0) for _, _, c in per_item), 4)
        planned = round(
            sum(
                svc.estimate_unit_cost(t or tier)
                for t, stage, _ in per_item
                if stage != STAGE_SUCCESS
            ),
            4,
        )
        b.prompt_max_duration = tier
        # cost_actual 实为「按档位累计的推算额度」，列名保留只为不丢历史；对账以它为准绳而非精确值
        b.cost_actual = charged
        b.cost_estimate = planned
        b.budget_gate = gate["level"]
        b.budget_note = (gate.get("reason") or gate.get("note"))[:500] if (gate.get("reason") or gate.get("note")) else None

    await _write_audit(
        db,
        action="asset.analyze_batch",
        operator=current_user,
        target_type="asset_batch",
        target_id=None,
        after={
            "tier": tier,
            "submitted": len(todo),
            "skipped": skipped,
            "estimate": estimate["total_cost"],
            "cumulative_cost": cumulative_cost,
            "balance": balance,
            "balance_note": balance_detail["note"],
            "gate": gate["level"],
            "confirmed": data.confirmed,
            "force": data.force,
            "cross_person": crosses or None,
        },
    )
    await db.commit()

    # 批 J：反推提交完，顺带把**还没在桶里的链接素材**排去下载原片（用户 11-05 口径：
    # 反推是常规动作，回看原片不该靠几小时就过期的时效直链）。放在所有 commit 之后——
    # 排程函数要自己 commit，且后台协程只读得到已提交的行。
    download_kick: Optional[dict] = None
    if data.download:
        dl_ids = [str(a.id) for a in todo if a.source_kind == SOURCE_LINK and not a.file_key]
        if dl_ids:
            download_kick = await _enqueue_download(
                db, asset_ids=dl_ids, operator=current_user,
                batch_id=str(next(iter(batch_ids))) if len(batch_ids) == 1 else None,
            )

    # 11-06：后台任务（JOB_ANALYZE 的重放）提交完**原地等收敛**——不再指望前端轮询，
    # 页面关了也一样收到终态、排上搭车下载。同步路径（脚本/行级重试）不等，行为不变。
    converge: Optional[dict] = None
    if data.wait_converge:
        converge = await _wait_prompt_convergence(db, todo, operator=current_user, tier=tier)
        await _write_audit(
            db,
            action="asset.analyze.converge",
            operator=current_user,
            target_type="asset_batch",
            target_id=None,
            after=converge,
        )
        await db.commit()

    return {
        "estimate": estimate,
        "cumulative_cost": cumulative_cost,
        "balance": balance,
        "balance_note": balance_detail["note"],
        "gate": gate,
        "results": results,
        "skipped": skipped,
        "queue": queue,
        "download": download_kick,
        "converge": converge,
        "message": f"已提交 {len(todo)} 条反推（档位 {tier}s，本批预估 {estimate['total_cost']} 元）"
        + (f"，同批未推 {cumulative_units} 条 → 批次累计 {cumulative_cost} 元" if cumulative_units else "")
        + (f"，跳过 {len(skipped)} 条已处理" if skipped else "")
        + (f"；队列还剩 {queue['remaining']} 条，下一次接着排" if queue and queue["remaining"] else "")
        + (
            f"；{download_kick['queued']} 条原片正在后台下载（完事列表上会显示下载标记）"
            if download_kick and download_kick["queued"] else ""
        )
        + (f"；{download_kick['note']}" if download_kick and download_kick.get("note") else "")
        + (
            f"；后台已收齐：成功 {converge['success']}、失败 {converge['failed']}"
            + (f"（自动重试过 {converge['auto_retry']} 条）" if converge["auto_retry"] else "")
            + (f"、{converge['left_running']} 条到点没等完（仍标在跑，可点「收取在跑结果」）"
               if converge.get("left_running") else "")
            if converge else ""
        ),
    }


@router.post("/assets/analyze/refresh-batch")
async def refresh_analyze_batch(
    data: RefreshBatchRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """一次收敛整批在跑的反推任务（A4-6：200 条不该发 200 次单条请求）。

    默认口径 `batch_id` → 只捞该批 **stage_prompt=running** 的行：终态（success/failed）
    智令侧不会自己变，重复轮询既白花一次外呼、又让「列表刷新」看着像卡死。
    `asset_ids` 是点名口（前端只勾了几条要复查时用）。

    收敛是**读操作、不扣费**，所以逐条 fail-soft：某条轮询网络抖动只回它自己的 error、
    保持 running 等下一轮，整批不连坐。串行跑（AsyncSession 非并发安全），
    单条智令 task-status 是毫秒级，20 条一轮没有可感等待。

    顺手修一个真会卡死的形态：`running` 但 `prompt_task_id` 为空／任务行不存在——
    那是提交瞬间进程中断留下的（A1-2 提过窗口），永远等不到收敛，这里判成 failed
    并写明"要重跑请带 retry_failed=true"，比让它一直挂在 running 上诚实。

    直链时长回写**不在这里做**（只有单条 `/{id}/prompt-refresh` 探）：一条最多挂 8 秒，
    20 条就是几分钟挤在一个 HTTP 请求里，那是 P1 Job 的活。
    """
    cap = _analyze_max_per_call()
    if data.batch_id and data.asset_ids:
        raise HTTPException(status_code=400, detail="batch_id 与 asset_ids 二选一：整批收敛，或点名复查")
    if not data.batch_id and not data.asset_ids:
        raise HTTPException(status_code=400, detail="请传 batch_id（整批）或 asset_ids（点名）")
    if data.asset_ids and len(data.asset_ids) > cap:
        raise HTTPException(status_code=400, detail=f"单次最多复查 {cap} 条，limit 上限同它")
    limit = int(data.limit or cap)
    if not 1 <= limit <= cap:
        raise HTTPException(status_code=400, detail=f"limit 请在 1~{cap} 之间（同步等外部接口，多了会超时）")

    remaining_running: Optional[int] = None
    if data.batch_id:
        conds = [
            AssetItem.batch_id == _as_uuid(data.batch_id, "batch_id"),
            AssetItem.stage_prompt == STAGE_RUNNING,
        ]
        total_running = (
            await db.execute(select(func.count()).select_from(AssetItem).where(and_(*conds)))
        ).scalar_one()
        assets = list(
            (
                await db.execute(
                    select(AssetItem)
                    .where(and_(*conds))
                    .order_by(AssetItem.created_at, AssetItem.code)
                    .limit(limit)
                )
            ).scalars().all()
        )
        remaining_running = max(0, total_running - len(assets))
    else:
        assets = [await _get_asset_or_404(db, aid) for aid in data.asset_ids]

    results: List[dict] = []
    tally = {"success": 0, "failed": 0, "running": 0, "stuck": 0, "poll_error": 0}
    for asset in assets:
        # 收敛核心与后台反推任务（JOB_ANALYZE）共用一个函数：两处口径分叉过一次就再没干净过
        entry, _task = await _converge_prompt_asset(db, asset)
        results.append(entry)
        if entry["error"] and entry["prompt_task_status"] is None and "轮询失败" in entry["error"]:
            tally["poll_error"] += 1
            continue
        if entry["stage_prompt"] == STAGE_SUCCESS:
            tally["success"] += 1
        elif entry["stage_prompt"] == STAGE_FAILED and entry["prompt_task_status"] is None:
            # 任务行缺失（提交后进程中断的残留），核心里已判 failed
            tally["stuck"] += 1
        elif entry["stage_prompt"] == STAGE_FAILED:
            tally["failed"] += 1
        else:
            tally["running"] += 1

    await _write_audit(
        db,
        action="asset.prompt_refresh_batch",
        operator=current_user,
        target_type="asset_batch" if data.batch_id else "asset_item",
        target_id=data.batch_id,
        after={"requested": len(assets), **tally, "limit": limit},
    )
    await db.commit()
    return {
        "results": results,
        "refreshed": len(assets),
        "tally": tally,
        "remaining_running": remaining_running,
        "message": (
            f"收敛 {len(assets)} 条：成功 {tally['success']}、失败 {tally['failed']}、"
            f"仍在跑 {tally['running']}"
            + (f"、缺任务行判失败 {tally['stuck']}" if tally["stuck"] else "")
            + (f"、轮询异常 {tally['poll_error']}" if tally["poll_error"] else "")
            + (
                f"；这批还有 {remaining_running} 条在跑，再点一次接着收"
                if remaining_running else ""
            )
        ),
    }


# ──────────────────────────────────────────────
# 钩子文案（详规 → 一句话/几句话候选）
# ──────────────────────────────────────────────
async def _drama_title_of(db: AsyncSession, asset: AssetItem) -> str:
    """给展开模板的「剧名全称」（模板第①行要写 `参考【《剧名》】剧情`）。

    优先级：挂接的剧目名 > 素材自带标题 > 空串。**取不到就传空**——模板里写死了
    「剧名只能由调用方给」，传空比让模型自己编一个剧名安全（编出来的名字会烧进
    每一条提示词，回收改名与剧目挂接全对不上）。
    """
    if asset.project_id:
        name = (
            await db.execute(select(Project.name).where(Project.id == asset.project_id))
        ).scalar_one_or_none()
        if name:
            return str(name).strip()
    return (asset.title or "").strip()



def _derive_asset_title_from_script(script: Optional[str]) -> Optional[str]:
    """反推详规 → 素材标题（≤24 字）。

    11-06 用户实测实锤：抽屉占位承诺「反推文案成功后才有标题」，但**没有任何代码写过
    asset.title**——链接素材反推成功后标题仍是空，审核台卡片只能靠 AS 号认素材。

    详规结构五花八门（「### 视频核心主题」小节 / 「视频拆解总结」整篇时间轴），所以是
    扫描式不是定位式：剥掉 markdown/时间轴/标签前缀后，找第一条「像标题」的行
    （≥8 字、不是小节头、不以冒号结尾）；「核心主题」小节内的行优先。取不到回 None
    （绝不硬编、绝不写 AS 号当标题）。
    """
    if not script:
        return None

    def _clean(t: str) -> str:
        t = t.strip().lstrip("#").replace("**", "").strip()
        # 时间轴前缀（00:00-00:03：）先剥——必须在数字剥离之前，否则行首 "00" 被当编号吃掉
        t = re.sub(r"^\d{1,2}:\d{2}(\s*[-–—]\s*\d{1,2}:\d{2})?[:：]?\s*", "", t)
        t = re.sub(r"^[\*\-\d\.\s]+", "", t).strip()
        t = re.sub(r"^(视频)?(核心)?主题[:：]\s*", "", t)
        return t.strip().strip("。；;，,")

    def _looks_like_title(t: str) -> bool:
        if len(t) < 8 or t.endswith(("：", ":", "—")):
            return False
        if re.match(r"^(视频|音频)?(拆解|概述|总结|内容分析)$", t):
            return False
        return True

    lines = [_clean(x) for x in script.splitlines()]
    # ①「核心主题」小节优先（从标记行到下一个标题行之间）
    focus: list[str] = []
    in_focus = False
    for raw in script.splitlines():
        stripped = raw.strip()
        if "核心主题" in stripped and ("#" in stripped or stripped.endswith(("：", ":")) or "**核心主题**" in stripped):
            in_focus = True
            # 行内直接带正文的情况（**核心主题**：讲述了……）
            inline = _clean(stripped.split("：", 1)[-1] if "：" in stripped else "")
            if _looks_like_title(inline):
                focus.append(inline)
            continue
        if in_focus and stripped.startswith("#"):
            break
        if in_focus:
            focus.append(_clean(stripped))
    def _cut24(t: str) -> Optional[str]:
        t = t[:24]
        # 24 字硬截会拦腰切词（「强势婆」）；24 字内有标点就落在标点上，且保底 ≥8 字
        for i in range(len(t) - 1, 7, -1):
            if t[i] in "，。、；：":
                return t[:i + 1].strip("，。、；：") or None
        return t or None

    for t in focus:
        if _looks_like_title(t):
            return _cut24(t)
    # ② 全文兜底
    for t in lines:
        if _looks_like_title(t):
            return _cut24(t)
    return None


def _backfill_title_on_prompt_success(asset: AssetItem, script: Optional[str]) -> bool:
    """反推成功收敛处统一调：title 还空着就自动起一个。返回是否写了。"""
    if (asset.title or "").strip():
        return False
    title = _derive_asset_title_from_script(script)
    if title:
        asset.title = title
        logger.info("素材 %s 反推成功自动起标题：%s", asset.code, title)
        return True
    return False


async def _prompt_script_of(db: AsyncSession, asset: AssetItem) -> Optional[str]:
    """取该素材的反推详规文本（wechat_dl_prompt_tasks.content）。

    跨 Base 只按 id 查、不建 relationship（建了会踩 mapper 未注册）。
    任务仍在 processing 时顺带轮询一次，省掉前端再来一轮。
    """
    if not asset.prompt_task_id:
        return None
    task = await get_prompt_task(db, asset.prompt_task_id)
    if task is None:
        return None
    task = await refresh_prompt_task(db, task)
    if task.status in (PT_SUCCESS, PT_FAILED):
        # 顺手把阶段态写回素材。原来只有 `/prompt-refresh` 会写，本函数把任务刷到终态后
        # `stage_prompt` 还停在 running → 列表上"永远在跑"，一线分不清谁卡住了。
        # 落库由调用方的 commit 带上（本函数被 review/produce/generate 复用，都在同一事务里）。
        svc.apply_stage(asset, "prompt", STAGE_SUCCESS if task.status == PT_SUCCESS else STAGE_FAILED)
        if task.status == PT_SUCCESS:
            _backfill_title_on_prompt_success(asset, task.content)
    if task.status != PT_SUCCESS:
        return None
    return (task.content or "").strip() or None


async def _linked_production_count(db: AsyncSession, summary_ids: List[Any]) -> int:
    """这些候选名下还挂着几张生产单（含已作废的）。"""
    ids = [s for s in summary_ids if s]
    if not ids:
        return 0
    return int(
        (
            await db.execute(
                select(func.count(AssetProduction.id)).where(AssetProduction.summary_id.in_(ids))
            )
        ).scalar_one()
    )


async def _assert_deletable_summaries(db: AsyncSession, summaries: List[AssetSummary]) -> Optional[str]:
    """删候选前的连坐检查：有生产单挂着就给出拒绝理由（None=可以删）。

    `AssetProduction.summary_id` 是 ON DELETE CASCADE —— 撤销审核后再重生成，若直接删
    候选会把生产单一起静默删掉，历史归零、对账无从下手（A2-2）。作废态同样算"挂着"，
    因为作废单仍是要留痕的交付依据。
    """
    total = await _linked_production_count(db, [s.id for s in summaries])
    if not total:
        return None
    return (
        f"这批候选已挂 {total} 张生产单，覆盖重生成会连坐删单、历史归零；"
        "请先处理生产单，或勾选不覆盖（新增候选）"
    )


async def _delete_summaries(
    db: AsyncSession, summaries: List[AssetSummary], *, operator: User
) -> None:
    """删候选并逐条留痕（A2-2：删除也是审核链上的一次改动，不能无声）。"""
    for s in summaries:
        await _write_audit(
            db,
            action="asset.summary.delete",
            operator=operator,
            target_type="asset_summary",
            target_id=s.id,
            before={"seq": s.seq, "audit_status": s.audit_status, "text": s.text},
            after={"deleted": True},
        )
        await db.delete(s)
    await db.flush()


async def _supersede_productions(
    db: AsyncSession, summary: AssetSummary, *, operator: User, reason: str
) -> int:
    """文案被撤销过审 → 它派生的**还没成功投出去**的生产单整批作废（A2-2 + R-5，11-04）。

    不作废的话：`/productions/export` 会把一张"审核已拒绝的文案"的单导出去投豆包，
    审的和产的就不是同一条了。已投递（queued/running/success）的不动——那些是既成事实，
    只能靠回收侧标记，不能假装没发生。

    R-5：`failed` 原来不在这个集合里，而 `failed → queued` 是允许的迁移（重投），
    queued 又在可交付集内 → **一张文案早已撤审的失败单，被当「失败重投」报一下就
    能导出投放**。按 D-4 拍板：失败单一并作废（与「撤审即作废派生单」同型）。
    代价是台账里那张失败单会变成作废旧单，一线找不到「我投过失败了的那条」——
    所以作废前后的状态进 AuditLog，`reason` 里带上撤审理由，要追随时查审计。
    """
    rows = (
        await db.execute(
            select(AssetProduction).where(
                AssetProduction.summary_id == summary.id,
                AssetProduction.status.in_([PR_ORDER_READY, PR_SKIPPED, PR_FAILED]),
            )
        )
    ).scalars().all()
    for p in rows:
        was = p.status
        p.status = PR_SUPERSEDED
        p.error = reason[:500]
        await _write_audit(
            db,
            action="asset.production.supersede",
            operator=operator,
            target_type="asset_production",
            target_id=p.id,
            before={"status": was},
            after={"status": PR_SUPERSEDED, "reason": reason},
        )
    return len(rows)


async def _call_autoclip(path: str, payload: dict, timeout: float = 900.0) -> dict:
    """调 autoclip 微服务（LLM 只在那边配了 key，后端进程不另起一套凭证）。

    超时为什么是 900 而不是原来拍的 180：出文案/展开是"浏览器点一下、同步等模型"的
    接口，11-04 在**同一条 1333 字反推详规**上实测（预览栈 assetprev-autoclip，
    max_tokens=32768）：mimo-v2.6-pro 96.2s、mimo-v2.6-flash 93.6s 正常回 3 条候选。
    看着 180 够用——但同一批请求里 flash 也**连续两次卡到 autoclip 自己的
    `API_TIMEOUT`（默认 240s）才超时**（容器日志 `curl (28) ... 240000ms`，第三次才成功）。
    网关卡流是常态事件，不是罕见事件（与 `cfdb2a8` 修的"反推查询抖动判死"同一类）。
    所以外层容忍必须**比 autoclip 单次上限还长**，否则就是"后端先 502、模型那边其实还在跑
    并最终成功"：钱照扣、候选没落库、一线看到"出文案失败"。
    口径**从内到外严格递增**（任何两层同值等于掷硬币，谁先到期看调度）：
    autoclip 单次 `API_TIMEOUT=600` < 本函数 900s < 浏览器 `MODEL_WAIT_TIMEOUT=960s`
    （frontend/src/api/assets.ts）< `frontend/nginx.conf` 的 1200s < 现网实际入口
    仓库根 `nginx.conf` 的 3600s。
    11-04 第二轮审核订正：这里原来写"nginx 900s > 本函数 900s"，一是同值本就有竞态，
    二是现网 163 的 `/api/` 由根 `nginx.conf` 直连 backend:8080、**根本不经过** frontend
    容器那份配置，写"同口径"是把预览栈的数当成生产数。

    11-04 批 C（D-1）之后这条链的适用面：出文案 / 投产的页面按钮改成 `async_mode=true`
    提交即回任务号，本函数在后台协程里跑，**上面那三层（960/1200/3600）不再夹它**，
    只剩 autoclip 600s < 本函数 900s 这一截。还受整条链约束的是反推（analyze）、
    收敛在跑结果（refresh-batch）、按需解析（resolve）和同步形态的出文案/投产（脚本、
    手工调用）——别因为"反正异步了"就把这里的 900 往下调。
    """
    url = f"{settings.AUTOCLIP_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json() or {}
    except httpx.HTTPStatusError as e:
        logger.error("autoclip %s 失败 %s: %s", path, e.response.status_code, e.response.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"文案服务调用失败（AutoClip {e.response.status_code}）：{e.response.text[:200]}",
        )
    except httpx.RequestError as e:
        logger.error("autoclip %s 连接失败: %s", path, e)
        raise HTTPException(status_code=502, detail=f"无法连接 AutoClip 服务：{e}")


# ──────────────────────────────────────────────
# 后台任务台账（D-1：出文案 / 投产「提交即回 + 轮询」）
# ──────────────────────────────────────────────

# asyncio 对 Task 只持**弱引用**：不留引用，正在跑的后台协程可能被 GC 掉，
# 台账却还挂着 running——看着像"卡在模型上"，其实是活早没了。跑完用回调摘掉。
_ASSET_JOB_TASKS: set = set()

# 非终态：重复提交守卫与「还在跑吗」都按这两个态判
JOB_OPEN_STATES = (JB_QUEUED, JB_RUNNING)
JOB_TERMINAL_STATES = (JB_SUCCEEDED, JB_FAILED, JB_INTERRUPTED)
# 轮询回给前端的白话状态（键是枚举，别改键）
ASSET_JOB_STATE_LABELS = {
    JB_QUEUED: "排队中",
    JB_RUNNING: "正在跑",
    JB_SUCCEEDED: "已完成",
    JB_FAILED: "失败",
    JB_INTERRUPTED: "已中断（服务重启，结果不可信）",
}

# 11-10 用户口径③「刚才投出去的那条生产单显示完成，成片墙还是看不到」：
# 「已完成」这三个字在台账里本来只说明**这一个动作**跑完了——投板跑完＝单挂上板，
# 片子还在豆包那边出（几十分钟）；开单跑完＝单建好，还没投板。一线把它读成
# "片儿到手了"完全合理，错的是我们只报了动作没报去向。所以每一种任务完成时都
# 必须带一句"做到了哪一步、下一步在哪看"（`done_note`），界面摆在完成提示里。
# 纯话术，不参与任何判定；改判定请回到各接口自己的闸门，别在这里加条件。
ASSET_JOB_DONE_NOTES = {
    JOB_ANALYZE: "反推只出稿：文案在「素材与文案」／审核台，这一步不产视频",
    JOB_SUMMARY_GENERATE: "钩子文案已出稿（还没建单、没投板）：去审核台看过审，再开单才轮到出片",
    JOB_PROMPT_PREVIEW: "提示词只是备好的预览：没建单、没投板、不占号池",
    JOB_PRODUCE: "生产单已建好，但还没投板（不占号也不出片）：在「生产单与投板」点「投去出片」才算投出去",
    JOB_DISPATCH: (
        "投板只是把单挂上豆包任务板：出片＋回库要几十分钟，"
        "回到「生产单与投板」看行上「成片」列——从「还没收片」变成「已收 N 段」才算到手，"
        "片子同时自动进「成片墙」"
    ),
    JOB_DOWNLOAD: "原片已下载入库：在素材详情里就地播，这一步不出成片",
    JOB_FRAMES: "抽帧完成：首帧摆在审核台卡片行与成片墙缩略图上",
}


def _job_endpoint(kind: str) -> Tuple[Any, Any, str]:
    """kind → (请求模型, 真正干活的接口函数, 白话名称)。

    后台任务**不另写一套业务逻辑**，就是把 `/summaries/generate`、`/produce`、
    `/productions/dispatch` 这些接口原样再调一次（自己开会话、自己收尾）。写两套必然分叉——
    审核/投产/导出三个入口刚刚才因为口径分叉被点名（R-6），这里绝不再造一个。
    """
    if kind == JOB_ANALYZE:
        # 11-06：反推正式进台账。跑的仍是 `/assets/analyze/batch` 这一个口（闸门/成本确认/
        # 逐条扣费全在里面），后台重放会原地等收敛＋快速失败自动重试——收敛口径和
        # 「收取在跑结果」按钮共用一个核心函数，不会出现"机器收的一套、人收的另一套"。
        return AnalyzeRequest, analyze_batch, "反推文案"
    if kind == JOB_SUMMARY_GENERATE:
        return SummaryGenerateRequest, generate_summaries, "出钩子文案"
    if kind == JOB_PRODUCE:
        return ProduceRequest, create_productions, "生成生产单"
    if kind == JOB_FRAMES:
        return FramesExtractRequest, extract_frames, "抽帧"
    if kind == JOB_DISPATCH:
        # 批 H：投板＝建任务＋轮询出片＋下载落桶，一段几十分钟的活。后台跑的仍然是
        # `/productions/dispatch` 这个口本身（confirm/闸门/审计全在里面），不另写一套——
        # 投递闸门要是分叉成"人点的严、机器排的松"，号池额度就会替我们发现这个 bug。
        return DispatchRequest, dispatch_productions, "投板"
    if kind == JOB_DOWNLOAD:
        # 批 J：下载原片。反推提交后自动排上（用户口径：反推默认顺带下载），
        # 失败条也能在列表上单独重试——跑的仍是 `/assets/download` 这一个口。
        return AssetDownloadRequest, download_asset_sources, "下载原片"
    if kind == JOB_PROMPT_PREVIEW:
        # 批 J：过审后顺手把豆包提示词展开一遍存起来。跑的仍是
        # `/summaries/preview-prompt`，与投产展开同一模型同一模板，不会出现
        # "预览一套、投产另一套"的分叉。
        return PromptPreviewRequest, preview_prompt_for_summaries, "备豆包提示词"
    raise HTTPException(
        status_code=400,
        detail=f"任务类型只支持 {'/'.join(ASSET_JOB_KINDS)}",
    )


def _job_scope_ids(kind: str, params: Dict[str, Any]) -> List[str]:
    """这次任务真正圈住的 id 列表（出文案＝素材 id，投产＝文案 id），用于防重复烧钱。"""
    if kind == JOB_FRAMES:
        # 抽帧同时圈素材和产物两类 id，防重复判据看的是"这批里有没有交集"，
        # 两类混在一个列表里比较不影响结论（UUID 不会撞）。
        p = params or {}
        return [
            str(x)
            for x in (list(p.get("asset_ids") or []) + list(p.get("output_ids") or []))
            if str(x)
        ]
    key = "asset_ids" if kind == JOB_SUMMARY_GENERATE else "summary_ids"
    if kind == JOB_DISPATCH:
        # 投板圈的是**生产单 id**：防重复判据因此天然是"同一张单没投过第二遍"，
        # 比按批次判更准（一个批次里可能只有 3 张单要投）。
        return [str(x) for x in ((params or {}).get("ids") or []) if str(x)]
    if kind == JOB_DOWNLOAD:
        # 批 J：下载圈的是素材 id（与出文案同一类），不复用默认分支的 summary_ids 键
        return [str(x) for x in ((params or {}).get("asset_ids") or []) if str(x)]
    if kind == JOB_ANALYZE:
        # 11-06：反推圈的是素材 id。整批排队形态没有 asset_ids → 走下面 batch_id 档判重
        return [str(x) for x in ((params or {}).get("asset_ids") or []) if str(x)]
    if kind == JOB_PROMPT_PREVIEW:
        # 批 J：备提示词圈的是文案 id（与投产同类）
        return [str(x) for x in ((params or {}).get("summary_ids") or []) if str(x)]
    return [str(x) for x in (params.get(key) or []) if str(x)]


def _twin_cost_phrase(kind: str) -> str:
    """重复提交烧的是**什么**——三类后台任务各不相同，别说成一句通用话。

    出文案／投产烧模型费用；投板一分钱模型费不花，烧的是**当天号池额度**（1023 那次
    叠两份量 → 115/120 成批 fail 就是这么来的）。写成"重复扣模型费用"会让一线以为
    投板重复提交只是多花几厘钱，而它的真实代价是"同一批里几十条额度白烧、还挤掉别人的量"。
    """
    if kind == JOB_DOWNLOAD:
        # 批 J：下载本身 0 元，但重下前要重新解析分享链接——落到付费渠道就是
        # 0.01 元/条的真金白银，外加桶里白占一份存储（桶不设过期）。
        return "重复下载既可能重复付解析费、又在桶里白占一份存储"
    if kind == JOB_PROMPT_PREVIEW:
        # 批 J：备提示词是真等一次模型（与投产展开同价），但已有预览的条会被幂等跳过，
        # 重复提交烧的只是"没有预览的那几条"的模型钱——照实说，别吓人也别装没事。
        return "重复扣模型费用（已有预览的条会自动跳过，不重复生成）"
    return "重复占当天号池额度" if kind == JOB_DISPATCH else "重复扣模型费用"


async def _assert_no_running_twin(
    db: AsyncSession, *, kind: str, params: Dict[str, Any], batch_id: Optional[str]
) -> None:
    """同一件事已经在跑就**不再起一份**——出文案/投产真花钱，投板真占号（批 H 起也有 twin 判据）。

    判据两档：按 id 列表提交的，比对 id 是否有交集；整批排队的（只有 batch_id），
    比对同批次同类型是否已有未结束的活。只回看 3 小时，免得一条历史卡死的活
    永远挡住新提交（那种情况该由 interrupted 收尾，见 lifespan 的启动清扫）。
    """
    label = _job_endpoint(kind)[2]
    since = datetime.utcnow() - timedelta(hours=3)
    conds = [AssetJob.kind == kind, AssetJob.status.in_(JOB_OPEN_STATES), AssetJob.created_at >= since]
    if batch_id:
        conds.append(AssetJob.batch_id == _as_uuid(batch_id, "batch_id"))
    rows = list((await db.execute(select(AssetJob).where(and_(*conds)))).scalars().all())
    if not rows:
        return
    ids = set(_job_scope_ids(kind, params))
    if not ids:
        # 整批排队：同批同类型有未结束的活就是重复点
        if batch_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"这批的「{label}」已经在后台跑着（任务 {rows[0].id}，"
                    f"{ASSET_JOB_STATE_LABELS.get(rows[0].status, rows[0].status)}），"
                    "请等它跑完或到任务台账里看进度，别再提交一次（重复＝重复花钱）"
                ),
            )
        return
    for job in rows:
        if ids & set(_job_scope_ids(job.kind, job.params or {})):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"选中的里有正在后台跑「{label}」的条目（任务 {job.id}，"
                    f"{ASSET_JOB_STATE_LABELS.get(job.status, job.status)}）。"
                    f"同一批重复提交＝{_twin_cost_phrase(kind)}，请等它结束或换别的条目"
                ),
            )


async def _start_asset_job(
    db: AsyncSession,
    *,
    kind: str,
    data: BaseModel,
    operator: User,
    batch_id: Optional[str],
    planned_units: Optional[int],
    cross_person: Optional[List[dict]] = None,
) -> AssetJob:
    """落一行 queued 台账并排上后台协程。

    ⚠️ 必须先 `commit` 再调度：后台协程用的是**另一个会话**，读不到本会话未提交的行；
    反过来也不能等本会话的 response 结束——那正是本口要避免的"人得干等着"。
    `cross_person`（11-06 拍板②）：跨人批次闸门确认后的清单，原样进 submit 审计，
    让「发起人≠批次主人」这件事在台账动作里也查得到。
    """
    params = data.model_dump(mode="json")
    await _assert_no_running_twin(db, kind=kind, params=params, batch_id=batch_id)
    job = AssetJob(
        kind=kind,
        status=JB_QUEUED,
        batch_id=_as_uuid(batch_id, "batch_id") if batch_id else None,
        params=params,
        planned_units=planned_units,
        created_by=operator.id,
    )
    db.add(job)
    await db.flush()
    await _write_audit(
        db,
        action=f"asset.job.{kind}.submit",
        operator=operator,
        target_type="asset_job",
        target_id=job.id,
        after={
            "batch_id": batch_id,
            "planned_units": planned_units,
            "params": params,
            "cross_person": cross_person or None,
        },
    )
    await db.commit()
    _schedule_asset_job(str(job.id), kind, params, str(operator.id))
    return job


def _schedule_asset_job(job_id: str, kind: str, params: Dict[str, Any], operator_id: str) -> None:
    task = asyncio.create_task(_run_asset_job(job_id, kind, params, operator_id))
    _ASSET_JOB_TASKS.add(task)
    task.add_done_callback(_ASSET_JOB_TASKS.discard)


async def _finish_asset_job(job_id: str, status: str, result: Optional[dict], error: Optional[str]) -> None:
    """终态回写用**新会话**：跑业务那个会话可能已经带着异常事务回滚过，不能再指望它。"""
    async with _database.async_session_factory() as db:
        job = await db.get(AssetJob, uuid.UUID(job_id))
        if job is None:
            return
        job.status = status
        job.result = result
        job.error = (error or None) and str(error)[:1000]
        job.finished_at = datetime.utcnow()
        await db.commit()


async def _run_asset_job(job_id: str, kind: str, params: Dict[str, Any], operator_id: str) -> None:
    """后台把接口原样跑一遍，整份响应进台账。

    这里**故意不做业务判断**：闸门、成本确认、钩子编号、复核全在被包住的那个口里。
    失败分两类：`HTTPException`＝接口自己拒的（参数不对/闸门没过），照实把 detail 存进
    error 让一线看到原话；其它异常＝编排炸了（连不上库等），记异常类型 + 日志堆栈。
    """
    model_cls, endpoint, _ = _job_endpoint(kind)
    uid = uuid.UUID(job_id)
    # ⚠️ 必须摘掉 async_mode：后台任务就是把同一个接口再调一遍，留着 true 会
    # 再起一份任务、再摘一次……无限套娃，台账里全是自己抄自己的活。
    params = {**params, "async_mode": False}
    # 终态在会话**关闭之后**再写：中途另开会话改 asset_jobs 那一行，跑业务的会话还
    # 挂着未提交事务（异常路径尤其如此），两个会话抢同一条连接在 sqlite 测试里就是死锁。
    outcome: Optional[Tuple[str, Optional[dict], Optional[str]]] = None
    async with _database.async_session_factory() as db:
        job = await db.get(AssetJob, uid)
        if job is None or job.status not in JOB_OPEN_STATES:
            # 进程重启的清扫已经把它判成 interrupted，别再假装还在跑
            return
        operator = await db.get(User, uuid.UUID(operator_id))
        if operator is None:
            outcome = (JB_FAILED, None, "提交人已不存在，任务没执行")
        else:
            job.status = JB_RUNNING
            job.started_at = datetime.utcnow()
            await db.commit()
            try:
                result = await endpoint(model_cls(**params), operator, db)
                outcome_detail = None
                result_dict = result if isinstance(result, dict) else {"raw": result}
                outcome_status = JB_SUCCEEDED
                # 抽帧的「接口成功」≠「抽到了」：全败时任务记 FAILED，别让台账绿着骗人
                if kind == JOB_FRAMES and isinstance(result_dict, dict):
                    rows = result_dict.get("results") or []
                    n_fail = sum(1 for r in rows if r.get("result") == "failed")
                    n_ok = sum(1 for r in rows if r.get("result") == "extracted")
                    if rows and n_ok == 0 and n_fail > 0:
                        outcome_status = JB_FAILED
                        outcome_detail = f"抽帧 {n_fail} 条全部失败（无一条成功）：详见 results 与 worker 日志"
                        logger.warning("素材库后台任务 %s(frames) 全败：%s", job_id, outcome_detail)
                # 反推的「接口成功」≠「收到结果」：后台等完收敛后一条都没成、还都是终态失败
                # （含自动重试仍失败）→ 任务记 FAILED，别让台账绿着让人以为文案马上就有
                if kind == JOB_ANALYZE and isinstance(result_dict, dict):
                    conv = result_dict.get("converge") or {}
                    n_ok = int(conv.get("success") or 0)
                    n_fail = int(conv.get("failed") or 0)
                    if (n_ok + n_fail) > 0 and n_ok == 0 and not conv.get("deadline_hit"):
                        outcome_status = JB_FAILED
                        outcome_detail = (
                            f"反推 {n_fail} 条全部失败（含自动重试仍失败）：逐条原因看素材列表的失败标记"
                        )
                        logger.warning("素材库后台任务 %s(analyze) 全败：%s", job_id, outcome_detail)
                outcome = (outcome_status, result_dict, outcome_detail)
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)[:900]
                logger.warning("素材库后台任务 %s(%s) 被接口拒绝：%s", job_id, kind, detail)
                await db.rollback()
                outcome = (JB_FAILED, None, f"HTTP {exc.status_code}：{detail}")
            except Exception as exc:  # noqa: BLE001 — 后台任务的兜底，绝不能把异常抛回事件循环
                logger.exception("素材库后台任务 %s(%s) 异常", job_id, kind)
                await db.rollback()
                outcome = (JB_FAILED, None, f"{type(exc).__name__}: {exc}"[:900])
    await _finish_asset_job(job_id, outcome[0], outcome[1], outcome[2])


async def _job_progress(db: AsyncSession, job: AssetJob) -> Dict[str, Any]:
    """进度按台账**现算**（协程不回报中间态，所以口径只能是"数结果"）。

    - 出文案：圈住的素材里 `stage_summary` 已收敛（成功/失败）的条数。
      ⚠️ 这条口径会把**上一次就跑好的**也算进去，所以它回答的是"还欠几条"，
      不是"这次跑了几条"——文案不齐时看列表页的逐条阶段标签更准。
    - 投产：圈住的文案里在本次开跑（started_at）之后**真长出过生产单**的条数。
    """
    total = job.planned_units
    done: Optional[int] = None
    note = "进度按台账现算；逐条状态看素材列表/生产单列表"
    ids = _job_scope_ids(job.kind, job.params or {})
    if job.kind in (JOB_SUMMARY_GENERATE, JOB_ANALYZE):
        stage_col = AssetItem.stage_summary if job.kind == JOB_SUMMARY_GENERATE else AssetItem.stage_prompt
        conds = []
        if ids:
            conds.append(AssetItem.id.in_([uuid.UUID(x) for x in ids]))
        elif job.batch_id:
            conds.append(AssetItem.batch_id == job.batch_id)
        if conds:
            total = total or len(ids)
            done = int(
                (
                    await db.execute(
                        select(func.count(AssetItem.id)).where(
                            and_(*conds, stage_col.in_((STAGE_SUCCESS, STAGE_FAILED)))
                        )
                    )
                ).scalar()
                or 0
            )
            if job.batch_id and not ids:
                note = "整批排队：进度＝本批已出完文案的条数（含上次就跑好的），剩余条数看队列" if job.kind == JOB_SUMMARY_GENERATE else "整批排队：进度＝本批已收完反推的条数（含上次就跑好的），剩余条数看队列"
    elif job.kind == JOB_PRODUCE and ids and job.started_at:
        done = int(
            (
                await db.execute(
                    select(func.count(func.distinct(AssetProduction.summary_id))).where(
                        AssetProduction.summary_id.in_([uuid.UUID(x) for x in ids]),
                        AssetProduction.created_at >= job.started_at,
                    )
                )
            ).scalar()
            or 0
        )
        total = total or len(ids)
        note = "投产进度＝已经长出生产单的文案条数（本批开跑之后新建的才算）"
    elif job.kind == JOB_FRAMES:
        p = job.params or {}
        aids = [str(x) for x in (p.get("asset_ids") or []) if str(x)]
        oids = [str(x) for x in (p.get("output_ids") or []) if str(x)]
        conds = []
        if aids:
            conds.append(AssetFrame.asset_id.in_([uuid.UUID(x) for x in aids]))
        if oids:
            conds.append(AssetFrame.output_id.in_([uuid.UUID(x) for x in oids]))
        if conds:
            done = int(
                (
                    await db.execute(
                        select(func.count(AssetFrame.id)).where(or_(*conds))
                    )
                ).scalar()
                or 0
            )
        total = total or (len(aids) + len(oids))
        note = "抽帧进度＝已落库的**帧数**（一条素材满帧是 4 张：3 单帧＋1 九宫格），不是完成的条数"
    elif job.kind == JOB_DOWNLOAD and ids:
        done = int(
            (
                await db.execute(
                    select(func.count(AssetItem.id)).where(
                        AssetItem.id.in_([uuid.UUID(x) for x in ids]),
                        AssetItem.download_status == "success",
                    )
                )
            ).scalar()
            or 0
        )
        total = total or len(ids)
        # 下载逐条落库，success 是可靠的"到手"口径；失败条的原因在任务结果逐条明细里
        note = "下载进度＝原片已落到自有桶的条数；失败的条看任务结果里的逐条原因，可单独重试"
    elif job.kind == JOB_PROMPT_PREVIEW and ids:
        done = int(
            (
                await db.execute(
                    select(func.count(AssetSummary.id)).where(
                        AssetSummary.id.in_([uuid.UUID(x) for x in ids]),
                        AssetSummary.prompt_preview.isnot(None),
                    )
                )
            ).scalar()
            or 0
        )
        total = total or len(ids)
        # 预览失败不拦投产（投产时重新展开），所以进度话术要先把这句话说在前头
        note = "备提示词进度＝预览已生成的文案条数；没生成出来的投产时会重新展开，不拦投产"
    elif job.kind == JOB_DISPATCH and ids:
        pids = []
        for x in ids:
            try:
                pids.append(uuid.UUID(str(x)))
            except (ValueError, TypeError):
                continue  # 脏 id 不参与现算，别让它把整条进度查询炸掉
        if pids:
            done = int(
                (
                    await db.execute(
                        select(func.count(AssetProduction.id)).where(
                            AssetProduction.id.in_(pids),
                            AssetProduction.status.in_((PR_SUCCESS, PR_FAILED)),
                        )
                    )
                ).scalar()
                or 0
            )
        total = total or len(pids)
        # 为什么只数终态：投板一条要等板子出片（几十分钟），"done"如果按"已经 POST 过"算，
        # 前端会在一半进度时就以为完事了；按终态算才是"到手了几条"。
        note = "投板进度＝已落到终态（成片到手/判失败）的张数，还在板上出片的不算完成；逐张看生产单列表"
    return {"total": total, "done": done, "note": note}


def _serialize_job(job: AssetJob, progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "kind_label": _job_kind_label(job.kind),
        "status": job.status,
        "status_label": ASSET_JOB_STATE_LABELS.get(job.status, job.status),
        # 「已完成」必须说清完成了什么、下一步在哪看（11-10 口径③）：只在成功终态给，
        # 失败／中断的成因走 `error`，两套话术不混
        "done_note": ASSET_JOB_DONE_NOTES.get(job.kind) if job.status == JB_SUCCEEDED else None,
        "running": job.status in JOB_OPEN_STATES,
        "batch_id": str(job.batch_id) if job.batch_id else None,
        "planned_units": job.planned_units,
        "progress": progress,
        "params": job.params,
        "error": job.error,
        # 结果只在终态回；跑一半时前端不该看到半份清单（会让人以为已经完事）
        "result": job.result if job.status in JOB_TERMINAL_STATES else None,
        "created_at": utc_iso(job.created_at),
        "started_at": utc_iso(job.started_at),
        "finished_at": utc_iso(job.finished_at),
    }


def _job_kind_label(kind: str) -> str:
    try:
        return _job_endpoint(kind)[2]
    except HTTPException:
        return kind


def _job_accepted(job: AssetJob, label: str) -> Dict[str, Any]:
    """`async_mode` 的统一回执：立即返回任务号，结果靠轮询取。

    故意**不**沿用同步接口的响应形状——同步返回 `{results:[...]}`，异步返回
    `{job_id, queued:true}`，前端拿到哪个就知道自己该等还是该刷新列表，
    不会出现"看到 results 是空的以为没素材"这种误读。
    """
    return {
        "job_id": str(job.id),
        "status": job.status,
        "status_label": ASSET_JOB_STATE_LABELS.get(job.status, job.status),
        "queued": True,
        "planned_units": job.planned_units,
        "poll_url": f"/api/assets/jobs/{job.id}",
        "list_url": "/api/assets/jobs?only_open=true",
        "message": (
            f"「{label}」已排到后台（本次 {job.planned_units or 0} 条），不用守着页面等；"
            "跑完会在任务台账里留下整份结果，中途关页面也不影响"
        ),
    }


async def sweep_interrupted_asset_jobs() -> int:
    """启动清扫：进程重启前挂在半路的任务一律判「已中断」。

    为什么必须由启动来做：后台协程活在**进程内存**里，`--workers 1` 重启即全没，
    台账却还挂着 queued/running——一线看到"正在跑"就一直等，等一个永远不会来的结果。
    判 interrupted 而不是失败：这不是业务失败（模型没拒绝、闸门没过），是**我们没跑完**，
    结果不可信，绝不能让前端把这种任务的 result 当数据用。

    例外（11-06 P2）：`kind=frames` 的任务**原行重排**不判死——抽帧免费、幂等
    （已有帧默认跳过，force 才重抽），重启把它打死纯属运气不好；判成 interrupted
    反而留下"要人手工补"的假终态。做法：状态拨回 queued、清 error/finished_at，
    commit 后按原 params 重新调度（`_run_asset_job` 自己会摘掉 async_mode 防套娃，
    params 里的原请求体就是重放口径）。提交人已删的 frames 任务还是判 interrupted，
    否则会在后台空转一圈记 failed，一线更看不懂。返回值只数**判死**的，重排的不算。
    """
    requeue: List[Tuple[str, str, Dict[str, Any], str]] = []
    async with _database.async_session_factory() as db:
        rows = list(
            (
                await db.execute(select(AssetJob).where(AssetJob.status.in_(JOB_OPEN_STATES)))
            ).scalars().all()
        )
        for job in rows:
            if job.kind == JOB_FRAMES and job.created_by is not None:
                # 属性要在 commit 前取走：session 默认 expire_on_commit，分离后读属性会炸
                requeue.append((str(job.id), job.kind, dict(job.params or {}), str(job.created_by)))
                job.status = JB_QUEUED
                job.error = None
                job.finished_at = None
                continue
            job.status = JB_INTERRUPTED
            job.error = "服务重启，任务没能跑完，结果不可信——需要重做请重新提交"
            job.finished_at = datetime.utcnow()
        await db.commit()
        if rows:
            logger.warning(
                "素材库启动清扫：%d 个在跑/排队的后台任务已标记中断（frames 原行重排 %d 个）",
                len(rows) - len(requeue), len(requeue),
            )
    for job_id, kind, params, operator_id in requeue:
        _schedule_asset_job(job_id, kind, params, operator_id)
    return len(rows) - len(requeue)


@router.get("/assets/jobs")
async def list_asset_jobs(
    status: Optional[str] = None,
    kind: Optional[str] = None,
    batch_id: Optional[str] = None,
    only_open: bool = False,
    include_frames: bool = False,
    limit: int = 20,
    current_user: User = Depends(require_roles(*_PROD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """任务台账列表：页面刷新后、换浏览器后，靠这个口找回"我刚才点的那批还在不在跑"。

    11-04 批 F 起**默认不列抽帧任务**（`include_frames=true` 才给）：抽帧是导入成功后
    系统自己排的，人人都有一堆，混进列表会把「我刚点的那批还在不在跑」挤出视野——
    这个口的用途本来就是找回人手点的那件慢活。
    """
    limit = min(max(1, int(limit or 20)), 100)
    conds: List[Any] = []
    if kind:
        if kind not in ASSET_JOB_KINDS:
            raise HTTPException(status_code=400, detail=f"kind 只支持 {'/'.join(ASSET_JOB_KINDS)}")
        conds.append(AssetJob.kind == kind)
    elif not include_frames:
        conds.append(AssetJob.kind != JOB_FRAMES)
    if only_open:
        conds.append(AssetJob.status.in_(JOB_OPEN_STATES))
    elif status:
        conds.append(AssetJob.status == status)
    if batch_id:
        conds.append(AssetJob.batch_id == _as_uuid(batch_id, "batch_id"))
    stmt = (
        select(AssetJob).order_by(AssetJob.created_at.desc()).limit(limit)
        if not conds
        else select(AssetJob).where(and_(*conds)).order_by(AssetJob.created_at.desc()).limit(limit)
    )
    jobs = list((await db.execute(stmt)).scalars().all())
    return {
        "items": [_serialize_job(j) for j in jobs],
        "note": "进度是现算的粗口径；逐条成败看 result.results 或列表页的阶段标签",
    }


@router.get("/assets/jobs/{job_id}")
async def get_asset_job(
    job_id: str,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """轮询单个后台任务：`running` 就继续等，终态时 `result` 里是整份接口响应。"""
    job = await db.get(AssetJob, _as_uuid(job_id, "job_id"))
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在（台账只留最近的，超期的看审计日志 asset.job.*）")
    return _serialize_job(job, await _job_progress(db, job))


@router.post("/assets/summaries/generate")
async def generate_summaries(
    data: SummaryGenerateRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """批量出钩子文案候选（默认 3 条：疑问式/陈述式/台词摘录式，模型标注推荐条）。

    前置是反推已成功——详规都没有就编文案，等于把「反推失败」洗成「像模像样的幻觉」，
    所以这里硬要求有 content，且生成后跑一致性校验（实体要在详规里命中）。
    """
    summary_cap = _summary_max_per_call()
    queue_batch_id, per_call, asset_ids = _queue_or_ids(data, summary_cap, what="出文案")

    queue: Optional[dict] = None
    picked: List[AssetItem] = []
    if queue_batch_id:
        picked, remaining = await _batch_queue_assets(
            db,
            batch_id=queue_batch_id,
            stage="summary",
            limit=per_call,
            offset=int(data.offset or 0),
            require_prompt_success=True,
            include_failed=bool(data.retry_failed),
        )
        queue = {
            "batch_id": queue_batch_id,
            "offset": int(data.offset or 0),
            "limit": per_call,
            "picked": len(picked),
            "remaining": remaining,
            "hint": "只排「反推已成功、本条还没出文案」的；出完的自动离开队列，offset 平时留 0",
        }
        if not picked:
            raise HTTPException(
                status_code=400,
                detail=f"这批这一段没有待出文案的素材（队列剩余 {remaining} 条）",
            )
    count = int(settings.ASSET_HOOK_CANDIDATE_COUNT if data.count is None else data.count)
    if not 1 <= count <= 6:
        raise HTTPException(status_code=400, detail="候选数只支持 1~6 条")

    # 11-06 拍板②：跨人批次闸门要放在**排任务之前**——异步的任务号一发出模型就开始烧钱，
    # 不能等后台跑起来才发现该拦。点名形态此时素材还没读，先读一遍（同步档下面会再读，
    # 同一事务里同主键拿回同一对象，不浪费）。
    gate_assets = picked if queue_batch_id else [await _get_asset_or_404(db, aid) for aid in asset_ids]
    crosses = await _cross_person_gate(
        db,
        operator=current_user,
        batch_ids=[a.batch_id for a in gate_assets],
        action_label="出钩子文案",
        confirmed=data.cross_person_confirm,
    )

    if data.async_mode:
        job = await _start_asset_job(
            db,
            kind=JOB_SUMMARY_GENERATE,
            data=data,
            operator=current_user,
            batch_id=queue_batch_id,
            planned_units=(len(picked) if queue is not None else len(asset_ids)),
            cross_person=crosses,
        )
        return _job_accepted(job, "出钩子文案")

    # 词表整批读一次（带 TTL 缓存）：候选落库时就要把命中连同级别写进 risk_hit
    book, exemptions = await _risk_lexicon(db)

    results: List[dict] = []
    targets: List[Tuple[AssetItem, Optional[str]]] = []
    if queue is not None:
        for asset in picked:
            targets.append((asset, await _prompt_script_of(db, asset)))
    else:
        for aid in asset_ids:
            asset = await _get_asset_or_404(db, aid)
            targets.append((asset, await _prompt_script_of(db, asset)))
    # 11-06 双产出：本批新落库的候选收集起来，等主循环收尾提交后再统一调
    # hook-copy/prompt-web 生成豆包网页版提示词（第二跳）。收集在循环里、
    # 调用在提交后——外部模型调用前事务必须干净（idle_in_transaction 60s 掐连接）。
    web_jobs: List[dict] = []
    new_copy_rows: List[AssetSummary] = []  # 11-09 批 O：整批新出的候选，出料后一次性自动预取号
    for asset, script in targets:
        aid = str(asset.id)
        # 批 G：图片没有详规、也不该有 —— 出文案要读 doc/120 的脚本，喂一张 jpg 进去
        # 只会拿回一条"脚本尚未就绪"，让人以为反推坏了。这里直接说清它是图片。
        if asset.media_kind == MEDIA_IMAGE:
            results.append({
                "asset_id": aid, "code": asset.code, "created": 0,
                "error": _image_block_reason(asset, "出文案"),
            })
            continue
        if not script:
            results.append({
                "asset_id": str(asset.id), "code": asset.code, "created": 0,
                "error": "反推脚本尚未就绪，先跑反推再出文案",
            })
            continue

        existing = list(
            (
                await db.execute(
                    select(AssetSummary).where(AssetSummary.asset_id == asset.id).order_by(AssetSummary.seq)
                )
            ).scalars().all()
        )
        # 要删的旧候选先记下来，**等新候选真到手之后**再删（见下方 to_delete）。
        # 旧写法在调模型之前就删，而调模型之前必须 commit 结束事务（见下），
        # 于是「模型挂了」会变成「旧文案已经没了、新文案也没来」。
        to_delete: List[AssetSummary] = []
        if existing and not data.overwrite:
            # 只补差额，已审过的候选不动（历史留痕是抽检的依据）
            if len(existing) >= count or any(s.audit_status != RV_PENDING for s in existing):
                results.append({
                    "asset_id": str(asset.id), "code": asset.code,
                    "created": 0, "kept": len(existing),
                    "note": "已有候选（含已审条目），覆盖重出请在列表勾选后点「出钩子文案」、确认框里选「覆盖重出」（已过审的必须先撤审）",
                })
                continue
            blocked = await _assert_deletable_summaries(db, existing)
            if blocked:
                results.append({"asset_id": str(asset.id), "code": asset.code, "created": 0, "error": blocked})
                continue
            to_delete = list(existing)
            existing = []
        elif existing and data.overwrite:
            approved = [s for s in existing if s.audit_status in REVIEW_PASSED_STATES]
            if approved:
                # 过审文案已经挂生产单了，删掉会让 production 的 summary 外键悬空
                results.append({
                    "asset_id": str(asset.id), "code": asset.code, "created": 0,
                    "error": f"存在 {len(approved)} 条已过审文案，不能覆盖重生成（请先撤销审核）",
                })
                continue
            blocked = await _assert_deletable_summaries(db, existing)
            if blocked:
                results.append({"asset_id": str(asset.id), "code": asset.code, "created": 0, "error": blocked})
                continue
            to_delete = list(existing)
            existing = []

        svc.apply_stage(asset, "summary", STAGE_RUNNING)

        payload = {
            "script": script,
            "count": count,
            # 内部重试压到 1 次：autoclip 每次网关调用最长 `API_TIMEOUT`（建议配 600s），
            # 默认 3 次＝最坏 12 分钟，外层（本函数 900s、nginx 900s）必然先崩，
            # 崩了里面还在烧钱重试。宁可这一次干净地失败（旧候选保留、这条标 failed、
            # 一线点重试），也不要内外两套超时互相抢。
            "max_retries": 1,
            "params": {
                "title": asset.title or "",
                "platform": asset.platform or "",
                "extra_requirements": data.extra_requirements or "",
                "compliance": "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
                # 2026-11-07 用户口径：第 1 条候选要贴合原片长度（10s/15s 取最接近档）。
                # 时长在各导入/解析路已有落库（文件导入 ffprobe、链接解析后回填）；
                # 拿不到就不带，autoclip 侧退回原「按文案丰满程度」判断。
                **({"duration_seconds": int(round(asset.duration))} if asset.duration else {}),
            },
        }
        # ⚠️ 调外部模型之前必须**结束事务**，flush 不够（还在同一个事务里）：
        # PG 侧 idle_in_transaction_session_timeout=60s（app/database.py
        # ::_enforce_idle_in_transaction_timeout，Issue #219 为防事务泄漏加的防御层）
        # 会在「SELECT 完就趴着等 HTTP」满 60 秒时**直接把连接掐掉**。
        # 11-03 预览栈真链路实测：mimo 出 4 条候选花了 9 分钟，回来后 INSERT 报
        #   asyncpg InterfaceError: connection is closed → 整口 500、候选一条没落库。
        # 此刻事务里只有 stage 标记（旧候选的删除已挪到模型返回之后），commit 掉
        # 正好让列表先显示「生成中」，比整批 500 干净。
        await db.commit()

        try:
            result = await _call_autoclip("hook-copy/generate", payload)
        except HTTPException as exc:
            # 单条失败只标这一条：抬 500 会让同批**已经出到候选**的素材一起回滚，
            # 而那些模型调用是真花了钱的。
            svc.apply_stage(asset, "summary", STAGE_FAILED)
            asset.note = ((asset.note or "") + f"\n出文案失败：{str(exc.detail)[:300]}")[:1000]
            await db.commit()
            results.append({
                "asset_id": str(asset.id), "code": asset.code, "created": 0,
                "error": str(exc.detail)[:300],
            })
            continue
        candidates = result.get("candidates") or []
        if not isinstance(candidates, list) or not candidates:
            svc.apply_stage(asset, "summary", STAGE_FAILED)
            asset.note = ((asset.note or "") + "\n文案服务未返回候选")[:1000]
            results.append({
                "asset_id": str(asset.id), "code": asset.code, "created": 0,
                "error": "文案服务未返回候选",
            })
            continue

        # 2026-11-07 用户口径：出文案同步产「浓缩标题」（6~14 字），直接当素材名称——
        # 反推扫描出的标题不够浓缩，拿不到标题的素材在列表里更是只剩 AS 号看不懂
        # （陈天强那批就是这样）。给了就覆盖（原链接信息在 source_url 不丢）；
        # 没给或长度不像标题就维持原状，绝不硬写。
        gen_title = str((result or {}).get("title") or "").strip()
        if 2 <= len(gen_title) <= 30:
            asset.title = gen_title
            logger.info("素材 %s 出文案同步起浓缩标题：%s", asset.code, gen_title)

        # 旧候选现在才真删：新候选已经在手，删了不会落空。与下面的 INSERT 同批提交，
        # 中途任何异常仍然整体回滚，旧文案原样留着。
        if to_delete:
            await _delete_summaries(db, to_delete, operator=current_user)

        seq = len(existing)
        created = 0
        created_rows: List[AssetSummary] = []
        for cand in candidates[:count]:
            text = str((cand or {}).get("text") or "").strip()
            if not text:
                continue
            seq += 1
            shape = svc.check_copy_shape(text)
            risk = svc.scan_risk(text, lexicon=book, exemptions=exemptions)
            consist = svc.check_consistency(text, script)
            summary = AssetSummary(
                asset_id=asset.id,
                seq=seq,
                text=text,
                style_tag=str(cand.get("style_tag") or "")[:20] or None,
                formula_tag=str(cand.get("formula_tag") or "")[:60] or None,
                # 11-04 拍板①：文案默认**继承所属素材的原型**（审核台可逐条改，改后留痕）。
                # 继承发生在建行的这一刻，之后素材重新归类不会回头改动已出的候选。
                category_id=asset.category_id,
                word_count=shape["chars"],
                is_recommended=bool(cand.get("is_recommended")),
                consistency_ok=consist["ok"],
                consistency_note=(
                    None if consist["ok"] and consist.get("note") is None
                    else (consist.get("note") or f"实体未命中：{'、'.join(consist['missing'])}")[:300]
                ),
                risk_hit=svc.format_risk_hits(risk),
                audit_status=RV_PENDING,
                source_prompt_task_id=asset.prompt_task_id,
            )
            db.add(summary)
            created_rows.append(summary)
            created += 1
        await db.flush()

        if created:
            svc.apply_stage(asset, "summary", STAGE_SUCCESS, has_approved_copy=asset.has_approved_copy)
        else:
            svc.apply_stage(asset, "summary", STAGE_FAILED)
        entry = {
            "asset_id": str(asset.id),
            "code": asset.code,
            "created": created,
            "model": result.get("model"),
        }
        # ④候选齐全（A2-1）：要 3 条只回 1 条也叫"成功"的话，审核页就没有对照，
        # 橡皮章式过审就是这么来的。不齐如实说，并给前端一个可判断的字段。
        if created and created < count:
            entry["candidates_short"] = count - created
            entry["note"] = f"候选不齐：要 {count} 条只出 {created} 条，审核缺横向对照，建议重生成"
        results.append(entry)
        if created_rows:
            # 多候选时只给**推荐条**挂号（没有推荐条就挂第一条）：一钩一号、发了即烧，
            # 三条候选都挂＝一条文案烧三个号，280/日的号池会被当废纸烧光。
            # 审核时真挑了非推荐那条，开单屏照旧手工填或点「代取」，跟批 N 之前一样。
            new_copy_rows.append(next((s for s in created_rows if s.is_recommended), created_rows[0]))
            web_jobs.append({"asset": asset, "script": script, "summaries": created_rows})

    await _write_audit(
        db,
        action="asset.summary_generate",
        operator=current_user,
        target_type="asset_item",
        target_id=None,
        after={
            "count": count,
            "requested": len(targets),
            "overwrite": data.overwrite,
            # A4-6：整批排队时审计要能回显"这批的哪一段"，否则事后查不到是谁点了第几排
            "queue": queue,
            "cross_person": crosses or None,
        },
    )
    await db.commit()

    # 11-09 批 O：出文案的当场把编号预取好挂上（用户口径「以后的新文案也自动预取吧」）。
    # 放在 commit 之后、第二跳之前：这一枪上面刚做完模型调用，同一条铁律——
    # 事务开着等外部调用（取号脚本最坏 30s×块数）会被 idle_in_transaction 60s 掐连接，
    # 11-03 预览栈实测整口 500、花钱换来的候选一条没落库。候选此刻已经提交，
    # 取号失败只少个预取位，开单时手工填或点「代取」照旧补得上。
    park = await _auto_park_hook_codes(db, new_copy_rows, operator=current_user, source="summary_generate")
    await db.commit()

    # ── 11-06 双产出第二跳：豆包网页版提示词 ──
    # 候选已在上面随审计一起提交，此刻事务干净，可以安心等模型（同一条铁律：
    # 外部调用前必须结束事务，idle_in_transaction 60s 会掐连接）。
    # 失败只记条目不回滚文案——一句话文案是真金白银换来的，提示词丢了用
    # 补口（POST /assets/summaries/prompt-web）单独补，别让两条产出绑死一条命。
    web_ok_assets = 0
    web_fail_assets = 0
    web_filled = 0
    # 字段并回主循环里那条结果（前端按 asset_id 一行一素材展示，别出两行）
    entry_by_asset = {r["asset_id"]: r for r in results if r.get("asset_id")}
    for job in web_jobs:
        asset = job["asset"]
        rows = job["summaries"]
        drama_title = await _drama_title_of(db, asset)
        payload = {
            "script": job["script"],
            "candidates": [
                {"seq": s.seq, "text": s.text, "formula_tag": s.formula_tag or ""}
                for s in rows
            ],
            # 内部重试压到 1 次：与出文案同口径（外层 900s，默认 3 次最坏 12 分钟必顶穿）
            "max_retries": 1,
            "params": {
                "drama_title": drama_title,
                "compliance": "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
                **({"duration_seconds": int(round(asset.duration))} if asset.duration else {}),
            },
        }
        entry = entry_by_asset.get(str(asset.id), {
            "asset_id": str(asset.id), "code": asset.code,
        })
        try:
            web = await _call_autoclip("hook-copy/prompt-web", payload)
        except HTTPException as exc:
            web_fail_assets += 1
            entry["doubao_prompt_filled"] = 0
            entry["doubao_prompt_total"] = len(rows)
            entry["web_note"] = f"豆包网页版提示词生成失败（文案不受影响，可单独补）：{str(exc.detail)[:200]}"
            continue
        by_seq: Dict[int, dict] = {}
        for p in web.get("prompts") or []:
            try:
                by_seq[int(p.get("seq") or 0)] = p
            except (TypeError, ValueError):
                continue
        filled = 0
        for s in rows:
            p = by_seq.get(int(s.seq))
            text = str((p or {}).get("prompt_text") or "").strip()
            if text:
                s.doubao_prompt = text
                filled += 1
        web_filled += filled
        if filled == len(rows) and rows:
            web_ok_assets += 1
        else:
            web_fail_assets += 1
        entry["doubao_prompt_filled"] = filled
        entry["doubao_prompt_total"] = len(rows)
        if filled != len(rows):
            entry["web_note"] = f"豆包网页版提示词只补上 {filled}/{len(rows)} 条（模型漏段），缺的在详情里点「补提示词」"
        # 逐素材提交：一条崩了不拖死已经填好的
        await db.commit()

    return {
        "results": results,
        "queue": queue,
        "hook_codes": _park_payload(park),
        "message": f"已为 {sum(1 for r in results if r.get('created'))} 条素材出文案"
        + (
            f"；{web_ok_assets} 条素材的豆包网页版提示词已同步生成（共 {web_filled} 段）"
            if web_filled else ""
        )
        + (
            f"；{web_fail_assets} 条素材的网页版提示词没生成全，详情里可单独补"
            if web_fail_assets else ""
        )
        + (f"；队列还剩 {queue['remaining']} 条，下一次接着排" if queue and queue["remaining"] else "")
        + (f"；{_park_note(park)}" if park.get("attempted") else ""),
    }


class RiskLexiconUpdateRequest(BaseModel):
    """风险词表更新（admin）。"""
    block: List[str] = Field(default_factory=list, description="拦级词：命中即不许过审、不许投产")
    warn: List[str] = Field(default_factory=list, description="警级词：只留痕预警，人工判断")
    exempt: Dict[str, str] = Field(default_factory=dict, description="豁免正则：词 → 正则（命中点被它整个包住就不算命中）")
    inherit: bool = Field(default=True, description="true=在默认词表上追加；false=整体替换默认表")


@router.get("/assets/risk-lexicon")
async def get_risk_lexicon(
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """读当前生效的风险词表（审核/投产闸门用的就是这一份）。

    material 也能读：出文案的就是他们，被 block 词拦下来时得知道拦的是哪个词、怎么绕。
    """
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.key == svc.RISK_LEXICON_CONFIG_KEY))
    ).scalar_one_or_none()
    raw = row.value if row is not None and isinstance(row.value, dict) else {}
    book, eff_exempt = svc.effective_risk_words(raw)
    return {
        "effective": {"block": list(book.get("block") or []), "warn": list(book.get("warn") or [])},
        "exempt": eff_exempt,
        "defaults": {
            "block": list(svc.DEFAULT_RISK_LEXICON[svc.RISK_LEVEL_BLOCK]),
            "warn": list(svc.DEFAULT_RISK_LEXICON[svc.RISK_LEVEL_WARN]),
            "exempt": dict(svc.DEFAULT_RISK_EXEMPTIONS),
        },
        "override": {
            "block": [str(w) for w in (raw.get("block") or [])],
            "warn": [str(w) for w in (raw.get("warn") or [])],
            "exempt": {str(k): str(v) for k, v in (raw.get("exempt") or {}).items()},
            "inherit": bool(raw.get("inherit", True)),
        },
        "has_override": row is not None,
        "updated_at": utc_iso(row.updated_at) if row is not None and row.updated_at else "",
        "ttl_seconds": int(settings.ASSET_RISK_LEXICON_TTL_SECONDS),
        "can_edit": current_user.role == UserRole.admin.value,
    }


@router.put("/assets/risk-lexicon")
async def update_risk_lexicon(
    data: RiskLexiconUpdateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """改风险词表（admin）。改完立刻清缓存，下一次审核/投产就用新表。"""

    def _clean(words: List[str]) -> List[str]:
        out: List[str] = []
        for w in words or []:
            s = str(w or "").strip()
            if s and s not in out:
                out.append(s)
        return out

    block = _clean(data.block)
    warn = _clean(data.warn)
    exempt: Dict[str, str] = {}
    for word, pattern in (data.exempt or {}).items():
        w = str(word or "").strip()
        p = str(pattern or "").strip()
        if not w:
            continue
        if p:
            try:
                re.compile(p)
            except re.error as e:
                raise HTTPException(status_code=400, detail=f"豁免正则写错了：{w} → {p}（{e}）")
        exempt[w] = p

    value = {"block": block, "warn": warn, "exempt": exempt, "inherit": bool(data.inherit)}
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.key == svc.RISK_LEXICON_CONFIG_KEY))
    ).scalar_one_or_none()
    # R-3（11-04 第二轮审核）：这份词表**保存即生效**并直接决定谁能过审、谁能投产，
    # 却没有留痕就答不上「谁在什么时候把哪个词从 warn 挪到 block」。本文件其它写口
    # （撤销过审、豁免、投产、拼接）都写审计，这是唯一的例外，补上。
    # before 取**改前的整份覆盖**（没配过就是 None＝当时走默认表），after 取改后的整份。
    before_value = copy.deepcopy(row.value) if row is not None and row.value else None
    if row is None:
        row = SystemConfig(
            key=svc.RISK_LEXICON_CONFIG_KEY,
            value=value,
            description="素材库风险词表（block=拦 / warn=警 / exempt=豁免正则 / inherit=是否在默认表上追加）",
        )
        db.add(row)
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
        if not row.description:
            row.description = "素材库风险词表（block=拦 / warn=警 / exempt=豁免正则 / inherit=是否在默认表上追加）"
    await db.flush()
    await db.refresh(row)
    await _write_audit(
        db,
        action="asset.risk_lexicon.update",
        operator=current_user,
        target_type="asset_risk_lexicon",
        target_id=svc.RISK_LEXICON_CONFIG_KEY,
        before=before_value,
        after=value,
    )
    _risk_cache_invalidate()

    book, eff_exempt = svc.effective_risk_words(value)
    notes: List[str] = []
    if not data.inherit and not block and not warn:
        notes.append("两级词表都清空了 → 实际生效的仍是内置默认表（词表全空会自动回落，不会变成全放行）")
    if not data.inherit:
        notes.append("已选「整体替换」：默认词表里没列出的词不再拦人")
    else:
        notes.append("已选「在默认表上追加」：默认词表仍然生效")
    return {
        "ok": True,
        "effective": {"block": list(book.get("block") or []), "warn": list(book.get("warn") or [])},
        "exempt": eff_exempt,
        "updated_at": utc_iso(row.updated_at) if row.updated_at else "",
        "notes": notes,
    }


# ─────────────────────  投产前可替换元素（批 M，11-10）  ─────────────────────
# 用户在②投产弹窗点「确认投板」之前，要把提示词里换得动的元素（场景／动物／道具…）
# 挑一个或自己填，换完拿到一份**完整可编辑**的正文再投。
#
# 形态完全照风险词库（同一类东西：运营能改、全员要读、不进模型提示词）：
# 读用 `_PROD_ROLES`、写只 admin、改动写 AuditLog，三层 defaults／override／effective。
#
# **抽元素与组稿都是纯文本进、纯文本出**，不读生产单、不落任何库：
# 前端把手上那份投递稿正文递进来，引擎认槽位、按人选替换，再把新正文原样递回去。
# 这样「换元素」与「改稿」是同一条通道（`DispatchRequest.prompt_overrides`），
# 库里的 `prompt_text`／过审文案一字不动——这是 11-06 的拍板，也是用户这次的原话
# （「原有的提示词，你不要给它们覆盖掉」）。
# 组出来的正文在返回时就照投板那道 block 级风险词重扫一遍，
# 让人在弹窗里就知道"换上这个词会被拦"，而不是点确认才吃 400。


def pattern_has_group(pattern: str) -> bool:
    """写法里到底有没有捕获组——存进去才发现没有，界面就会「认得出但换不动」。"""
    try:
        return re.compile(pattern).groups >= 1
    except re.error:
        return False


class PromptElementSlotRow(BaseModel):
    """元素库的一行（PUT 的一条）。键与写法当场校验：坏正则直接 400，不让人以为存好了。"""
    key: str = Field(..., description="稳定标识（同键覆盖出厂默认表；建议小写英文＋下划线）")
    label: str = Field("", description="界面显示名（如「场景」「出场的动物」），留空用 key")
    mode: str = Field(
        pesvc.MODE_LITERAL,
        description="literal＝正文里逐字找词面（场景/动物这类写在③剧情自由文本里的东西）；"
        "pattern＝按带捕获组的正则找（①那种模板保证存在、只能在原地处改的位置）；"
        "manual＝整句话（台词/泄密内容/引爆不公那句），系统不猜原值，这一行永远摆出来给人手填",
    )
    anchors: List[str] = Field(
        default_factory=list,
        description="literal 认法要匹配的词面；留空＝拿候选池当词面",
    )
    pattern: str = Field("", description="pattern 认法的正则，捕获组 1 就是当前值")
    probe: str = Field(
        "",
        description="literal 专用的**识别位置**（带捕获组）：词表外的值也能认出当前值，"
        "替换仍按逐字全局走。场景就靠它认「剧情：」后第一段。",
    )
    pool: List[str] = Field(default_factory=list, description="裂变候选（顺序＝界面上的推荐顺序）")
    categories: List[str] = Field(
        default_factory=list,
        description="只在这些钩子原型下出现（填原型名或「原型 A」这种短前缀）；留空＝所有原型都用这一槽位",
    )
    skip_lines: Optional[str] = Field(
        None,
        description="这一槽位不碰哪些行（正则，缺省＝「钩子原文」行＋①生成【…】行）。"
        "明确写空串＝允许碰那两行（换剧名这类特殊活儿才用）",
    )
    note: str = Field("", description="行内说明（纯展示，告诉一线这个槽位换的是什么）")


class PromptElementsUpdateRequest(BaseModel):
    slots: List[PromptElementSlotRow] = Field(default_factory=list)
    inherit: bool = Field(
        True, description="true＝在出厂默认表上追加/覆盖同键；false＝整体替换（默认槽位也不再认）"
    )


class PromptElementsExtractRequest(BaseModel):
    texts: Dict[str, str] = Field(
        default_factory=dict,
        description="行 id → 那份投递稿正文（一次上限 50 条，单条上限 20000 字）",
    )
    category: Optional[str] = Field(
        None, description="钩子原型名或「原型 A」这种短前缀；给了就只报这个原型适用的元素"
    )
    include_unmatched: bool = Field(
        False,
        description="true＝这一原型的参数项**全摆出来**，认不出原值的 current 给空"
        "（④开单屏要的就是这个：先让人知道这个类型要设哪几项）；"
        "false＝只回报认得出的（②投产弹窗的老口径，不摆空下拉）",
    )


class PromptElementEditItem(BaseModel):
    """一条替换。`old` 留空＋槽位是 pattern＝把这个槽位的所有命中都换掉。"""
    key: str = Field("", description="元素槽位键；留空＝自定义替换（整段逐字换，不限于字典认出的元素）")
    old: str = Field("", description="要换掉的那段原文")
    new: str = Field(..., description="换成什么")


class PromptElementsApplyRequest(BaseModel):
    text: str = Field(..., description="当前那份投递稿正文")
    edits: List[PromptElementEditItem] = Field(default_factory=list)


_MAX_EXTRACT_ITEMS = 50
_MAX_ELEMENT_TEXT_LEN = 20000


async def _prompt_element_catalog(db: AsyncSession) -> List[Dict[str, Any]]:
    """读生效元素字典（每次现读，不缓存）。

    TTL 缓存是给"每个动作都要扫一遍"的风险词表准备的；元素字典只在开弹窗时读一次，
    而**运营刚配完就等着看效果**，缓存反而制造"配了看着没生效"。
    """
    row = (
        await db.execute(
            select(SystemConfig).where(SystemConfig.key == pesvc.PROMPT_ELEMENTS_CONFIG_KEY)
        )
    ).scalar_one_or_none()
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    eff, _override = pesvc.merge_catalog(value)
    return eff


@router.get("/assets/prompt-elements")
async def get_prompt_elements(
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """读当前生效的可替换元素字典（抽元素／组稿用的就是这一份）。"""
    row = (
        await db.execute(
            select(SystemConfig).where(SystemConfig.key == pesvc.PROMPT_ELEMENTS_CONFIG_KEY)
        )
    ).scalar_one_or_none()
    raw = row.value if row is not None and isinstance(row.value, dict) else {}
    eff, override = pesvc.merge_catalog(raw)
    return {
        "effective": eff,
        "defaults": pesvc.normalize_catalog(pesvc.DEFAULT_PROMPT_ELEMENTS),
        "override": override,
        "inherit": bool(raw.get("inherit", True)),
        "has_override": row is not None,
        # 界面要能把「这一行用的是默认保护行」和「这一行被改成了别的手法」分开显示，
        # 所以把默认串也吐出去——前端自己抄一份迟早和这里对不上。
        "default_skip_lines": pesvc.DEFAULT_SKIP_LINES,
        "updated_at": utc_iso(row.updated_at) if row is not None and row.updated_at else "",
        "can_edit": current_user.role == UserRole.admin.value,
        "notes": [
            "候选池还没配的元素槽位照样能用：界面上走「自定义输入」，功能不断档",
            "「场景／动物」这类元素要按钩子原型加行，存完立即生效，不用发版",
            "整句话那几项（动物说的话／偷听到的内容／引爆不公那句）是手填项：系统不猜原句，"
            "界面永远摆出来让人从稿子里复制",
            "认与换都不碰「钩子原文」那行和 ① 生成【…】那行（后者里面有《剧名》，"
            "把动物全文替换会顺手造出一部不存在的剧）",
            "「题材标签／剧名」11-10 已按用户口径从默认字典去掉（参考文件《钩子模版换皮参数设定.docx》"
            "里没有这两项）：要改 ① 行那几个字，用「自定义替换」照打一遍",
        ],
    }


@router.put("/assets/prompt-elements")
async def update_prompt_elements(
    data: PromptElementsUpdateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.admin))],
    db: AsyncSession = Depends(get_db),
):
    """改元素字典（仅 admin）。改完下一次抽元素就用新表。"""
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in data.slots:
        key = str(item.key or "").strip()[:60]
        if not key:
            raise HTTPException(status_code=400, detail="有一行没写「键」，键是这一行的身份证号，不能空")
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"键重复了：{key}（同键只会留一份，先把多余那行删掉）",
            )
        seen.add(key)
        mode = str(item.mode or pesvc.MODE_LITERAL).strip()
        if mode not in pesvc.SLOT_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"「{key}」的认法只认三种：逐字找词面（literal）、按写法找（pattern）、"
                    f"整句自己填（manual），现在写的是：{mode}"
                ),
            )
        pattern = str(item.pattern or "").strip()
        if pattern:
            if len(pattern) > pesvc.MAX_PATTERN_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{key}」的识别写法太长了（上限 {pesvc.MAX_PATTERN_LEN} 字）",
                )
            err = pesvc.compile_error(pattern)
            if err:
                raise HTTPException(status_code=400, detail=f"「{key}」的识别写法编不过：{err}")
            if not pattern_has_group(pattern):
                raise HTTPException(
                    status_code=400,
                    detail=f"「{key}」的识别写法里要有捕获组（用圆括号把当前值那段包住），否则不知道该换哪一段：{pattern}",
                )
        if mode == pesvc.MODE_PATTERN and not pattern:
            raise HTTPException(
                status_code=400,
                detail=f"「{key}」写了按写法找（pattern）却没给识别写法，这一行什么都认不出",
            )
        probe = str(item.probe or "").strip()
        if probe:
            if mode == pesvc.MODE_PATTERN:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{key}」是 pattern 槽位，识别位置（probe）是给逐字找词面那类用的，两者不叠加",
                )
            if len(probe) > pesvc.MAX_PATTERN_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=f"「{key}」的识别位置太长了（上限 {pesvc.MAX_PATTERN_LEN} 字）",
                )
            err = pesvc.compile_error(probe)
            if err:
                raise HTTPException(status_code=400, detail=f"「{key}」的识别位置编不过：{err}")
            if not pattern_has_group(probe):
                raise HTTPException(
                    status_code=400,
                    detail=f"「{key}」的识别位置要带一个捕获组（圆括号包住「当前值」那段），否则不知道该认哪几个字：{probe}",
                )
        # manual 行什么都可以不给（这行就是要人填）；literal 行必须给词面、候选或识别位置，
        # 否则存进去的是"看着有这行、永远认不出"的僵尸槽位
        if mode == pesvc.MODE_LITERAL and not (item.anchors or item.pool or probe):
            raise HTTPException(
                status_code=400,
                detail=f"「{key}」是逐字找词面的槽位，词面（anchors）、候选（pool）、识别位置（probe）至少要给一个",
            )
        skip_lines = item.skip_lines
        if skip_lines is not None:
            skip_lines = str(skip_lines).strip()
            if skip_lines:
                if len(skip_lines) > pesvc.MAX_SKIP_PATTERN_LEN:
                    raise HTTPException(
                        status_code=400,
                        detail=f"「{key}」的跳过写法太长了（上限 {pesvc.MAX_SKIP_PATTERN_LEN} 字）",
                    )
                err = pesvc.compile_error(skip_lines)
                if err:
                    raise HTTPException(
                        status_code=400,
                        detail=f"「{key}」的跳过写法编不过（留空表示用默认保护行）：{err}",
                    )
        rows.append(
            {
                "key": key,
                "label": item.label,
                "mode": mode,
                "anchors": item.anchors,
                "pattern": pattern,
                "probe": probe,
                "pool": item.pool,
                "categories": item.categories,
                "skip_lines": skip_lines,
                "note": item.note,
            }
        )
    if len(rows) > pesvc.MAX_SLOTS:
        raise HTTPException(status_code=400, detail=f"元素槽位最多 {pesvc.MAX_SLOTS} 行")

    value = {"slots": rows, "inherit": bool(data.inherit)}
    row = (
        await db.execute(
            select(SystemConfig).where(SystemConfig.key == pesvc.PROMPT_ELEMENTS_CONFIG_KEY)
        )
    ).scalar_one_or_none()
    before_value = copy.deepcopy(row.value) if row is not None and row.value else None
    if row is None:
        row = SystemConfig(
            key=pesvc.PROMPT_ELEMENTS_CONFIG_KEY,
            value=value,
            description="投产前可替换元素字典（slots=槽位／inherit=是否在出厂默认表上追加）",
        )
        db.add(row)
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
        if not row.description:
            row.description = "投产前可替换元素字典（slots=槽位／inherit=是否在出厂默认表上追加）"
    await db.flush()
    await db.refresh(row)
    await _write_audit(
        db,
        action="asset.prompt_elements.update",
        operator=current_user,
        target_type="asset_prompt_elements",
        target_id=pesvc.PROMPT_ELEMENTS_CONFIG_KEY,
        before=before_value,
        after=value,
    )
    eff, _ = pesvc.merge_catalog(value)
    notes: List[str] = []
    if not data.inherit:
        notes.append(
            "已选「整体替换」：出厂那 "
            f"{len(pesvc.normalize_catalog(pesvc.DEFAULT_PROMPT_ELEMENTS))} 行（原型 A–F 的参数项）都不再认，"
            f"现在生效的只有你给的 {len(eff)} 行"
        )
    if not eff:
        notes.append("字典一行都没有 → 抽元素什么都认不出来，界面上只剩「自定义替换」")
    notes.append("元素换出来的正文只走这一次投递（库里原稿一字不动），下一次再投仍是原稿")
    return {
        "ok": True,
        "effective": eff,
        "updated_at": utc_iso(row.updated_at) if row.updated_at else "",
        "notes": notes,
    }


@router.post("/assets/prompt-elements/extract")
async def extract_prompt_elements(
    data: PromptElementsExtractRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """从投递稿正文里认出可替换元素（带候选池），供②投产弹窗摆元素行。

    纯文本进出，不读库、不落库、不花钱。
    """
    catalog = await _prompt_element_catalog(db)
    if len(data.texts) > _MAX_EXTRACT_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多认 {_MAX_EXTRACT_ITEMS} 条（这次 {len(data.texts)} 条），分批看",
        )
    items: Dict[str, Any] = {}
    over_limit: List[str] = []
    for key, text in data.texts.items():
        body = str(text or "")
        if len(body) > _MAX_ELEMENT_TEXT_LEN:
            over_limit.append(str(key))
            items[str(key)] = []
            continue
        items[str(key)] = pesvc.extract_elements(
            body, catalog, data.category, include_unmatched=data.include_unmatched
        )
    notes: List[str] = []
    if not catalog:
        notes.append("元素字典是空的，认不出元素——去「可替换元素库」按钩子原型加行")
    if over_limit:
        notes.append(f"有 {len(over_limit)} 条正文太长（上限 {_MAX_ELEMENT_TEXT_LEN} 字），没去认元素")
    if data.include_unmatched:
        notes.append("标了「没认出」的那几项不是坏了：原稿里的写法不在词表内，或者本来就是整句话，"
                     "照原稿抄进去再填新值就行")
    return {
        "items": items,
        "category": data.category or "",
        "include_unmatched": data.include_unmatched,
        "catalog_count": len(catalog),
        "slot_labels": [s["label"] for s in catalog],
        "notes": notes,
    }


class PromptElementsGuessRequest(BaseModel):
    """11-10 用户口径「在页面上重新认参数，能不能再将它们提炼一下」的入参。

    形状与 `extract` 一致（行 id → 投递稿正文），但**这一口花钱**：`extract` 是 0 元、
    可复现的确定性认法，认不出就是认不出（词表外写法＋台词类整句按设计永不自动认）；
    这里补的是那一段——把稿子交给模型，让它**逐字抄回**稿子里扮演这个角色那段原文。
    所以它必须是界面上一个要点才会跑的按钮，不许挂在认参数后面自动发生。
    """

    texts: Dict[str, str] = Field(
        default_factory=dict,
        description=f"行 id → 那份投递稿正文（一次上限 {pesvc.GUESS_MAX_ITEMS} 篇、"
        f"总计上限 {pesvc.GUESS_MAX_TOTAL_CHARS} 字，超了就分批点）",
    )
    category: Optional[str] = Field(
        None, description="钩子原型名或「原型 A」这种短前缀；给了就只提炼这一型配的参数项"
    )


@router.post("/assets/prompt-elements/guess-values")
async def guess_prompt_element_values(
    data: PromptElementsGuessRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """让模型从稿子里**逐字抄回**各换皮参数的原值（「稿子里没认出原值」的补位路）。

    为什么需要它（回答一线那句「为什么都是稿子里没认出原值」）：
      - literal 槽只认字典里那几组字面词，稿子写「黄皮子」而词表是「黄鼠狼」就认不出；
      - manual 槽（说的话／偷听内容／引爆台词／绝境）**按设计永不自动认**——真稿是间接
        转述，没有形状可依，让人自己去上千字里找那句原话再逐字抄，才是今天卡住的地方；
      - 反推提示词那一步并没有"槽位"概念，所以这些值不是提前填好的，是开单这一屏现认的。

    安全边界（模型会编，所以校验不许商量）：`accept_guessed_values` 要求抄回来的串
    **逐字出现在这一份稿子的可动区间**里，编的一律丢弃并写进 `dropped` 白话。
    本口**只读**：不改稿、不进投递正文、不动字典、不覆盖已经认出的原值（那些由前端按
    「哪一格还没有值」决定，后端给的只是候选）。花一次模型钱，落一条审计。
    """
    if not data.texts:
        raise HTTPException(status_code=400, detail="没有稿子正文，没什么可提炼的")
    if len(data.texts) > pesvc.GUESS_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多提炼 {pesvc.GUESS_MAX_ITEMS} 篇（这次 {len(data.texts)} 篇），分批点",
        )
    total_chars = sum(len(str(v or "")) for v in data.texts.values())
    if total_chars > pesvc.GUESS_MAX_TOTAL_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"这一批稿子共 {total_chars} 字，超过一次 {pesvc.GUESS_MAX_TOTAL_CHARS} 字上限："
            "分批点，或先把「模板脚本提示词」里用不上的段落删短",
        )
    catalog = await _prompt_element_catalog(db)
    slots = pesvc.slots_for_guess(catalog, data.category)
    if not slots:
        raise HTTPException(
            status_code=400,
            detail="这一型在元素字典里没配参数项，没有可提炼的原值——先去「可替换元素库」按原型加行",
        )

    payload_texts = [{"id": str(k), "text": str(v or "")} for k, v in data.texts.items()]
    # 给模型的只有"这一项叫什么／是什么／常见的那些词"，`skip_lines`／`mode` 是**本机校验判据**，
    # 不出去（出去等于告诉它哪几行不能碰，它反而会照着绕）。
    payload_slots = [
        {"key": s["key"], "label": s["label"], "note": s["note"], "pool": s["pool"]} for s in slots
    ]
    res = await _call_autoclip(
        "hook-copy/slots",
        {"texts": payload_texts, "slots": payload_slots, "max_retries": 1},
        # 用 900s 默认值：单次问答比展开短，但超时链口径不许破（autoclip 600s < 这里 900s
        # < 浏览器 MODEL_WAIT_TIMEOUT 960s），理由见 `_call_autoclip` 那段注释。
    )

    items_by_id: Dict[str, List[Dict[str, Any]]] = {}
    stray: List[str] = []
    for row in res.get("items") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        if rid not in data.texts:
            # 模型自己造的 id：这份稿子没提交过，它给的值一个都不认
            stray.append(rid)
            continue
        items_by_id.setdefault(rid, []).append(row)

    values: Dict[str, Dict[str, str]] = {}
    dropped: List[str] = []
    silent: List[str] = []
    for key, text in data.texts.items():
        picked = pesvc.accept_guessed_values(str(text or ""), slots, items_by_id.get(str(key), []))
        if picked["values"]:
            values[str(key)] = picked["values"]
        else:
            silent.append(str(key))
        dropped.extend(picked["dropped"])

    notes: List[str] = [
        # 这几条会原样进界面（notification / Alert），不带 markdown 星号——
        # 11-10 done_note 就踩过这个坑：antd 只认纯文本，`**x**` 会裸显四个星号。
        "这一步是模型提炼（花一次模型钱，与出文案同档），不是 0 元的字典认法；"
        "抄回来的每个词都必须逐字出现在这份稿子里，模型编的当场丢弃。",
        "提炼只往「原稿里写的是」那一格填原值，不替你决定换成什么——换上什么还是你填。",
    ]
    if stray:
        notes.append(f"模型多回了 {len(stray)} 个没提交过的稿子编号，那些值一律没用")
    if silent:
        notes.append(
            f"有 {len(silent)} 篇一篇都没提炼到（多半是稿子里确实没写这一型要的那些东西）"
        )

    await _write_audit(
        db,
        action="asset.prompt_elements.guess_values",
        operator=current_user,
        target_type="asset_prompt_elements",
        target_id=data.category or "*",
        before=None,
        after={
            "text_count": len(payload_texts),
            "slot_count": len(slots),
            "filled_rows": len(values),
            "dropped_count": len(dropped),
            "model": res.get("model") or "",
        },
    )
    return {
        # 行 id → {槽位 key: 逐字抄回的原值}（与 extract 的 items 同一套 id，前端按格回填）
        "values": values,
        "labels": {str(s["key"]): str(s.get("label") or s["key"]) for s in slots},
        "dropped": dropped,
        "notes": notes,
        "model": res.get("model") or "",
        "slot_count": len(slots),
        "text_count": len(payload_texts),
        "total_chars": total_chars,
    }


@router.post("/assets/prompt-elements/apply")
async def apply_prompt_elements(
    data: PromptElementsApplyRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """按人选的元素替换把整段正文组出来，并当场扫一遍拦级风险词。

    返回的 `text` 就是要塞进「完整可编辑正文」那一份；人还能接着手改，
    点确认时才作为 `prompt_overrides` 投出去。
    """
    if len(data.text) > _MAX_ELEMENT_TEXT_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"正文 {len(data.text)} 字，超过 {_MAX_ELEMENT_TEXT_LEN} 字上限，先删短再组稿",
        )
    catalog = await _prompt_element_catalog(db)
    edits = [{"key": e.key, "from": e.old, "to": e.new} for e in data.edits]
    text, replaced, notes = pesvc.apply_edits(data.text, catalog, edits)
    # 11-10 用户口径①「看不到正文被替换的地方」：位置在这里也算出来，
    # 前端那棵高亮树只认 marks，不再自己 indexOf 猜。
    marks, mark_notes = pesvc.mark_replacements(text, replaced, data.text)
    notes = notes + mark_notes
    if len(text) > _PROMPT_OVERRIDE_MAX_LEN:
        notes.append(
            f"组完 {len(text)} 字，超过投递稿单条上限 {_PROMPT_OVERRIDE_MAX_LEN} 字，投板时会被拦，先删一点"
        )
    book, exemptions = await _risk_lexicon(db)
    hits = svc.scan_risk(text, lexicon=book, exemptions=exemptions)
    blocked = svc.risk_block_hits(hits)
    return {
        "text": text,
        "replaced": replaced,
        "marks": marks,
        "notes": notes,
        "length": len(text),
        "risk": {
            "block": blocked,
            "warn": [h for h in hits if h.get("level") == svc.RISK_LEVEL_WARN],
        },
        # 与投板那道闸同一个判据：这里非空，点确认就会照原稿那道闸被拦（admin 可带理由强行投）
        "would_dispatch_block": bool(blocked),
    }


class PromptElementsFanoutPreviewRequest(BaseModel):
    """④ 开单屏「换完长这样」的入参：和 produce 的扇出入口**同一套键**，只是不落库、不调模型。"""

    texts: Dict[str, str] = Field(
        default_factory=dict,
        description="行 id（summary_id）→ 这一屏看到的那份底稿（上限同 extract：50 条 / 单条 20000 字）",
    )
    category: Optional[str] = Field(None, description="钩子原型；给了就只按这个原型的参数项换")
    values: Dict[str, List[str]] = Field(
        default_factory=dict, description="槽位 key → 要换上的多个值（扇几行就看它）"
    )
    base: Optional[Dict[str, str]] = Field(None, description="公共原值（这一屏手填/认出的那份）")
    base_by_summary: Optional[Dict[str, Dict[str, str]]] = Field(
        None, description="逐篇原值；与 produce 同一条合并口径：**逐篇覆盖公共**"
    )
    mode: str = Field(pesvc.MATRIX_ZIP, description="zip＝按行配对，product＝全组合")


@router.post("/assets/prompt-elements/fanout-preview")
async def preview_prompt_element_fanout(
    data: PromptElementsFanoutPreviewRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """把「每个参数填了多个值」扇出来的那 N 份稿子当场组给人看（11-10 用户口径）。

    用户 11-10 晚的原话：「我刚选了几个元素，但是没有看到正文被替换的地方。」这一口就是答案：
    填完值立刻看到换完之后长什么样、哪几条真换动了、哪几条其实没换动。

    ⚠️ 三条要说死的口径：
     1. **和开单同一个引擎**——`expand_matrix` ＋ `compose_variants`（produce 扇出走的
        `_element_fanout_rows` 里那两个），不是前端另拼一套字符串。所以配对报错、
        "只填一个值的参数每行复用"、"没有原值就不换"这些行为预览与开单一致。
     2. **0 元、不落库、不占号**：不调 autoclip，只在传进来的那份底稿上做字面替换。
        开单时模型还会把文案展开成投递稿（`expand=true`），那份和这里看到的底稿可能有个别
        字面差别——界面上要写清"以投板前 ④「改投递稿」那一屏为准"，别让人以为这里就是终稿。
     3. **拦人的判据在这里也照跑，但只说不拦**：按行配对对不齐／全组合超上限 → 与 produce
        同样的 400（免得人在预览里看好几遍、点提交才挨打）；高风险词只列进 `risk_words`
        （produce 会整批 400），这里不拦是因为人还在试词。
    """
    if len(data.texts) > _MAX_EXTRACT_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多预览 {_MAX_EXTRACT_ITEMS} 条（这次 {len(data.texts)} 条），分批看",
        )
    over = [k for k, v in data.texts.items() if len(str(v or "")) > _MAX_ELEMENT_TEXT_LEN]
    if over:
        raise HTTPException(
            status_code=400,
            detail=f"这几条正文超过 {_MAX_ELEMENT_TEXT_LEN} 字上限，先删短再预览：{', '.join(over[:3])}",
        )

    catalog = await _prompt_element_catalog(db)
    labels = {s["key"]: s["label"] for s in catalog}
    try:
        matrix_rows, matrix_notes = pesvc.expand_matrix(data.values, data.mode or pesvc.MATRIX_ZIP, labels)
    except ValueError as exc:
        # 与 produce 完全同一条 400 话术（同一函数抛的），预览里看到的拦和开单里看到的拦是一个字
        raise HTTPException(status_code=400, detail=str(exc))

    # 公共原值打底、逐篇覆盖：与 produce 的 `{**element_base, **element_bases.get(...)}` 同一条
    common_base = {
        str(k).strip(): str(v or "").strip()[: pesvc.MAX_MANUAL_VALUE_LEN]
        for k, v in (data.base or {}).items()
        if str(v or "").strip()
    }
    per_base: Dict[str, Dict[str, str]] = {}
    for sid_raw, per in (data.base_by_summary or {}).items():
        cleaned = {
            str(k).strip(): str(v or "").strip()[: pesvc.MAX_MANUAL_VALUE_LEN]
            for k, v in (per or {}).items()
            if str(v or "").strip()
        }
        if cleaned:
            per_base[str(_as_uuid(sid_raw, "summary_id"))] = cleaned

    book, exemptions = await _risk_lexicon(db)
    risk_words: List[str] = []
    for row in matrix_rows:
        for key, val in row.items():
            hits = svc.risk_block_hits(svc.scan_risk(val, lexicon=book, exemptions=exemptions))
            for h in hits:
                word = f"{labels.get(key) or key}「{val}」含高风险词 {h['word']}"
                if word not in risk_words:
                    risk_words.append(word)

    items: List[Dict[str, Any]] = []
    for sid_raw, body in data.texts.items():
        sid = str(_as_uuid(sid_raw, "summary_id"))
        base_values = {**common_base, **per_base.get(sid, {})}
        variants = pesvc.compose_variants(
            body, catalog, base_values, matrix_rows, data.category, with_marks=True
        )
        items.append({"id": sid, "variants": variants})

    return {
        "rows": max(1, len(matrix_rows)),
        "mode": data.mode or pesvc.MATRIX_ZIP,
        "notes": matrix_notes,
        "risk_words": risk_words,
        "items": items,
    }


@router.get("/assets/summaries")
async def list_summaries(
    audit_status: Optional[str] = None,
    asset_id: Optional[str] = None,
    asset_ids: Optional[str] = None,
    batch_id: Optional[str] = None,
    only_risk: bool = False,
    only_inconsistent: bool = False,
    recommended_only: bool = False,
    only_resubmittable: bool = False,
    category_id: Optional[str] = None,
    q: Optional[str] = None,
    owner: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """文案审核队列（列表形式 + 审核态），素材列表点「文案」也走这里。

    11-09 加的两个入参（给「② 素材与文案 → 投去 AI 生成」用，读口径不变）：
      - `audit_status` 可传逗号多值（如 `approved,passed_edited`），单值行为照旧；
      - `asset_ids` 逗号分隔的素材 id（≤300 个），与 `asset_id` 是两套筛选、可叠加。

    `recommended_only`：只出推荐条。方案 §七「默认只过推荐条」防橡皮章——前端默认勾它，
    后端提供口径（B 组：原先只有列、没有参数）。

    `only_resubmittable`：只看「轮到我改」的（被驳回/需改写，且是我负责的素材；admin 看全部）。

    `q`（批 N·评审二 P1）：关键词搜索，正文/素材码模糊匹配——筛出空集时给人一条
    自己找回目标的正路，而不是对着空表猜筛选哪里配错了。

    `owner`（A′ 按运营隔离，2026-11-07）：**GET 读口的查询偏好**，写口权限不受它影响。
    owner=me → pending/驳回/需改写全量共享（挑文案是大家的事），**已过审区只显自己
    过审的**；owner=all 或缺省 → 全量。reviewed_by IS NULL 的存量过审行＝无主公共
    历史，owner=me 不含（三读口一致口径）。11-03「读口不分可见范围」的口径在本
    参数上被推翻（前端「我的」默认视图），推翻记录见 docs/素材库按运营隔离-设计方案-20261107.md。
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 300)

    conds = []
    # 11-03 口径：审核队列与全部读口一样**不分可见范围**，全量进队列（谁能审仍看角色）
    # 11-09：`audit_status` 支持逗号多值（② 素材与文案「投去 AI 生成」要一次把
    # approved + passed_edited 一起取回）。拆成两次请求拼不出可信 total，也不该让人
    # 猜「这条素材的过审文案到底在哪个请求里」。非法值当场 400 说清认哪几个——
    # 与 GET /assets 的 audit_status 同一口径，别让手滑变成一个查不到东西的空页签。
    status_list = [s.strip() for s in (audit_status or "").split(",") if s.strip()]
    bad_status = [s for s in status_list if s not in REVIEW_STATES]
    if bad_status:
        raise HTTPException(
            status_code=400,
            detail=f"audit_status 里有不认的值：{'、'.join(bad_status)}（只认 {'/'.join(REVIEW_STATES)}）",
        )
    if len(status_list) == 1:
        conds.append(AssetSummary.audit_status == status_list[0])
    elif len(status_list) > 1:
        conds.append(AssetSummary.audit_status.in_(status_list))
    if asset_id:
        conds.append(AssetSummary.asset_id == _as_uuid(asset_id, "asset_id"))
    # 11-09 新增：按**一批素材**取文案（素材列表勾选后直达投产要用）。上限 300＝一页
    # 勾选的实际上限，再多就是拿 IN 子句当遍历全表用，那种活该走 batch_id。
    if asset_ids:
        wanted_assets = _split_ids(asset_ids, "asset_ids")
        if len(wanted_assets) > 300:
            raise HTTPException(
                status_code=400,
                detail=f"asset_ids 一次最多 300 个（当前 {len(wanted_assets)} 个）；按整批取请改用 batch_id",
            )
        conds.append(AssetSummary.asset_id.in_([uuid.UUID(x) for x in wanted_assets]))
    if batch_id:
        conds.append(AssetItem.batch_id == _as_uuid(batch_id, "batch_id"))
    if only_risk:
        conds.append(AssetSummary.risk_hit.isnot(None))
    if only_inconsistent:
        conds.append(AssetSummary.consistency_ok.is_(False))
    if recommended_only:
        conds.append(AssetSummary.is_recommended.is_(True))
    if only_resubmittable:
        # 「等我改的」：被驳回/需改写、且是我负责的素材（admin 看全部）。
        # 这是驳回闭环的入口筛选——作者得能一眼找到轮到自己改的那几条。
        conds.append(AssetSummary.audit_status.in_((RV_REJECTED, RV_NEED_REWRITE)))
        if current_user.role != UserRole.admin.value:
            conds.append(AssetItem.created_by == current_user.id)
    if owner not in (None, "", "me", "all"):
        raise HTTPException(status_code=400, detail="owner 只支持 me（我的链路）或 all（全量），缺省=all")
    if owner == "me":
        # A′：已过审区按过审人隔离；pending/驳回/需改写全量共享；无主公共历史（NULL）不含
        conds.append(or_(
            AssetSummary.audit_status.notin_((RV_APPROVED, RV_PASSED_EDITED)),
            and_(
                AssetSummary.audit_status.in_((RV_APPROVED, RV_PASSED_EDITED)),
                AssetSummary.reviewed_by == current_user.id,
            ),
        ))
    if q and q.strip():
        # 批 N（评审二 P1）：正文/素材码子串匹配（大小写不敏感）。LIKE 转义掉
        # 用户手滑输入的 %/_，别让搜索框变成全表扫。
        kw = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{kw}%"
        conds.append(or_(AssetSummary.text.ilike(like), AssetItem.code.ilike(like)))
    # 11-04 拍板①：按**文案自己的**原型筛（继承来的也算它自己的，改过就按改后的），
    # `none`＝未分类。为什么不用素材那列筛：审核台上"这条文案属于哪个原型"才是审的东西，
    # 素材被重新归过类不该把已经定性的文案一起带走。
    cat_cond = _category_cond(category_id)
    if cat_cond == "none":
        conds.append(AssetSummary.category_id.is_(None))
    elif cat_cond is not None:
        conds.append(AssetSummary.category_id == cat_cond)

    stmt = (
        select(AssetSummary, AssetItem)
        .join(AssetItem, AssetItem.id == AssetSummary.asset_id)
        .where(and_(*conds))
        if conds
        else select(AssetSummary, AssetItem).join(AssetItem, AssetItem.id == AssetSummary.asset_id)
    )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            # 同素材 3 条候选必须相邻：created_at 是同事务批量插入、秒级相同，只按
            # created_at+seq 排会在平局里把同素材的 3 条打散（用户实测「3 条分开看着搞混」）。
            stmt.order_by(
                AssetSummary.created_at.desc(), AssetSummary.asset_id.asc(), AssetSummary.seq.asc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    cat_names = await _category_name_map(db)
    # 批 F 卡片右侧「已产 N 条」：`asset_summaries.id → asset_productions.summary_id
    # → asset_outputs.production_id` 一条 join，整页一次聚合（默认一页 100 条，
    # 逐行数＝100 次查询）。
    # 只数**视频**：package（交付包 zip）/copy（文案 txt）是附属文件，算进去会让
    # 「一条成片配一份 zip」看起来像产了 2 条。拼接产物没挂生产单（production_id
    # 为空）→ 不计：那是"两段拼的"，不归到某条文案头上。
    out_counts: Dict[Any, int] = {}
    sids = [s.id for s, _a in rows]
    if sids:
        orows = (
            await db.execute(
                select(AssetProduction.summary_id, func.count(AssetOutput.id))
                .join(AssetOutput, AssetOutput.production_id == AssetProduction.id)
                .where(
                    AssetProduction.summary_id.in_(sids),
                    AssetOutput.kind.notin_(("package", "copy")),
                )
                .group_by(AssetProduction.summary_id)
            )
        ).all()
        out_counts = {sid: int(cnt) for sid, cnt in orows}
    # A′：过审人显示名一次聚合
    reviewer_names = await _user_names(db, {s.reviewed_by for s, _a in rows})
    # P1（评审定稿⑯）：每条候选已开过几张生产单——防重复开单白烧号池
    prod_counts: Dict[Any, int] = {}
    if rows:
        prows = (
            await db.execute(
                select(AssetSummary.id, func.count(AssetProduction.id))
                .join(AssetProduction, AssetProduction.summary_id == AssetSummary.id)
                .where(AssetSummary.id.in_([s.id for s, _a in rows]))
                .group_by(AssetSummary.id)
            )
        ).all()
        prod_counts = {r[0]: int(r[1]) for r in prows}
    return {
        "items": [
            _serialize_summary(
                s, a,
                can_resubmit=_can_resubmit(s, a, current_user),
                category_name=cat_names.get(str(s.category_id)) if s.category_id else None,
                output_count=out_counts.get(s.id, 0),
                production_count=prod_counts.get(s.id, 0),
                reviewer_name=reviewer_names.get(str(s.reviewed_by)) if s.reviewed_by else None,
            )
            for s, a in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _split_waived(
    problems: List[Dict[str, str]], waive_codes: Optional[List[str]]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """R-6：把复核拦点按**问题类型**切成「豁免掉的」和「仍然拦着的」。

    `waive_codes` 留空＝整条全豁免（旧行为，保持兼容）；一旦传了就只放过点名的类型——
    原来「一致性对不上 → 找 admin 豁免 → 同条里的真违禁词一起被放过」就是这么发生的。
    返回 (waived, still_blocking)；still_blocking 非空＝这条仍然不许过。
    """
    if not waive_codes:
        return list(problems), []
    wanted = {str(c).strip() for c in waive_codes if str(c).strip()}
    waived = [p for p in problems if p["code"] in wanted]
    still = [p for p in problems if p["code"] not in wanted]
    return waived, still


@router.post("/assets/summaries/review")
async def review_summaries(
    data: ReviewRequest,
    current_user: Annotated[User, Depends(require_functions("review"))],
    db: AsyncSession = Depends(get_db),
    _role_gate: User = Depends(require_roles(*_REVIEW_ROLES)),
):
    """批量审核钩子文案：通过 / 驳回 / 需改写 / 改后通过。

    四条硬规矩（审核席位要求，别在改代码时 loosen）：
    1. **生产者不得自审**：素材创建人不能过自己素材的文案（admin 除外）；
    2. **驳回必填理由**：否则改写的人只能靠猜；
    3. **改后通过必须留痕**：原文进 text_before_edit，before/after 进 AuditLog，供 admin 抽检；
    4. **过审前必须过复核**（A2-1，R-6 口径）：拦人的只有**超字数**和 **block 级风险词**；
       「与反推详规对不上」是**预警**——照样落库留痕（consistency_ok/note）、照样在接口里回给
       前端，但不拦过审（专名白名单天然误报，硬拦只会训练一线来找 admin 豁免）。
       admin 可带 `waive_reason` 豁免拦点，`waive_codes` 指定只放过哪几类（留空＝整条全放过，
       兼容旧行为）；豁免内容和理由逐条进 AuditLog。**撤销过审会连带把
       由此文案派生的未投递生产单置为 superseded**（A2-2），不留"审核已拒、单还能导"的孤儿。
    """
    action_map = {
        "approve": RV_APPROVED,
        "reject": RV_REJECTED,
        "need_rewrite": RV_NEED_REWRITE,
        "pass_edited": RV_PASSED_EDITED,
    }
    if data.action not in action_map:
        raise HTTPException(status_code=400, detail=f"action 只支持 {'/'.join(action_map)}")
    to_state = action_map[data.action]
    if not data.summary_ids:
        raise HTTPException(status_code=400, detail="请选择要审核的文案")
    if data.action in ("reject", "need_rewrite") and not (data.reason or "").strip():
        raise HTTPException(status_code=400, detail="驳回/需改写必须填理由")
    if data.action == "pass_edited" and not (data.new_text or "").strip():
        raise HTTPException(status_code=400, detail="改后通过必须提供修改后的文案")

    is_admin = current_user.role == UserRole.admin.value
    book, exemptions = await _risk_lexicon(db)
    results: List[dict] = []
    # 批 J：本次真正过审的文案（含"改后过"）——审核 commit 完之后拿去排提示词预览
    approved_now: List[Any] = []

    for sid in data.summary_ids:
        uuid_s = _as_uuid(sid, "summary_id")
        summary = (
            await db.execute(select(AssetSummary).where(AssetSummary.id == uuid_s))
        ).scalar_one_or_none()
        if summary is None:
            results.append({"summary_id": str(uuid_s), "ok": False, "error": "文案不存在"})
            continue
        # 文案所属素材（11-03 起不分可见范围，仍要确认素材行在，防孤儿文案 500）
        asset = await _get_asset_or_404(db, summary.asset_id)

        # 生产者不得自审（素材是别人导入的就不算自审，这里按「素材创建人」判）
        if not is_admin and asset.created_by == current_user.id:
            results.append({
                "summary_id": str(uuid_s), "ok": False, "code": asset.code,
                "error": "生产者不能审核自己导入的素材（换个人过审，或由管理员操作）",
            })
            continue

        try:
            svc.assert_review_transition(summary.audit_status, to_state)
        except ValueError as e:
            results.append({"summary_id": str(uuid_s), "ok": False, "code": asset.code, "error": str(e)})
            continue

        before = {"audit_status": summary.audit_status, "text": summary.text}
        was_passed = summary.audit_status in REVIEW_PASSED_STATES
        waived: Optional[dict] = None
        recheck_warnings: List[dict] = []

        # A2-1：过审 = 「这条就是要投豆包的那条」。所以过审前跑一遍与投产前**同一套**
        # 复核（形态/风险词 block 级/一致性），而不是只看一眼字数。
        effective = (
            (data.new_text or "").strip() if to_state == RV_PASSED_EDITED
            else (summary.text if to_state == RV_APPROVED else None)
        )
        if effective is not None:
            script = await _prompt_script_of(db, asset)
            verdict = svc.recheck_copy(effective, script, lexicon=book, exemptions=exemptions)
            if not verdict["ok"]:
                waived_list, still_blocking = _split_waived(
                    verdict["problems"], data.waive_codes if is_admin else None
                )
                if is_admin and (data.waive_reason or "").strip() and not still_blocking:
                    waived = {
                        "problems": waived_list,
                        "codes": sorted({p["code"] for p in waived_list}),
                        "reason": (data.waive_reason or "").strip()[:500],
                    }
                else:
                    # 分粒度豁免没覆盖到的类型照实拦下来，并说清是**哪几类**没被豁免
                    detail = still_blocking or verdict["problems"]
                    results.append({
                        "summary_id": str(uuid_s), "ok": False, "code": asset.code,
                        "error_code": "ASSET_RECHECK_FAILED",
                        "problems": detail,
                        "waivable_codes": sorted({p["code"] for p in verdict["problems"]}),
                        "error": "复核未过：" + "；".join(p["message"] for p in detail)
                                 + ("（管理员可填豁免理由强过，会记入审计；"
                                    "只放过某几类问题请传 waive_codes）"
                                    if is_admin else "（这条过不了，请改文案或找审核人）"),
                    })
                    continue
            if to_state == RV_PASSED_EDITED:
                summary.text_before_edit = summary.text
                summary.text = effective
            summary.word_count = verdict["chars"]
            summary.risk_hit = svc.format_risk_hits(verdict["risk"])
            recheck_warnings = list(verdict.get("warnings") or [])
            consist = verdict["consistency"]
            if consist is not None:
                summary.consistency_ok = consist["ok"]
                summary.consistency_note = (
                    None if consist["ok"] and consist.get("note") is None
                    else (consist.get("note") or f"实体未命中：{'、'.join(consist['missing'])}")[:300]
                )

        # A′（2026-11-07 按运营隔离）：同态重报**已过审**候选不改归属——B 重按一遍
        # A 过审过的「过」，reviewed_by 保持 A，绝不偷换成 B；回报里带 note 说清。
        # 撤审（approved→rejected）不算同态，走原路（reviewed_by 记撤审人，名下活跃单作废）。
        if to_state == before["audit_status"] and to_state in REVIEW_PASSED_STATES \
                and summary.reviewed_by not in (None, current_user.id):
            owner_name = (await _user_names(db, {summary.reviewed_by})).get(
                str(summary.reviewed_by), "未知"
            )
            results.append({
                "summary_id": str(uuid_s), "ok": True, "code": asset.code,
                "audit_status": to_state, "is_recommended": bool(summary.is_recommended),
                "warnings": [],
                "note": f"已由 {owner_name} 过审，保持原归属（未重复处理、归属未变）",
            })
            continue
        summary.audit_status = to_state
        summary.reviewed_by = current_user.id
        summary.reviewed_at = datetime.utcnow()
        summary.reject_reason = (data.reason or "").strip()[:500] if to_state in (RV_REJECTED, RV_NEED_REWRITE) else None

        # 素材概要态回写：只要有任意一条过审，就允许开生产单
        approved_cnt = (
            await db.execute(
                select(func.count(AssetSummary.id)).where(
                    AssetSummary.asset_id == asset.id,
                    AssetSummary.audit_status.in_(REVIEW_PASSED_STATES),
                )
            )
        ).scalar_one()
        asset.has_approved_copy = approved_cnt > 0
        svc.apply_stage(asset, "summary", STAGE_SUCCESS, has_approved_copy=asset.has_approved_copy)

        # A2-2：撤销过审必须把旧单一起作废，否则 `/produce`、`/export` 还在投一条已拒的文案
        superseded = 0
        if was_passed and to_state not in REVIEW_PASSED_STATES:
            why = f"文案撤销过审（{before['audit_status']}→{to_state}），由此单派生的生产任务作废"
            if (data.reason or "").strip():
                why += f"；审核意见：{data.reason.strip()[:300]}"
            superseded = await _supersede_productions(
                db, summary, operator=current_user, reason=why,
            )

        # 批 J：预览跟着「这条就是要投的那条」走——
        # 过审 → 记下来，commit 后排去备提示词；改后过 → 文案已经变了，旧预览作废；
        # 撤销过审 → 旧预览作废（重新过审会重新备）。留着过期预览，一线会拿它当投产结果。
        if to_state in REVIEW_PASSED_STATES:
            approved_now.append(summary.id)
            if to_state == RV_PASSED_EDITED and summary.prompt_preview is not None:
                summary.prompt_preview = None
                summary.prompt_preview_at = None
        elif summary.prompt_preview is not None:
            summary.prompt_preview = None
            summary.prompt_preview_at = None

        await _write_audit(
            db,
            action=f"asset.summary_review.{data.action}",
            operator=current_user,
            target_type="asset_summary",
            target_id=summary.id,
            before=before,
            after={
                "audit_status": summary.audit_status,
                "text": summary.text,
                "reason": summary.reject_reason,
                "waived": waived,
                "superseded_productions": superseded,
            },
            # 11-06 拍板①：豁免过审是最必须留痕的动作——审计写失败就拒绝这条过审
            # （整请求回滚），绝不出现「豁免了却查无此事」。
            strict=bool(waived),
        )
        results.append({
            "summary_id": str(uuid_s), "ok": True, "code": asset.code, "audit_status": to_state,
            "waived": bool(waived),
            # 11-06 P2：推荐与否是**这条文案自己的属性**，逐条带回真话——前端藏卡提示
            # 的「非推荐」统计改吃这里（原来只数当前页 items，豁免重放/跨页勾选时
            # 目标行不在当前页就漏报「其实会被藏住」）。失败条不回（提示只数 ok 条）。
            "is_recommended": bool(summary.is_recommended),
            # R-6：一致性这类**预警**不拦人，但必须让审核人看到「过了、只是有预警」，
            # 否则留痕列 consistency_ok=false 就成了没人解释的红灯。
            "warnings": recheck_warnings,
            "superseded_productions": superseded,
        })

    await db.flush()
    await db.commit()

    # 批 J：审核 commit 完，把刚过审的文案排去备豆包提示词（用户口径：过审后提示词就
    # 备好、审核台直接能看）。排不上绝不能让审核整体报错——审核本身已经落库成功，
    # 预览只是搭车的。
    preview_note: Optional[str] = None
    if approved_now:
        kick = await _enqueue_preview(
            db, summary_ids=[str(s) for s in approved_now], operator=current_user,
        )
        preview_note = kick.get("note") if not kick.get("queued") else None

    ok = sum(1 for r in results if r["ok"])
    waived_cnt = sum(1 for r in results if r.get("waived"))
    warn_cnt = sum(1 for r in results if r["ok"] and r.get("warnings"))
    return {
        "results": results,
        "prompt_preview_note": preview_note,
        "message": (
            f"审核完成：成功 {ok} 条，未通过 {len(results) - ok} 条（未通过原因见 results）"
            + (f"，其中 {waived_cnt} 条为管理员豁免（已入审计，admin 可抽检）" if waived_cnt else "")
            + (f"；{warn_cnt} 条带预警（与反推详规对不上，不拦过审但请复核一眼）" if warn_cnt else "")
            + (
                f"；{len(approved_now)} 条过审文案的豆包提示词正在后台备好（稍后在文案上看预览）"
                if approved_now and not preview_note else ""
            )
            + (f"；{preview_note}" if preview_note else "")
        ),
    }


class SummaryPromptWebRequest(BaseModel):
    """11-06 双产出补口：给 doubao_prompt 缺失（或要求重出）的候选补网页版提示词。"""
    summary_ids: List[str] = Field(default_factory=list)
    force: bool = Field(False, description="true=已有提示词的也重出（默认只补缺的）")


@router.post("/assets/summaries/prompt-web")
async def prompt_web_summaries(
    data: SummaryPromptWebRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """单独补/重出某几条候选的豆包网页版完整提示词。

    出文案时第二跳失败只记条目不回滚（文案是真金白银换来的，别跟提示词绑死一条命），
    缺的就用这个口补。单次上限 = ASSET_SUMMARY_MAX_PER_CALL（与出文案同一类
    「别让一次点击干太多」的闸）；每条一次模型调用，同步等。
    """
    if not data.summary_ids:
        raise HTTPException(status_code=400, detail="请点名要补提示词的文案（summary_ids）")
    cap = max(1, int(settings.ASSET_SUMMARY_MAX_PER_CALL))
    if len(data.summary_ids) > cap:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多补 {cap} 条（每条都是一次真模型调用），分几批来",
        )
    uuids: List[uuid.UUID] = []
    for raw_id in data.summary_ids:
        try:
            uuids.append(uuid.UUID(str(raw_id)))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail=f"文案 id 不合法：{raw_id}")
    rows = (
        await db.execute(
            select(AssetSummary).where(AssetSummary.id.in_(uuids)).order_by(AssetSummary.asset_id, AssetSummary.seq)
        )
    ).scalars().all()
    found = {str(s.id) for s in rows}
    results: List[dict] = []
    skipped_missing = [str(x) for x in data.summary_ids if str(x) not in found]
    if skipped_missing:
        results.append({"summary_id": skipped_missing[0], "error": f"找不到这条文案（共 {len(skipped_missing)} 条 id 无效）"})

    filled = 0
    for s in rows:
        asset = (
            await db.execute(select(AssetItem).where(AssetItem.id == s.asset_id))
        ).scalar_one_or_none()
        entry: dict = {"summary_id": str(s.id), "code": asset.code if asset else None, "seq": s.seq}
        if asset is None:
            entry["error"] = "所属素材已删除，没法补"
            results.append(entry)
            continue
        if (s.doubao_prompt or "").strip() and not data.force:
            entry["note"] = "已有网页版提示词，未重出（要重出请带 force=true）"
            results.append(entry)
            continue
        if asset.media_kind == MEDIA_IMAGE:
            entry["error"] = _image_block_reason(asset, "补提示词")
            results.append(entry)
            continue
        script = await _prompt_script_of(db, asset)
        if not script:
            entry["error"] = "反推脚本尚未就绪，没法展开提示词"
            results.append(entry)
            continue
        # 外部调用前结束事务（idle_in_transaction 60s 铁律）
        await db.commit()
        try:
            web = await _call_autoclip(
                "hook-copy/prompt-web",
                {
                    "script": script,
                    "candidates": [{"seq": s.seq, "text": s.text, "formula_tag": s.formula_tag or ""}],
                    "max_retries": 1,
                    "params": {
                        "drama_title": await _drama_title_of(db, asset),
                        "compliance": "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
                        **({"duration_seconds": int(round(asset.duration))} if asset.duration else {}),
                    },
                },
            )
        except HTTPException as exc:
            entry["error"] = f"网页版提示词生成失败：{str(exc.detail)[:200]}"
            results.append(entry)
            continue
        prompt_text = ""
        for p in web.get("prompts") or []:
            if int(p.get("seq") or 0) == int(s.seq) or not prompt_text:
                t = str(p.get("prompt_text") or "").strip()
                if t:
                    prompt_text = t
                if int(p.get("seq") or 0) == int(s.seq):
                    break
        if not prompt_text:
            entry["error"] = "模型没返回可用段落，重试一次或换批再补"
            results.append(entry)
            continue
        s.doubao_prompt = prompt_text
        filled += 1
        entry["ok"] = True
        results.append(entry)

    if filled:
        await _write_audit(
            db,
            action="asset.summary_prompt_web",
            operator=current_user,
            target_type="asset_summary",
            target_id=None,
            after={"requested": len(data.summary_ids), "filled": filled, "force": data.force},
        )
        await db.commit()
    return {
        "results": results,
        "filled": filled,
        "message": f"补上 {filled} 条豆包网页版提示词"
        + (f"，{len(results) - filled} 条没补成（原因见明细）" if len(results) > filled else ""),
    }


@router.post("/assets/summaries/resubmit")
async def resubmit_summaries(
    data: ResubmitRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """改后重新提审：被驳回 / 需改写的文案，改完交回待审队列。

    这是 11-04 用户问出来的缺口：原来驳回之后**文案作者没有任何入口**——
    要么审核人自己「改后过」，要么整批重新出文案（再花钱）。
    现在作者可以改了直接交回来，审核人重新过一遍。

    三条规矩：
    1. **状态门槛**：只有 rejected / need_rewrite 能重提（待审的本来就在队列里）。
    2. **权限门槛**：这条素材的负责人（导入人，＝出文案的人）或 admin。审核人不
       能自己给自己擦屁股——那和生产者不得自审是同一条线。
    3. **硬闸门照旧**：形态（超字数/首句过长/结尾悬空）与 block 级风险词当场拦下，
       改完再提也得干净；**一致性只留痕不拦**（那是审核人的判断，且过审时还会再校一次）。
    改前改后都进 AuditLog，admin 可抽检；文案本身的改前原文留在 text_before_edit。
    """
    if not data.summary_ids:
        raise HTTPException(status_code=400, detail="请选择要重新提审的文案")

    is_admin = current_user.role == UserRole.admin.value
    book, exemptions = await _risk_lexicon(db)
    results: List[dict] = []

    for sid in data.summary_ids:
        uuid_s = _as_uuid(sid, "summary_id")
        summary = (
            await db.execute(select(AssetSummary).where(AssetSummary.id == uuid_s))
        ).scalar_one_or_none()
        if summary is None:
            results.append({"summary_id": str(uuid_s), "ok": False, "error": "文案不存在"})
            continue
        asset = await _get_asset_or_404(db, summary.asset_id)

        if not _can_resubmit(summary, asset, current_user):
            if summary.audit_status not in (RV_REJECTED, RV_NEED_REWRITE):
                results.append({
                    "summary_id": str(uuid_s), "ok": False, "code": asset.code,
                    "error": f"只有被驳回/需改写的文案能重新提审（当前 {summary.audit_status}）",
                })
            else:
                results.append({
                    "summary_id": str(uuid_s), "ok": False, "code": asset.code,
                    "error": "只有这条素材的负责人（导入人）或管理员能改后重新提审",
                })
            continue

        before = {
            "audit_status": summary.audit_status,
            "text": summary.text,
            "reject_reason": summary.reject_reason,
        }
        new_text = (data.new_text or "").strip()
        # 先在**候选文本**上过闸门，一个字都还没落库：没过就原样退回，
        # 作者原来的文案不能被一次失败的提交改掉（11-04 现网验收实测踩到）。
        candidate = new_text if new_text else (summary.text or "").strip()
        if not candidate:
            results.append({"summary_id": str(uuid_s), "ok": False, "code": asset.code, "error": "文案不能为空"})
            continue

        # 硬闸门：与 /review、/produce **同一套口径**（R-6）——recheck_copy 默认只把
        # 形态和 block 级风险词算进 problems，一致性掉到 warnings 里留痕不拦。
        # 所以这里直接信 verdict["ok"]，不再自己按 code 挑挑拣拣：三个入口曾经因为
        # 各自过滤（这里手动滤 consistency、审核当硬闸拦）而严度不一，同一条文案
        # 「提审能过、投产被拒」。
        script = await _prompt_script_of(db, asset)
        verdict = svc.recheck_copy(candidate, script, lexicon=book, exemptions=exemptions)
        if not verdict["ok"]:
            results.append({
                "summary_id": str(uuid_s), "ok": False, "code": asset.code,
                "error_code": "ASSET_RECHECK_FAILED",
                "problems": verdict["problems"],
                "error": "复核未过：" + "；".join(p["message"] for p in verdict["problems"])
                         + "（先改干净再提审）",
            })
            continue

        # 过了闸门才落库：原留档，改后写正
        if new_text and new_text != summary.text:
            summary.text_before_edit = summary.text
            summary.text = new_text
        elif not (summary.text or "").strip():
            summary.text = new_text
        text = summary.text.strip()

        summary.word_count = verdict["chars"]
        summary.risk_hit = svc.format_risk_hits(verdict["risk"])
        consist = verdict["consistency"]
        if consist is not None:
            summary.consistency_ok = consist["ok"]
            summary.consistency_note = (
                None if consist["ok"] and consist.get("note") is None
                else (consist.get("note") or f"实体未命中：{'、'.join(consist['missing'])}")[:300]
            )

        # 回队列：清掉上一轮的审核痕迹（理由留在 AuditLog 里，不丢）
        summary.audit_status = RV_PENDING
        summary.reviewed_by = None
        summary.reviewed_at = None
        summary.reject_reason = None
        # P1（评审定稿⑩）：作者写给审核人的说明落列持久化——此前只进审计，审核人看不见
        summary.resubmit_note = (data.note or "").strip() or None
        summary.updated_at = datetime.utcnow()

        # 素材概要态回写：这条退回待审了，本素材是否还有过审文案要重新数一遍
        approved_cnt = (
            await db.execute(
                select(func.count(AssetSummary.id)).where(
                    AssetSummary.asset_id == asset.id,
                    AssetSummary.audit_status.in_(REVIEW_PASSED_STATES),
                )
            )
        ).scalar_one()
        asset.has_approved_copy = approved_cnt > 0
        # 阶段列一起收敛（对照审核路径 `:2628` 同一行）：原来只改了 has_approved_copy，
        # `stage_summary` 留在上一轮的值上 → 按阶段筛选/`derive_status` 算出来的整条状态
        # 跟文案实际所处的环节对不上，列表里会出现「文案阶段=失败但候选就在待审队列」这种矛盾行。
        svc.apply_stage(asset, "summary", STAGE_SUCCESS, has_approved_copy=asset.has_approved_copy)

        await _write_audit(
            db,
            action="asset.summary_resubmit",
            operator=current_user,
            target_type="asset_summary",
            target_id=summary.id,
            before=before,
            after={
                "audit_status": summary.audit_status,
                "text": summary.text,
                "note": (data.note or "").strip()[:500] or None,
                "consistency_ok": summary.consistency_ok,
                "risk_hit": summary.risk_hit,
            },
        )
        results.append({
            "summary_id": str(uuid_s), "ok": True, "code": asset.code,
            "audit_status": RV_PENDING, "text": summary.text,
            # 预警（一致性）随结果回给作者：不拦提审，但要让人知道审核人会看到这条提示
            "warnings": list(verdict.get("warnings") or []),
        })

    await db.flush()
    await db.commit()
    ok = sum(1 for r in results if r["ok"])
    return {
        "results": results,
        "message": (
            f"重新提审：成功 {ok} 条，已交回待审队列"
            + (f"，未通过 {len(results) - ok} 条（原因见 results）" if ok < len(results) else "")
        ),
    }


# ──────────────────────────────────────────────
# 生产单（过审文案 × N 条差异化提示词）
# ──────────────────────────────────────────────

# ── 角色卡（批 G，11-04 拍板③ / 11-05 做完）：多卡保序 + 逐项取图 ──────────────────
# 旧形状只有一个 `character_card_key`：值由前端**手填**（ProduceOrderModal 那个
# 「角色卡编号」输入框），后端直接当 MinIO key 用。填错一个字符的后果是：任务照建、
# picDatas 是空的、画中人全靠模型自由发挥，而台账上一切正常——「上下集换装」历史上
# 就是这么来的。这批把"手填 key"换成"从素材库挑图"，并且支持一部剧多张卡
# （男女主各一张），板侧按数组顺序理解主次，所以**顺序是数据的一部分**，不是显示细节。


def _resolution_wh(resolution: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """`asset_items.resolution`（入库时 ffprobe 量出来的 "720x1280"）→ (宽, 高)。
    量不到 / 老数据没这格式 → (None, None)，调用方按"不知道画幅"处理，**不许猜**。
    """
    s = (resolution or "").strip().lower().replace("×", "x")
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", s)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _card_ratio_fields(resolution: Optional[str]) -> Dict[str, Any]:
    """给一张卡补上画幅三字段（ratio / orientation / 人话 hint）。缺了它，
    导出侧只能显示"有一张卡"，显示不出"这张会把成片压成横屏"。
    """
    w, h = _resolution_wh(resolution)
    asp = svc.image_aspect(w, h)
    return {"width": w, "height": h, "ratio": asp["ratio"], "orientation": asp["orientation"]}


async def _resolve_card_assets(
    db: AsyncSession, raw_ids: Optional[List[str]]
) -> List[AssetItem]:
    """挑卡入参 → 素材行，**顺序原样保留**（同 id 重复出现只留第一次）。

    三类脏输入当场 400 白话拒收，绝不允许静默变成"少一张卡"——少一张卡的任务
    照样投得出去，烧的是号池额度，而且没人知道：
      · id 不存在（含被删的素材）；
      · 那条不是图片：视频当角色卡＝投一张会动的图，板侧 picDatas 只收图片，
        失败报起来像坏文件，事后从生产单上看不出挂错了东西；
      · 图片没落进桶（`file_key` 为空＝链接形态或上传失败行）。
    """
    wanted: List[str] = []
    for raw in raw_ids or []:
        aid = str(raw or "").strip()
        if aid and aid not in wanted:
            wanted.append(aid)
    if not wanted:
        return []
    rows = list(
        (
            await db.execute(
                select(AssetItem).where(AssetItem.id.in_([uuid.UUID(x) for x in wanted]))
            )
        ).scalars().all()
    )
    by_id = {str(r.id): r for r in rows}
    cards: List[AssetItem] = []
    missing: List[str] = []
    for aid in wanted:
        a = by_id.get(aid)
        if a is None:
            missing.append(aid[:8])
            continue
        if (getattr(a, "media_kind", None) or MEDIA_VIDEO) != MEDIA_IMAGE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{a.code}（{a.file_name or '未命名'}）是视频，不能当角色卡：picDatas 只收图片。"
                    "要当卡用的话先把定妆照当图片传进素材库（导入口支持 .jpg/.jpeg/.png/.webp）"
                ),
            )
        if not a.file_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{a.code}（{a.file_name or '未命名'}）桶里没有文件（上传没成功或本来就是链接形态），"
                    "挑它当卡＝投一张读不到的图，先重新入库再投产"
                ),
            )
        cards.append(a)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"这些角色卡在素材库里找不到（id 前 8 位：{'、'.join(missing)}）："
                "多半是那条素材已被删除。刷新挑图列表重选，别拿旧弹窗里的快照投产"
            ),
        )
    return cards


def _card_shape_notes(cards: List[AssetItem]) -> List[dict]:
    """逐张卡的画幅判读（拍板③依据的是既有实测：**画幅由角色卡宽高比决定**，
    提示词里写 9:16 压不住一张横版三视图卡）。给挑卡处和投产响应显示，
    **只提醒不拦**——一线可能就想做横版，但那必须是他看见这条信息之后选的。
    """
    out: List[dict] = []
    for a in cards:
        fields = _card_ratio_fields(a.resolution)
        w, h = fields["width"], fields["height"]
        orientation, ratio = fields["orientation"], fields["ratio"]
        if orientation == "portrait":
            hint = f"这张 {ratio}（{w}×{h}）出竖屏"
        elif orientation == "landscape":
            hint = (
                f"这张是横版 {ratio}（{w}×{h}）：画幅由角色卡宽高比决定，"
                "提示词写 9:16 也压不住，投出去会是横屏"
            )
        elif orientation == "square":
            hint = f"这张是方图 {ratio}（{w}×{h}）：成片 720×1280 上下会留边"
        else:
            hint = "这张量不到尺寸（老数据或探失败）：画幅按模型默认走，投产前自己看一眼原图"
        out.append({
            "asset_id": str(a.id),
            "code": a.code,
            "file_name": a.file_name,
            "width": w,
            "height": h,
            "ratio": ratio,
            "orientation": orientation,
            "hint": hint,
        })
    return out


def _card_mixed_orientation_note(notes: List[dict]) -> Optional[str]:
    """多卡方向不一致 → 一句话点名。混着挂的后果不是"哪张算数"说不清，
    而是模型会在同一支片里换画幅，成片既不是竖屏也不是横屏。
    """
    kinds = [n["orientation"] for n in notes if n.get("orientation")]
    if len(set(kinds)) > 1:
        bad = "、".join(f"{n['code']}（{n['ratio']}）" for n in notes if n.get("orientation") == "landscape")
        return (
            f"这批卡方向不一致（{'、'.join(sorted(set(kinds)))}）：同一支片里换画幅，"
            f"成片会既不是竖屏也不是横屏。横版的那张：{bad or '见逐张提示'}"
        )
    return None


async def _card_sources_for(
    db: AsyncSession, rows: List[AssetProduction]
) -> Dict[str, List[Dict[str, Any]]]:
    """生产单 → **有序**取图清单（导出 N 张单只查一次 asset_items）。

    每条 `{"asset_id", "key", "bucket", "label", "legacy"}`。三种"取不到"分开列，
    为的是让导出侧能**点名**而不是给个空 picDatas：
      - 素材行没了（`asset_id` 有、查不到行）；
      - 素材行在但桶里没有 key；
      - 旧单只有 `character_card_key`（回退路径，key 直接可取）。
    """
    ids: set = set()
    for p in rows:
        for x in (p.card_asset_ids or []):
            if str(x or "").strip():
                ids.add(str(x).strip())
    by_id: Dict[str, AssetItem] = {}
    if ids:
        uuids = []
        for x in ids:
            try:
                uuids.append(uuid.UUID(x))
            except (ValueError, TypeError):
                continue  # 脏值留到下面按"取不到"点名，这里别炸整批导出
        if uuids:
            found = (
                await db.execute(select(AssetItem).where(AssetItem.id.in_(uuids)))
            ).scalars().all()
            by_id = {str(a.id): a for a in found}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for p in rows:
        refs: List[Dict[str, Any]] = []
        seen: set = set()
        for x in (p.card_asset_ids or []):
            aid = str(x or "").strip()
            if not aid or aid in seen:
                continue
            seen.add(aid)
            a = by_id.get(aid)
            if a is None:
                refs.append({
                    "asset_id": aid, "key": None, "bucket": None,
                    "label": f"素材 {aid[:8]}（行已不在库里，卡取不到）",
                })
                continue
            if not a.file_key:
                refs.append({
                    "asset_id": aid, "key": None, "bucket": None,
                    "label": f"{a.code}（{a.file_name or '未命名'}）桶里没有文件",
                })
                continue
            refs.append({
                "asset_id": aid, "key": a.file_key,
                "bucket": a.bucket or settings.MINIO_BUCKET_RAW,
                "label": f"{a.code}（{a.file_name or '未命名'}）",
                "resolution": a.resolution,
                **_card_ratio_fields(a.resolution),
            })
        if not refs and p.character_card_key:
            # ⚠️ 回退只认"数组为空"这一种情况。卡片数组非空但里面有坏项时**不回退**：
            # 那种单是新前端建的，作者看到的是一张挑坏了的卡，偷偷把旧 key 塞回去
            # 等于替他改了输入。
            refs.append({
                "asset_id": None, "key": p.character_card_key,
                "bucket": settings.MINIO_BUCKET_RAW,
                "label": f"旧口径单值 key `{p.character_card_key}`",
                "legacy": True,
            })
        out[str(p.id)] = refs
    return out


@router.get("/assets/hook-codes/used")
async def hook_codes_used(
    codes: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """11-06 拍板③：生产单弹窗回显「这些编号里哪些已经被用掉」。

    `codes` 逗号分隔的五位编号；只读、0 元。`used` 每项带它钉在哪条素材的
    哪张单上（含单子状态），前端在输入框下当场亮红——比提交后才 400 顺手。
    取号本身仍走共享盘的 hook_id.py，本口不代取、不预占任何号。
    """
    wanted = [c.strip().upper() for c in (codes or "").split(",") if c.strip()][:100]
    if not wanted:
        return {"used": []}
    rows = list(
        await db.execute(
            select(AssetProduction.hook_code, AssetProduction.seq, AssetProduction.status, AssetItem.code)
            .join(AssetItem, AssetItem.id == AssetProduction.asset_id)
            .where(AssetProduction.hook_code.in_(wanted))
        )
    )
    return {
        "used": [
            {"code": c, "asset_code": ac, "seq": seq, "status": st}
            for c, seq, st, ac in rows
        ]
    }


@router.post("/assets/summaries/hook-codes")
async def park_hook_codes(
    data: HookCodeParkRequest,
    current_user: Annotated[User, Depends(require_roles(*_REVIEW_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """把 hook_id.py 取来的号**提前钉**在文案上（或补钉在已建好的生产单上）。11-09 批 N，
    用户口径「现有已经导入的那些文案，你都去取一个编号放着吧」。

    为什么要这个口：取号是外部动作（共享台账、一发即烧），过去只能在开单那一屏现取现贴。
    批量导入的 85 条要每条手动粘一遍，慢一步还得回服务器重取。号先钉在 `asset_summaries.hook_code`
    上等着，开单时后端自动顶到缺号的槽位（见 `create_productions` 的 parked_code），顶掉当场清空。

    两种行，各自口径：
    - `summary_id` ＋ 号＝预取；号被某张单吃掉后预取位自动空出来，同一个号绝不会被第二次开单复用。
    - `production_id` ＋ 号＝**补号**：建单时没带号、后来才拿到号那种。段头/推荐标题/产出清单三处
      编号都是**导出与投板时**按 `p.hook_code` 现拼的（`format_export_block`），不写在提示词正文里，
      所以补在还没上板的单上是全_effective_的；已经上了板（`board_tid` 有值）就**拒绝**——
      板面任务名与回收对账都按老号钉死了，这里改一下就会对不上账。
    - `hook_code` 留空＝清位（清生产单同样要求没上板）。

    判据与开单口共用一条尺：五位 `is_valid_hook_code`、批内不许重号、
    已经被哪张单用掉的号不许再钉（拍板③ 一钩一号）。写 AuditLog（`asset.hook_code.park`，
    逐行 before/after）——号是烧掉的东西，谁钉的、钉之前挂着什么，必须查得回来。
    """
    items = data.items or []
    if not items:
        raise HTTPException(status_code=400, detail="请至少点名一行（summary_id 或 production_id ＋ 号）")
    cap = int(settings.ASSET_IMPORT_BATCH_MAX)
    if len(items) > cap:
        raise HTTPException(status_code=400, detail=f"单次最多钉 {cap} 行，当前 {len(items)} 行——分批钉")

    summary_ids: List[str] = []
    production_ids: List[str] = []
    wanted: List[str] = []
    parsed: List[dict] = []
    for idx, it in enumerate(items):
        sid = str(it.summary_id or "").strip()
        pid = str(it.production_id or "").strip()
        if bool(sid) == bool(pid):
            raise HTTPException(
                status_code=400,
                detail=f"第 {idx + 1} 行要**二选一**：给 summary_id（预取到文案）或给 production_id（补号到生产单）",
            )
        code = str(it.hook_code or "").strip().upper() or None
        if code and not svc.is_valid_hook_code(code):
            raise HTTPException(
                status_code=400,
                detail=f"第 {idx + 1} 行的钩子编号 {it.hook_code!r} 不合法：必须是五位 0-9A-Z，"
                       "用 hook_id.py 取号，禁止手编",
            )
        if code:
            wanted.append(code)
        row = {"summary_id": sid, "production_id": pid, "code": code}
        parsed.append(row)
        (summary_ids if sid else production_ids).append(sid or pid)
    if len(set(wanted)) != len(wanted):
        raise HTTPException(status_code=400, detail="同一次提交里有重号：一钩一号，一个号只能钉一行")

    s_uuids = [_as_uuid(x, "summary_id") for x in dict.fromkeys(summary_ids)]
    p_uuids = [_as_uuid(x, "production_id") for x in dict.fromkeys(production_ids)]
    summaries = {
        str(r.id): r
        for r in (await db.execute(select(AssetSummary).where(AssetSummary.id.in_(s_uuids)))).scalars().all()
    } if s_uuids else {}
    productions = {
        str(r.id): r
        for r in (await db.execute(select(AssetProduction).where(AssetProduction.id.in_(p_uuids)))).scalars().all()
    } if p_uuids else {}
    not_found = [
        row["summary_id"] or row["production_id"] for row in parsed
        if (row["summary_id"] and row["summary_id"] not in summaries)
        or (row["production_id"] and row["production_id"] not in productions)
    ]

    # 这批要钉的号现在的真实去向：钉在哪张单上、钉在哪条文案的预取位上（都只查一次，不在行循环里打）
    used_on: Dict[str, str] = {}
    parked_on: Dict[str, str] = {}
    if wanted:
        rows = list(
            await db.execute(
                select(AssetProduction.hook_code, AssetProduction.seq, AssetItem.code)
                .join(AssetItem, AssetItem.id == AssetProduction.asset_id)
                .where(AssetProduction.hook_code.in_(wanted))
            )
        )
        used_on = {c: f"素材 {ac} 的第 {seq} 张单" for c, seq, ac in rows}
        rows2 = list(
            await db.execute(
                select(AssetSummary.hook_code, AssetItem.code)
                .join(AssetItem, AssetItem.id == AssetSummary.asset_id)
                .where(AssetSummary.hook_code.in_(wanted))
            )
        )
        parked_on = {c: f"素材 {ac} 的预取位" for c, ac in rows2}

    changed_summaries: List[dict] = []
    changed_productions: List[dict] = []
    skipped: List[dict] = []
    conflicts: List[dict] = []
    for row in parsed:
        code = row["code"]
        if row["summary_id"]:
            s = summaries.get(row["summary_id"])
            if s is None:
                continue
            if (s.hook_code or None) == code:
                skipped.append({"kind": "summary", "id": row["summary_id"], "hook_code": code,
                                "reason": "同态幂等：预取位已经是这个号"})
                continue
            # 走到这里 `s.hook_code != code`，所以 parked_on 里若还有这个号，占位的一定是别条文案
            if code and used_on.get(code):
                conflicts.append({"kind": "summary", "id": row["summary_id"], "hook_code": code,
                                  "reason": f"这个号已经用在{used_on[code]}上，一钩一号不许再钉"})
                continue
            if code and parked_on.get(code):
                conflicts.append({"kind": "summary", "id": row["summary_id"], "hook_code": code,
                                  "reason": f"这个号已经挂在{parked_on[code]}上，一个号只能占一个预取位"})
                continue
            changed_summaries.append({"id": row["summary_id"], "before": s.hook_code, "after": code})
            s.hook_code = code
        else:
            p = productions.get(row["production_id"])
            if p is None:
                continue
            if p.board_tid:
                conflicts.append({"kind": "production", "id": row["production_id"], "hook_code": code,
                                  "reason": "这张单已经投上后台任务板（板面任务名与回收对账都按当时的号钉死），"
                                            "编号改不得——要换号请重开一张单"})
                continue
            if (p.hook_code or None) == code:
                skipped.append({"kind": "production", "id": row["production_id"], "hook_code": code,
                                "reason": "同态幂等：这张单已经是这个号"})
                continue
            # 号钉在**这张单自己**名下不可能出现在 used_on（那行 hook_code 是空才会走到补号），
            # 所以 used_on 命中就是别处已经用了这个号，直接点名
            if code and used_on.get(code):
                conflicts.append({"kind": "production", "id": row["production_id"], "hook_code": code,
                                  "reason": f"这个号已经用在{used_on[code]}上，一钩一号不许再钉"})
                continue
            changed_productions.append({"id": row["production_id"], "before": p.hook_code, "after": code})
            p.hook_code = code

    await db.flush()
    # 只在**真改了东西**时留痕：全批同态/全批冲突也写一条审计，会把「谁在什么时刻真的动过号」
    # 淹成一片重复记录——号是要烧的东西，审计的价值在变化点，不在调用点。
    if changed_summaries or changed_productions:
        await _write_audit(
            db,
            action="asset.hook_code.park",
            operator=current_user,
            target_type="asset_hook_code",
            target_id="asset_hook_code",
            before={"summaries": [{"id": c["id"], "hook_code": c["before"]} for c in changed_summaries],
                    "productions": [{"id": c["id"], "hook_code": c["before"]} for c in changed_productions]},
            after={"summaries": [{"id": c["id"], "hook_code": c["after"]} for c in changed_summaries],
                   "productions": [{"id": c["id"], "hook_code": c["after"]} for c in changed_productions],
                   "conflicts": conflicts, "skipped": skipped},
        )
    notes: List[str] = []
    if not_found:
        notes.append(f"这些 id 在库里查不到，已跳过：{', '.join(not_found[:5])}"
                     + (f"（共 {len(not_found)} 个）" if len(not_found) > 5 else ""))
    if conflicts:
        notes.append("；".join(c["reason"] for c in conflicts[:5])
                     + (f"；另有 {len(conflicts) - 5} 行同因没钉上" if len(conflicts) > 5 else ""))
    return {
        "ok": not not_found and not conflicts,
        "summary_parked": sum(1 for c in changed_summaries if c["after"]),
        "summary_cleared": sum(1 for c in changed_summaries if not c["after"]),
        "production_filled": sum(1 for c in changed_productions if c["after"]),
        "production_cleared": sum(1 for c in changed_productions if not c["after"]),
        "skipped": skipped,
        "conflicts": conflicts,
        "not_found": not_found,
        "notes": notes,
    }


def _element_fanout_rows(
    base_row: Dict[str, Any],
    catalog: List[Dict[str, Any]],
    base_values: Dict[str, str],
    matrix_rows: List[Dict[str, str]],
    category: Optional[str],
    codes: List[Optional[str]],
    labels: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """批 P（11-10）：一份展开好的正文 × 用户填的多组参数值 → N 份投递稿。

    **不调模型、不花钱**：走的是 8-14 那套字面替换引擎（`compose_variants`），
    每一行都从模型展开出来的**同一份原稿**出发，所以第 2 个场景不会盖掉第 1 个场景。

    编号是每行自己的：模型把编号写进了推荐标题与段头那行，所以第 j 份要把正文里出现的
    "基准号"整个字面换成这一行的号。不换的后果是两张单带着同一个标题投上同一块板——
    板面按标题回收，两条产物会挂到同一张单上（11-05 现网真踩过的对账坑）。
    号不够时留空（照今天的口径：缺号在结果里点名，导出时标缺），绝不后端自编。

    返回 `(行, 备注)`；备注只在"这一行其实没换动"时才有内容——换不动要说出来，
    不能让人以为 20 条里每条都换了场景。
    """
    src_code = str(base_row.get("hook_code") or "")
    base_titles = list(base_row.get("video_titles") or [])
    out: List[Dict[str, Any]] = []
    notes: List[str] = []
    for variant in pesvc.compose_variants(
        base_row.get("prompt_text"), catalog, base_values, matrix_rows, category
    ):
        idx = int(variant["seq"])
        code = codes[idx - 1] if idx - 1 < len(codes) else None
        text = variant["text"]
        titles = base_titles
        # ⚠️ 判据是「这一行的号和基准号不一样」，**不是**「不是第 1 行」：n×K 摊开时
        # 第 vi 份的底稿带着 codes_for_summary[vi] 那个号，而它扇出来的 K 张占的是
        # vi*K..vi*K+K-1 ——除了 vi=0 以外第 1 行就已经要换号了，按 idx>1 判会漏换，
        # 漏换的结果正是本函数开头写的那条坑：两张单同名投上同一块板。
        if src_code and code != src_code:
            if code:
                text = text.replace(src_code, code)
                titles = [str(t or "").replace(src_code, code) for t in base_titles]
            elif idx > 1:
                # 号不够：正文里仍留着别的单的号。不悄悄留，也不硬删（删了标题会变成半截话），
                # 当场点名让一线补够号再来——今天「缺号能建单」的口径不变，但扇出时后果更重。
                notes.append(
                    f"第 {idx} 条没分到钩子编号，正文/标题里仍带着 {src_code}（那张号是别的单的）："
                    f"补够 {len(codes)} 个号再来，否则投上板会重名、回收对不上账"
                )
        combo = "、".join(f"{labels.get(k) or k}={v}" for k, v in (variant["values"] or {}).items())
        row = dict(base_row)
        row.update({
            "prompt_text": text,
            "hook_code": code,
            # 板上 name 取的是 video_titles[0]（B-5），标题里那句编号必须跟着换，
            # 只换 prompt_text 等于台账改了、板面还是重名。
            "video_titles": titles or None,
            # 差异来源必须写进单子上：事后拿着这张单要能回答"这条和旁边那条差在哪"。
            # 列是 String(120)，超了截断（截断只发生在极端长的词表上，不影响判读）。
            "variant_basis": f"{base_row.get('variant_basis') or ''}｜{combo}"[:120],
        })
        out.append(row)
        if variant["missing"]:
            notes.append(
                f"第 {idx} 条（{combo}）这些参数原稿里没认出值、这条没换："
                + "、".join(variant["missing"]) + "（手填项要自己从稿子里复制原句）"
            )
        elif not variant["changed"] and idx > 1:
            notes.append(f"第 {idx} 条（{combo}）正文和原稿一模一样：填的值和原值相同，或词面在稿子里没出现")
    return out, notes


@router.post("/assets/produce")
async def create_productions(
    data: ProduceRequest,
    current_user: Annotated[User, Depends(require_functions("produce"))],
    db: AsyncSession = Depends(get_db),
    _role_gate: User = Depends(require_roles(*_REVIEW_ROLES)),
):
    """过审文案 → N 条生产单（本口**只建 order_ready 单**，一毛不花也不占号池；
    往板上投是下一步：批 H 起有 `POST /assets/productions/dispatch`（机器连板、逐批人工确认），
    或照旧导出 payload 人工投完走 `POST /assets/productions/status` 回写投递态）。

    N 的语义（2026-11-03 定稿）：同一条过审文案派生 **N 条差异化提示词**
    （句式轮换 / 换角色卡 / 镜头重排…），**不是**把同一条重复投 N 次——
    重复投喂产物近似且白烧额度。差异来源记在每条的 variant_basis。

    ⚠️ **N 与板上 total 是两个量**（B-1）：板上 `total`＝同一条 prompt 出几版（后台给
    每版派不同豆包号）。所以一批 N 份＝**N 个任务、每个 board_total 默认 1**；若把 N 直接
    填进 total，同一批会白烧 N×N 的量。要"一条出 2~3 版挑最好"请用 board_total。

    prompt_snapshot 冻结过审文案；展开后的提示词若与快照对不上（模型改词），
    标 drift=true 不静默——「审的」和「生产的」必须能对上。

    板上 `name` 取**推荐视频标题第 1 条**（11-02 版权威：1020 起项目标题行已取消），
    `board_date` 由后端生成完整时间戳，`hook_code` 只能来自取号工具（后端绝不编号）。
    """
    if not data.summary_ids:
        raise HTTPException(status_code=400, detail="请选择已过审的文案")
    # 只有**没传**才用默认值：`data.n or DEFAULT` 会把 n=0 静默变成 3，
    # 而 0 恰恰是「我要取消这批」的输入，必须明确报错而不是偷偷开工。
    n = int(settings.ASSET_PRODUCE_DEFAULT_N if data.n is None else data.n)
    if n < 1:
        raise HTTPException(status_code=400, detail="生产数量至少 1 条")
    if n > int(settings.ASSET_PRODUCE_MAX_N):
        raise HTTPException(
            status_code=400,
            detail=f"单条文案最多派生 {settings.ASSET_PRODUCE_MAX_N} 份（防误填把号池额度一天烧光），请分批",
        )
    channel = data.channel or DEFAULT_PRODUCTION_CHANNEL
    if channel not in PRODUCTION_CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel 只支持 {'/'.join(PRODUCTION_CHANNELS)}")

    # B-4：这条通道**没有时长参数**，payload 七键里一个都改不了出片规格。
    # 放任用户填 15/20 只会给出错误的操作预期（豆包的做法是加快语速而不是删词）。
    duration = data.duration
    board_out_seconds = int(round(settings.ASSET_BOARD_OUTPUT_SECONDS))
    if channel == CH_WEWORK_AIVIDEO:
        if duration is None:
            duration = board_out_seconds
        if int(duration) != board_out_seconds:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"后台任务板出片恒 {settings.ASSET_BOARD_OUTPUT_SECONDS}s / "
                    f"{settings.ASSET_BOARD_OUTPUT_RESOLUTION}，接口没有时长开关——提示词写「15 秒」不生效"
                    "（实测豆包是加快语速而不是删词）。要更长的内容请拆**上集/下集两条**（每条 10s），"
                    "推荐视频标题带（上集）/（下集），编号连续两个。"
                ),
            )

    # B-1：板上 total 与 n 分列
    board_total = int(settings.ASSET_BOARD_DEFAULT_TOTAL if data.board_total is None else data.board_total)
    total_cap = int(settings.ASSET_BOARD_TOTAL_MAX)
    if not 1 <= board_total <= total_cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"board_total（**同一条提示词出几版**）只支持 1..{total_cap}（接口层就是 min1/max20）。"
                f"注意它和 n（几条差异化提示词）是两个量：n 份 → n 个任务，每任务 total={board_total}，"
                f"本批实际投放量 = n × board_total。"
            ),
        )

    # 五位钩子编号：只接受 hook_id.py 取来的号，后端不自己编（多人在共享盘取号，手编必撞码）
    hook_codes: List[str] = []
    if data.hook_codes:
        for raw in data.hook_codes:
            code = str(raw or "").strip().upper()
            if not code:
                continue
            if not svc.is_valid_hook_code(code):
                raise HTTPException(
                    status_code=400,
                    detail=f"钩子编号 {raw!r} 不合法：必须是五位 0-9A-Z（日期2位base36+剧码2位+当日序号1位），用 hook_id.py 取号，禁止手编",
                )
            hook_codes.append(code)
        if len(set(hook_codes)) != len(hook_codes):
            raise HTTPException(status_code=400, detail="钩子编号重复，一钩一号")

        # 11-06 拍板③：已用号当场拦。号是共享盘 hook_id.py 发出去的，一发就烧掉——
        # 哪怕挂着号的那张单后来作废了，重用同一个号也可能让板面出现两条同名任务、
        # 回收时对不上账。在这里点名「这个号已经钉在哪条素材的哪张单上」，
        # 比等导出/投板时才发现对不上账再返工便宜得多。取号仍走 hook_id.py，后端不代取。
        used = list(
            await db.execute(
                select(AssetProduction.hook_code, AssetProduction.seq, AssetItem.code)
                .join(AssetItem, AssetItem.id == AssetProduction.asset_id)
                .where(AssetProduction.hook_code.in_(hook_codes))
            )
        )
        if used:
            shown = "；".join(f"{c}（已钉在素材 {ac} 的第 {seq} 张单上）" for c, seq, ac in used[:8])
            more = f"；另有 {len(used) - 8} 张没列出" if len(used) > 8 else ""
            raise HTTPException(
                status_code=400,
                detail=f"这些钩子编号已经被用掉了：{shown}{more}。一钩一号，回 hook_id.py 重新取号再投产",
            )

    board_tag = (data.board_tag or settings.ASSET_BOARD_TAG).strip()[:60]
    # B-2：date 由后端生成（绝不用前端传的日期），并折算成板面本地时间
    board_date = svc.board_timestamp(tz_offset_hours=settings.ASSET_BOARD_TZ_OFFSET_HOURS)
    # K＝该剧发布号数（11-02 版：推荐标题条数不再固定 5）
    title_count = data.recommended_title_count
    if title_count is not None and not 1 <= int(title_count) <= 20:
        raise HTTPException(status_code=400, detail="K（推荐标题条数=该剧发布号数）只支持 1..20")

    # 批 G：角色卡在**排后台任务之前**就判完。脏卡 id 必须当场 400——不能让用户点了
    # 「投产」收到一个"已受理"，几分钟后才在任务详情里看到"卡取不到"，那时候
    # 钩子编号已经发出去了。
    cards = await _resolve_card_assets(db, data.card_asset_ids)
    card_ids = [str(a.id) for a in cards]
    card_notes = _card_shape_notes(cards)
    # 兼容写：单值列继续有值（旧前端、旧导出、任何只看 `character_card_key` 的读侧都不许
    # 因为新前端改传数组就读不到卡）。多卡时写第一张——它就是 picDatas 的第一项，语义上是主卡。
    card_key = (cards[0].file_key if cards else None) or data.character_card_key or None

    # ── 批 P（11-10）：多值扇出——「一次填多个场景/动物 → 一次出多条钩子视频」 ──
    # ⚠️ 三个判据全排在 async_mode **之前**，理由与卡校验、跨人闸同一条先例：扇出来的每一条
    # 都要占一个钩子编号、投上板就是当天号池的一条额度。参数写错了却在几分钟后于后台任务
    # 详情里看到，人早走了，号也烧了。
    # 扇出本身**不调模型、不花钱**：它是在已经展开好的那份正文上做字面替换（引擎在
    # `asset_prompt_elements.compose_variants`），所以 `n`（差异化份数）与扇出行数是两个量，
    # 本批张数 = 文案数 × n × 扇出行数。
    element_rows: List[Dict[str, str]] = []
    element_catalog: List[Dict[str, Any]] = []
    element_labels: Dict[str, str] = {}
    element_notes: List[str] = []
    element_base = {
        str(k).strip(): str(v or "").strip()[: pesvc.MAX_MANUAL_VALUE_LEN]
        for k, v in (data.element_base or {}).items()
        if str(v or "").strip()
    }
    # 逐文稿的原值（批 P）：键用规范化后的 summary uuid 存，下面按 `str(uuid_s)` 取，
    # 免得前端传了带空格/大写形式就取不到、悄悄退回公共兜底那份。
    element_bases: Dict[str, Dict[str, str]] = {}
    for _sid_raw, _per in (data.element_base_by_summary or {}).items():
        _cleaned = {
            str(k).strip(): str(v or "").strip()[: pesvc.MAX_MANUAL_VALUE_LEN]
            for k, v in (_per or {}).items()
            if str(v or "").strip()
        }
        if _cleaned:
            element_bases[str(_as_uuid(_sid_raw, "summary_id"))] = _cleaned
    if data.element_values:
        element_catalog = await _prompt_element_catalog(db)
        element_labels = {s["key"]: s["label"] for s in element_catalog}
        try:
            element_rows, element_notes = pesvc.expand_matrix(
                data.element_values, data.element_mode or pesvc.MATRIX_ZIP, element_labels
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # 换上去的词当场按当前词表扫一遍：扇 10 条里有 1 条带高风险词，投到板上才发现
        # 就是白占 9 条之外的额度＋一个烧掉的号。这里整批不建单，改词再投（比事后逐张撤便宜）。
        _book0, _exempt0 = await _risk_lexicon(db)
        bad_words: List[str] = []
        for row in element_rows:
            for key, val in row.items():
                hits = svc.risk_block_hits(svc.scan_risk(val, lexicon=_book0, exemptions=_exempt0))
                if hits:
                    bad_words.append(
                        f"{element_labels.get(key) or key}「{val}」含高风险词 "
                        + "、".join(h["word"] for h in hits)
                    )
        if bad_words:
            raise HTTPException(
                status_code=400,
                detail=(
                    "这些替换词里有投板会被拦下的高风险词："
                    + "；".join(sorted(set(bad_words))[:6])
                    + "。换一批词，或者先去「风险词库」确认这个词到底要不要用"
                ),
            )
    # 一条文案扇出几张单（没填多值＝1，与今天完全同一条路径）
    fanout = max(1, len(element_rows))

    # A′（2026-11-07 按运营隔离）：归属跨人确认闸——投**别人过审**的候选要知情确认。
    # ⚠️ 必须在 async_mode 分支**之前**判：前端唯一真实路径是 async_mode=true（提交即回
    # 任务号），闸若放在分支之后，首呼会拿到 job ack、确认弹窗协议就断了（后台重放才
    # 撞 400，一线只看到任务失败）。与卡校验同一条先例：烧钱前当场判完。
    # 谁投账算谁（production.created_by 记实际投产人），候选过审人进审计；
    # 无主公共历史（reviewed_by IS NULL 的存量行）不拦——与钱闸「归属未知不预判」同口径。
    _pre_summaries: Dict[Any, Optional[AssetSummary]] = {}
    for sid in data.summary_ids:
        _u = _as_uuid(sid, "summary_id")
        _pre_summaries[_u] = (
            await db.execute(select(AssetSummary).where(AssetSummary.id == _u))
        ).scalar_one_or_none()
    # 批 N（11-09）：这批文案名下**预取好、还没用掉**的号，先集体查一次「是不是已经被别的单用掉了」。
    # 判据与请求体里手工粘来的号完全同一条（拍板③ 一钩一号），只是来源不同。为什么必须提前查、
    # 不等消费时再说：号一旦顶进某个槽，这张单就带着一个板面对不上账的号投出去了，
    # 到回收/对账时才炸——提前 400 点名比那便宜得多。一次 SELECT 查完，不在逐文案循环里打。
    parked_codes = sorted({s.hook_code for s in _pre_summaries.values() if s is not None and s.hook_code})
    if parked_codes:
        stale = list(
            await db.execute(
                select(AssetProduction.hook_code, AssetProduction.seq, AssetItem.code)
                .join(AssetItem, AssetItem.id == AssetProduction.asset_id)
                .where(AssetProduction.hook_code.in_(parked_codes))
            )
        )
        if stale:
            shown = "；".join(f"{c}（已钉在素材 {ac} 的第 {seq} 张单上）" for c, seq, ac in stale[:8])
            more = f"；另有 {len(stale) - 8} 个没列出" if len(stale) > 8 else ""
            raise HTTPException(
                status_code=400,
                detail=(
                    f"这几条文案名下预取的钩子编号已经被用掉了：{shown}{more}。"
                    "一钩一号，请把这批已开单投掉、或用 POST /assets/summaries/hook-codes "
                    "把预取位清空（hook_code 传 null）后重新取号"
                ),
            )
    cross_summaries = [
        s for s in _pre_summaries.values()
        if s is not None and s.audit_status in REVIEW_PASSED_STATES
        and s.reviewed_by is not None and str(s.reviewed_by) != str(current_user.id)
    ]
    self_summaries = [
        s for s in _pre_summaries.values()
        if s is not None and s.audit_status in REVIEW_PASSED_STATES
        and s.reviewed_by == current_user.id
    ]
    if cross_summaries and not data.cross_person_confirm:
        name_map = await _user_names(db, {s.reviewed_by for s in cross_summaries})
        code_map = dict(
            (
                await db.execute(
                    select(AssetItem.id, AssetItem.code).where(
                        AssetItem.id.in_({s.asset_id for s in cross_summaries})
                    )
                )
            ).all()
        )
        shown = "；".join(
            f"{code_map.get(s.asset_id, str(s.asset_id)[:8])}#{s.seq}（过审人 {name_map.get(str(s.reviewed_by), '未知')}）"
            for s in cross_summaries[:5]
        )
        more = f"（另有 {len(cross_summaries) - 5} 条，本条只列前 5 条）" if len(cross_summaries) > 5 else ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"投产涉及{_CROSS_OWNER_MARKER}：{shown}{more}。"
                "谁投账算谁（生产单记你名下、候选过审人留审计）——请确认确实是替同事补单/代班："
                "界面弹窗点「确认替他人投产」后再发一次（带 cross_person_confirm=true），这一次没有建单。"
            ),
        )

    if data.async_mode:
        # D-1：展开提示词要调模型（实测一次 9 分钟），同步等会一路撞上
        # 浏览器 960s / 后端 900s / nginx 的超时链，参数校验已经全过完了才排后台，
        # 所以"提交即回"回的是**已受理**，不是"大概能成"。
        job = await _start_asset_job(
            db,
            kind=JOB_PRODUCE,
            data=data,
            operator=current_user,
            batch_id=None,
            planned_units=len(data.summary_ids),
        )
        return _job_accepted(job, "生成生产单")

    productions: List[AssetProduction] = []
    results: List[dict] = []
    batch_codes: set = set()
    is_admin = current_user.role == UserRole.admin.value
    book, exemptions = await _risk_lexicon(db)
    recheck_failed: List[dict] = []
    waived_rows: List[dict] = []
    skeleton_gaps: List[dict] = []
    drifted: List[dict] = []
    # P1 #19：推荐标题正文超预算的软校验结果（只提示一线去改，不拦投产、不改状态）
    title_warnings: List[dict] = []
    # 模板自报偏差（缺剧名/缺角色卡/K 未给兜底）逐条清单，见下方 deviation 处理
    deviations: List[dict] = []
    # 批 P：扇出来的某一条换完词撞上高风险词 → 只摘那一条（点名到值，不静默丢）
    element_skipped: List[dict] = []
    code_pos = 0  # 钩子编号消耗指针：整条文案被拦下时**不进位**，号不该被一次失败的提交烧掉

    # 投产整批要保持原子（撞唯一约束时回 409「整批未落库」），所以这里**不能**像
    # 出文案口那样在调模型前先 commit；那就必须让本次事务别被空闲超时掐死：
    # PG 侧 idle_in_transaction_session_timeout=60s（Issue #219 的防御层）会在
    # 「SELECT 完就趴着等 HTTP」满 60 秒时关掉连接，11-03 预览栈真链路实测
    # 一次展开跑 9 分钟 → 后面 INSERT 报 connection is closed → 整口 500。
    # SET LOCAL 只影响**当前这个事务**，提交后自动还原，不改角色级配置、不影响别的请求。
    # 敢这么做的理由：等待期间本事务不锁任何别人要动的行——
    # asset_items 的 has_approved_copy 已挪到写单阶段（见下方），
    # asset_productions 的行是本事务自己新建、还没提交的。
    # 只在 PG 上做：单测/集成跑 sqlite，没有这个 GUC（`SET` 直接语法错）。
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))

    # A′（2026-11-08 评审定稿）：自审自投闸门——自己过审的候选自己投产要不要拦。
    # 11-09 用户口径：一人多角是常态，**默认放开**（config 里 ASSET_SELF_PRODUCE_ALLOWED=True）。
    # 放开不等于无痕：每次自审自投仍逐条写豁免审计（owner_cross 带 self 标记），
    # 质检关不会沦为静默绕过的橡皮章；确需纪律（外包/新人）显式设 false 就恢复拦。
    # getattr 的兜底值跟 config 默认保持一致——别出现「字段没读到反而变严」的分裂口径。
    self_produce_allowed = bool(getattr(settings, "ASSET_SELF_PRODUCE_ALLOWED", True))
    self_cross = self_summaries
    if self_cross and not self_produce_allowed:
        shown = "；".join(f"#{s.seq}" for s in self_cross[:5])
        raise HTTPException(
            status_code=400,
            detail=(
                f"这 {len(self_cross)} 条是你自己质检过审的（候选序号 {shown}），"
                "而自审自投闸门当前是关着的（ASSET_SELF_PRODUCE_ALLOWED=false）。"
                "质检与投产分离是三角色模型的纪律——确需一人包干（小团队/应急），"
                "由管理员把该旋钮设为 true 后重发（每次自审自投都会逐条留豁免审计）。"
            ),
        )

    for sid in data.summary_ids:
        uuid_s = _as_uuid(sid, "summary_id")
        summary = _pre_summaries.get(uuid_s)
        if summary is None:
            results.append({"summary_id": str(uuid_s), "created": 0, "error": "文案不存在"})
            continue
        # 素材多为素材专员导入，运营审完必须能直接投产（11-03 起读口不分可见范围，
        # 这里只校验素材行存在；投产权限仍是 operator/admin，自审禁令在 review 口）
        asset = await _get_asset_or_404(db, summary.asset_id)
        if summary.audit_status not in REVIEW_PASSED_STATES:
            results.append({
                "summary_id": str(uuid_s), "created": 0, "code": asset.code,
                "error": f"文案未过审（当前 {summary.audit_status}），生产必须只吃过审文案",
            })
            continue
        # 这里原本有一句 `asset.has_approved_copy = True`：挪到**写单阶段**去做
        # （apply_stage 已经带 has_approved_copy=True）。留在循环顶部会让 asset_items
        # 那一行在整批外部模型调用期间被本事务锁住——别的请求（比如同批素材的
        # 反推收敛写 stage）会一直等锁到 statement_timeout。过审时审核口早就置过位了。

        # A2-1 投产前复核（方案 §十一.7）：审核时看的是文案，投产时投的是**展开后的提示词**，
        # 中间词表可能已经更新（迁进 system_config 后改词不用发版），文案本身也可能被别处改过。
        # 这一遍跑在真正花号池额度**之前**，不过就整条文案不生成单，而不是生成了再靠人肉眼拦。
        script = await _prompt_script_of(db, asset)
        verdict = svc.recheck_copy(summary.text, script, lexicon=book, exemptions=exemptions)
        waived = None
        if not verdict["ok"]:
            waived_list, still_blocking = _split_waived(
                verdict["problems"], data.waive_codes if is_admin else None
            )
            if is_admin and (data.waive_reason or "").strip() and not still_blocking:
                waived = {
                    "problems": waived_list,
                    "codes": sorted({p["code"] for p in waived_list}),
                    "reason": (data.waive_reason or "").strip()[:500],
                }
                # 注意是**嵌一套**不是摊平：展开后的复扫结果要往同一个 dict 里补
                # prompt_problems，摊平（`{**waived}`）等于把那个引用丢了、补进去的东西永远看不见
                waived_rows.append({"summary_id": str(uuid_s), "code": asset.code, "waived": waived})
            else:
                detail = still_blocking or verdict["problems"]
                recheck_failed.append({
                    "summary_id": str(uuid_s), "code": asset.code, "problems": detail,
                })
                results.append({
                    "summary_id": str(uuid_s), "created": 0, "code": asset.code,
                    "error_code": "ASSET_RECHECK_FAILED",
                    "problems": detail,
                    "waivable_codes": sorted({p["code"] for p in verdict["problems"]}),
                    "error": "投产前复核未过：" + "；".join(p["message"] for p in detail)
                             + ("（本条未生成生产单；管理员可带 waive_reason 豁免，"
                                "只放过某几类问题请传 waive_codes）"
                                if is_admin else "（本条未生成生产单，请找审核人）"),
                })
                continue

        # 已有同文案的序号接着排（重头发不覆盖历史，交付对账要能追到每一版）
        max_seq = (
            await db.execute(
                select(func.coalesce(func.max(AssetProduction.seq), 0)).where(AssetProduction.summary_id == summary.id)
            )
        ).scalar_one()
        codes_for_summary = hook_codes[code_pos: code_pos + n * fanout]
        # 批 N（11-09 预取编号）：请求没给够号时，把这条文案名下预取的那个号顶到**第一个空槽**
        # （手工粘来的号优先，预取号只补空位）。顶上去就必须把预取位清空——留着等于允许
        # 同一个号被第二次开单复用，而号在 hook_id.py 那边一发即烧、板面同名任务回收对不上账。
        # 另一种"也算用掉"：请求里把同一个号手工粘了一遍（前端把预取号显示出来时很容易顺手粘），
        # 这时不再重复顶槽，但预取位同样要清，否则下一次开单会被上面的 stale 判据拦死。
        parked_code = summary.hook_code
        parked_consumed = bool(parked_code) and (
            parked_code in hook_codes or len(codes_for_summary) < n * fanout
        )
        if parked_code and parked_code not in hook_codes and len(codes_for_summary) < n * fanout:
            codes_for_summary = codes_for_summary + [parked_code]
        # 剧名一条文案查一次（不在 n 次展开循环里查）：模板要用它写「参考《剧名》剧情」
        drama_title = await _drama_title_of(db, asset)
        # 批 P：扇出要按**这一条的原型**决定哪些参数项参与替换（字典行上的 categories 限定）。
        # 只在真扇出时查这一行 PK，不扇出时零成本——旧前端/脚本调用完全走不到这条路上。
        element_category: Optional[str] = None
        if element_rows:
            _cat_id = summary.category_id or asset.category_id
            if _cat_id is not None:
                _cat_row = await db.get(AssetCategory, _cat_id)
                element_category = _cat_row.name if _cat_row is not None else None
        # 这一篇的原值：逐文稿那份优先，没单给才落到公共兜底（多文稿同批开单时
        # 拿一条稿子的场景词去换另一条稿子＝换不上，还报「原稿里没认出」，一线只会以为字典坏了）
        element_base_for_summary = {**element_base, **element_bases.get(str(uuid_s), {})}

        expand_error: Optional[str] = None
        pending: List[dict] = []
        # 真正落库的行：没扇出时就是 `pending` 本身，扇出时是摊平后的 n×K 行（见下方 else 分支）
        flat_rows: List[Dict[str, Any]] = []
        failure_recorded = False
        for i in range(1, n + 1):
            seq = max_seq + i
            basis = svc.variant_basis(i, n)
            # 一钩一号：按请求顺序发号，号不够就留空（绝不后端自编），导出时标缺
            next_hook_code = codes_for_summary[i - 1] if i - 1 < len(codes_for_summary) else None
            prompt_text = None
            dispatch_note = None
            video_titles: List[str] = []
            drift = False
            drift_reason: Optional[str] = None
            if data.expand:
                try:
                    expanded = await _call_autoclip(
                        "hook-copy/expand",
                        {
                            "hook_copy": summary.text,
                            "seq": i,
                            "total": n,
                            "variant_basis": basis,
                            # 与出文案同口径：内部只试一次，重试交给一线点按钮（理由见
                            # `_call_autoclip` 的超时链说明，11-04 flash 实测）。
                            "max_retries": 1,
                            "params": {
                                "asset_code": asset.code,
                                "platform": asset.platform or "",
                                # 剧名全称：模板第①行「参考《剧名》剧情」唯一来源，取不到传空
                                "drama_title": drama_title,
                                # 剧名缩写取自 NAS《剧名缩写表.json》，容器内读不到 → 由前端/一线带
                                "drama_abbr": (data.drama_abbr or "").strip(),
                                # 板上恒 10.08s：给模板的时长口径只有"10s 单条"这一档
                                "duration": duration,
                                "recommended_title_count": title_count,
                                "hook_code": next_hook_code,
                                "has_character_card": bool(card_ids or data.character_card_key),
                                "compliance": "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
                            },
                        },
                        # 用 `_call_autoclip` 的 900s 默认值。⚠️ 本函数是 n 次**串行**展开，
                        # 一次 HTTP 请求的耗时 ≈ n × 单次模型耗时（实测 pro/flash 各约 90–150s，
                        # 卡流时到 600s）——n 很大时早就顶穿浏览器那层 960s（连接断了但单照样
                        # 落库，刷新即可看到）。11-04 批 C（D-1）已把这条收掉：**页面按钮走
                        # `async_mode=true`，本函数只在后台任务里跑，没有 HTTP 请求在等它**，
                        # 所以大 n 不用再「分次投产」；只有不带 async_mode 的同步调用（脚本、
                        # 手工）还受这条超时链约束。
                    )
                    prompt_text = (expanded.get("prompt_text") or "").strip() or None
                    # B-9：投放要求（改名/跳过二次确认/并行）不进 payload，只给人看。
                    # 模板已改成分字段输出时直接用 dispatch_note；没改到位则整行搬移兜底。
                    dispatch_note = (expanded.get("dispatch_note") or "").strip() or None
                    if prompt_text:
                        body, moved = svc.split_dispatch_note(prompt_text)
                        if moved:
                            prompt_text = body
                            dispatch_note = "\n".join(x for x in (dispatch_note, moved) if x)
                    vt = expanded.get("video_titles")
                    video_titles = [str(x) for x in vt if str(x).strip()][:20] if isinstance(vt, list) else []
                    # 模板自报偏差（hook_expand.txt 里点名的三条：缺剧名→写《剧名待定》、
                    # 没挂角色卡→画幅不受文字控制、K 未给→按 5 条兜底）。这是模板与后端之间
                    # 唯一的约定通道，11-03 真链路冒烟才发现后端一直没接：模板照实报了，
                    # 一线在详情和导出 txt 里一个字都看不到。落进 dispatch_note（只给人看、
                    # 不进 payload）并在响应 deviations 里逐条列出。
                    deviation = (expanded.get("deviation_note") or "").strip()
                    if deviation:
                        dispatch_note = "\n".join(
                            x for x in (dispatch_note, f"模型自报偏差：{deviation}") if x
                        )
                        deviations.append({"code": asset.code, "seq": seq, "note": deviation[:300]})
                    # A3-3：过审文案必须在提示词里**原样、唯一、独立**地存活。
                    # 旧判据只做「去空格子串包含」——前面拼半句、整句塞进括号、复制两遍
                    # 全都判成"没漂移"，等于这道闸形同虚设。expand=false 的裸单没有
                    # prompt_text，不判（提示词还没生成，谈不上漂移）。
                    if prompt_text:
                        drift_verdict = svc.judge_drift(summary.text, prompt_text)
                        if drift_verdict["drift"]:
                            drift = True
                            drift_reason = "；".join(drift_verdict["reasons"])[:500]
                    # 展开后的提示词再扫一遍：风险词若是**模型自己加的**，拦在生成单之前
                    prompt_problems: List[Dict[str, str]] = []
                    if prompt_text:
                        hits = svc.risk_block_hits(
                            svc.scan_risk(prompt_text, lexicon=book, exemptions=exemptions)
                        )
                        prompt_problems += [
                            {"code": "risk", "message": f"展开后的提示词含高风险词「{h['word']}」（模型加的，过审文案里没有）"}
                            for h in hits
                        ]
                        sk = svc.check_prompt_skeleton(prompt_text)
                        if not sk["ok"]:
                            # 骨架缺行**只警示不拦**：模板由 CodeBuddy 侧维护，P0 期还在迭代，
                            # 拦在这里会把一整批投放卡住。真正的拦是风险词（A2-3 复扫）。
                            skeleton_gaps.append({
                                "code": asset.code, "seq": seq, "missing": sk["missing"],
                            })
                        if prompt_problems and not waived:
                            expand_error = (
                                "展开结果复核未过：" + "；".join(p["message"] for p in prompt_problems)
                                + "（本条文案整批未生成生产单，未消耗钩子编号）"
                            )
                            recheck_failed.append({
                                "summary_id": str(uuid_s), "code": asset.code, "problems": prompt_problems,
                            })
                            results.append({
                                "summary_id": str(uuid_s), "created": 0, "code": asset.code,
                                "error_code": "ASSET_EXPAND_RECHECK_FAILED",
                                "problems": prompt_problems, "error": expand_error,
                            })
                            failure_recorded = True
                            break
                        if prompt_problems and waived:
                            # admin 已豁免（豁免的是这条文案的整体投递），展开侧的新命中一并留痕
                            waived["prompt_problems"] = prompt_problems
                except HTTPException as e:
                    expand_error = str(e.detail)[:300]
                    break

            pending.append({
                "seq": seq,
                "hook_code": next_hook_code,
                "prompt_text": prompt_text,
                "dispatch_note": dispatch_note,
                "video_titles": video_titles or None,
                "variant_basis": basis,
                "drift": drift,
                "drift_reason": drift_reason,
            })
        else:
            # 整条文案的全部展开都过了才落库：中途拦下不能留下半批已生成的单
            #
            # 批 P：这里把「n 份展开稿」摊成「n × 扇出行数」张单。没扇出（`fanout==1`）时
            # 这一段等价于原来的 `for row in pending`——序号、编号、正文一律不动，
            # 老路径的回归判据就是这个等价性。
            flat_rows: List[Dict[str, Any]] = []
            if element_rows:
                for vi, base_row in enumerate(pending):
                    slice_codes = [
                        codes_for_summary[vi * len(element_rows) + j]
                        if vi * len(element_rows) + j < len(codes_for_summary) else None
                        for j in range(len(element_rows))
                    ]
                    rows, row_notes = _element_fanout_rows(
                        base_row, element_catalog, element_base_for_summary, element_rows,
                        element_category, slice_codes, element_labels,
                    )
                    for cand in rows:
                        # 换完词再扫一遍：单个词在词表里过、拼进句子却撞上高风险词的组合是真会
                        # 发生的（「猫」＋「摔在地上」）。这里只摘这一条：模型那 n 次调用的钱已经
                        # 花了，整条文案 20 张全不建是二次浪费；但摘掉的这条绝不静默——
                        # 点名到值、进结果、进审计。
                        hits = svc.risk_block_hits(
                            svc.scan_risk(cand.get("prompt_text") or "", lexicon=book, exemptions=exemptions)
                        )
                        if hits:
                            element_skipped.append({
                                "code": asset.code,
                                "basis": cand.get("variant_basis"),
                                "words": sorted({h["word"] for h in hits}),
                            })
                            continue
                        flat_rows.append(cand)
                    element_notes.extend(f"{asset.code} #{base_row['seq']}：{note}" for note in row_notes)
                for idx, cand in enumerate(flat_rows):
                    # 扇出后"这条文案的第 i 份"不再是序号的唯一来源：n×K 张单必须各自占号，
                    # 撞 uq_asset_production_seq 会让整批回滚（就是 B-5 那条 409）。
                    cand["seq"] = max_seq + idx + 1
            else:
                flat_rows = list(pending)
            for row in flat_rows:
                prod = AssetProduction(
                    asset_id=asset.id,
                    summary_id=summary.id,
                    batch_id=asset.batch_id,
                    # project_title 已废弃（11-02 版取消项目标题行），不再写入
                    duration=duration,
                    channel=channel,
                    board_total=board_total,
                    board_tag=board_tag,
                    board_date=board_date,
                    # B-5：板上 name = 推荐视频标题第 1 条（剥非法字符、≤60 码点）
                    board_name=svc.sanitize_board_name(row["video_titles"][0])
                    if row["video_titles"] else None,
                    character_card_key=card_key,
                    # 批 G：新前端挑的卡（顺序＝picDatas 顺序）。空数组给 None 而不是 []，
                    # 让"这批没挂卡"在读侧只有一种表示，回退判据不用同时防两种空值。
                    card_asset_ids=card_ids or None,
                    status=PR_ORDER_READY,
                    prompt_snapshot=summary.text,
                    idempotency_key=f"{summary.id}:{row['seq']}",
                    created_by=current_user.id,
                    **row,
                )
                db.add(prod)
                productions.append(prod)
                # P1 #19 推荐标题字数**软校验**（排在投产前复核等既有校验之后）：
                # 一线在任务板上看到的标题列只显示前 22 字（含发布侧补的 4 字【账号】
                # 前缀），而展开导出的标题正文不带前缀 → 预算是正文 ≤18 字。超了**不是
                # 报错**——那条标题会在报表里被截断、回收改名对不上，所以只收进
                # title_warnings 提示一线去改，不拦投产、不改状态。字数复用
                # count_copy_chars，与文案侧判据同一把尺。
                for gap in svc.check_video_title_budget(row["video_titles"]):
                    title_warnings.append({
                        "asset_code": asset.code,
                        "summary_id": str(summary.id),
                        "seq": row["seq"],
                        "hook_code": row["hook_code"],
                        **gap,
                    })
                if row["drift"]:
                    # 单子照常生成、不静默丢弃，但逐条点名（投出去烧的是号池额度）
                    drifted.append({
                        "summary_id": str(summary.id), "code": asset.code,
                        "seq": row["seq"], "reason": row["drift_reason"],
                    })
                if asset.batch_id:
                    batch_codes.add(str(asset.batch_id))
            # 过审标记落列（apply_stage 只用它算派生态、**不写列**，所以必须在这里显式置）：
            # 挪到写单阶段是为了不在外部模型调用期间锁住 asset_items 那一行
            if not asset.has_approved_copy:
                asset.has_approved_copy = True
            code_pos += n * fanout  # 号只在这批真的成了单之后才算用掉（扇出后每行各占一个）
            if parked_consumed:
                # 预取位清空与上面那行同生同死：半批被拦下时根本走不到这里，号不会被白烧
                summary.hook_code = None

        created = len(flat_rows) if not expand_error else 0
        if created:
            svc.apply_stage(asset, "produce", STAGE_PENDING, has_approved_copy=True)
            asset.cost_produce = asset.cost_produce or 0
        if failure_recorded:
            continue  # 展开复核已经记过这条的结果了，不再追加一条 created=0
        results.append({
            "summary_id": str(uuid_s), "created": created, "code": asset.code,
            "error": expand_error if expand_error else None,
        })

    try:
        await db.flush()
    except IntegrityError as exc:
        # 并发双击 / 同一文案同一序号重投 → 撞 uq_asset_production_seq / idempotency_key。
        # 裸 500 会让一线以为"没投出去"再点一次，这里明确回 409（B 组）。
        await db.rollback()
        logger.warning("生产单唯一约束冲突：%s", exc)
        raise HTTPException(
            status_code=409,
            detail="生产单与已有记录撞了唯一约束（同一文案同一序号已投过），本次整批未落库，请刷新后重试",
        )
    # 本批真实投放量 = 单条数 × 板上 total（这是号池当天要吃的条数，不是 created）
    planned_rows = len(productions) * board_total
    day_start = board_date.replace(hour=0, minute=0, second=0, microsecond=0)
    already_today = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(AssetProduction.board_total), 0)).where(
                    AssetProduction.board_date >= day_start,
                    AssetProduction.board_date < day_start + timedelta(days=1),
                )
            )
        ).scalar_one()
        or 0
    ) - planned_rows  # 刚 flush 的本批已在库里，扣掉才是"本批之前"的量
    capacity = svc.board_capacity_hint(
        planned_rows, max(0, already_today), int(settings.ASSET_BOARD_DAILY_SOFT_CAP)
    )
    plan = svc.estimate_production_days(
        planned_rows, account_count=max(1, int(data.accounts or 1)),
        per_account_per_day=settings.ASSET_DOUBAO_PER_ACCOUNT_PER_DAY,
    )
    missing_codes = sum(1 for p in productions if not p.hook_code)
    missing_names = sum(1 for p in productions if not p.board_name)
    _owner_names_all = await _user_names(
        db, {s.reviewed_by for s in (*cross_summaries, *self_summaries) if s.reviewed_by}
    ) if (cross_summaries or self_summaries) else {}
    await _write_audit(
        db,
        action="asset.produce_order",
        operator=current_user,
        target_type="asset_production",
        target_id=None,
        after={
            "requested": len(data.summary_ids),
            "n_per_copy": n,
            "created": len(productions),
            "channel": channel,
            "expand": data.expand,
            # 投放口径与产能声明全部留痕：事后对账要能还原"当时按几版投、说了几个号"
            "board_total": board_total,
            "planned_rows": planned_rows,
            "board_tag": board_tag,
            "board_date": board_date.isoformat(timespec="seconds"),
            "duration": duration,
            "accounts": data.accounts,
            "recommended_title_count": title_count,
            "character_card_key": card_key,
            # 批 G：卡按 id 数组留痕（顺序也留）——事后对账要能回答"当时挂的是哪几张、
            # 谁排第一"。只留一个 key 的话，多卡批次里被换掉的那张根本查不出来。
            "card_asset_ids": card_ids or None,
            "card_shapes": [
                {"code": n["code"], "ratio": n["ratio"], "orientation": n["orientation"]}
                for n in card_notes
            ] or None,
            # A′：归属留痕——候选过审人是谁、有没有跨人投产，事后要能回答"谁替谁投"
            "owner_cross": (
                {
                    "summaries": [
                        {
                            "summary_id": str(s.id),
                            "reviewed_by": str(s.reviewed_by) if s.reviewed_by else None,
                            "reviewed_by_name": _owner_names_all.get(str(s.reviewed_by)),
                            # A′：self=自审自投（ASSET_SELF_PRODUCE_ALLOWED 开闸时的逐条豁免留痕）
                            "self": s.reviewed_by == current_user.id,
                        }
                        for s in (*cross_summaries, *self_summaries)
                    ]
                }
                if cross_summaries or self_summaries
                else None
            ),
            "hook_codes": hook_codes or None,
            "capacity": capacity,
            # 复核结果全部入审计：豁免的每一条都能被 admin 抽检回溯（A2-1）
            "recheck_waived": waived_rows or None,
            "recheck_failed": recheck_failed or None,
            "prompt_skeleton_gaps": skeleton_gaps or None,
            # A3-3：展开结果与过审文案不是同一条的，逐条留成因
            "drifted": drifted or None,
            # P1 #19：标题字数软校验同样入审计，事后能回看当时超了哪几条
            "title_warnings": title_warnings or None,
            # 模板自报偏差入审计：导出后一线看到的《剧名待定》/无角色卡是当时几号单报的
            "deviations": deviations or None,
            # 批 P：扇出口径整个进审计——事后要能回答"这批为什么是 20 张不是 2 张"
            "element_fanout": (
                {
                    "mode": data.element_mode or pesvc.MATRIX_ZIP,
                    "rows_per_copy": len(element_rows),
                    "params": {
                        element_labels.get(k) or k: v for k, v in (data.element_values or {}).items()
                    },
                    "skipped": element_skipped or None,
                    "notes": element_notes[:20] or None,
                }
                if element_rows
                else None
            ),
        },
    )
    await db.commit()

    warnings = []
    if capacity["advisory"]:
        warnings.append(capacity["advisory"])
    if missing_codes:
        warnings.append(
            f"{missing_codes} 条缺五位钩子编号：段头/推荐标题/产出清单三处必须带编号，"
            "用 hook_id.py 取号后回填（后端不代编，手编必与共享盘撞码）"
        )
    if missing_names:
        warnings.append(
            f"{missing_names} 条没有推荐视频标题 → 板上 name 无从生成（投放后无法按标题回收），"
            "expand=false 的裸单不许投"
        )
    if waived_rows:
        warnings.append(
            f"{len(waived_rows)} 条投产前复核未过、由管理员豁免放行（原因与拦下的问题已入审计），"
            "抽检请对 asset.produce_order 的 recheck_waived 逐条回看"
        )
    if recheck_failed:
        warnings.append(
            f"{len(recheck_failed)} 条因投产前复核未过被拦下、未生成生产单，"
            "改文案或走管理员豁免后再投（钩子编号没被烧掉，可原号重投）"
        )
    if skeleton_gaps:
        warnings.append(
            f"{len(skeleton_gaps)} 条展开提示词缺十行骨架（缺行见 prompt_skeleton_gaps）："
            "缺「负面约束」会出怪片、缺「音频与字幕」会被加字幕，投放前人工补齐"
        )
    if drifted:
        warnings.append(
            f"{len(drifted)} 条展开结果与过审文案不是同一条（成因见 drifted，单条也回显在 drift_reason）："
            "模型改写了钩子原句 / 前面拼了字 / 整句复制了两遍。这批投出去就是烧号池额度，"
            "要么回去重展（expand=true 重投一次，序号接着排），要么人工把原句粘回正文再投"
        )
    if title_warnings:
        warnings.append(
            f"{len(title_warnings)} 条推荐标题正文超 {svc.TITLE_BODY_BUDGET_CHARS} 字"
            f"（逐条见 title_warnings）：报表/板面标题列只显示前 22 字（含发布侧补的"
            "4 字【账号】前缀），超了那条会被截断、回收改名对不上——不拦投产，请一线改短后再投"
        )
    if deviations:
        warnings.append(
            f"{len(deviations)} 条展开时模型自报了偏差（逐条见 deviations，也已并进各单的投放要求）："
            "常见是缺剧名→提示词里写成《剧名待定》、没挂角色卡→成片画幅不受文字控制、"
            "K 未给→标题按 5 条兜底。这类单子投出去对不上账，先补输入再重展"
        )
    # 批 G：画的画幅在建单当场说清（画幅由卡宽高比决定，等导出时才发现要重投一批）
    if card_notes:
        landscape = [n for n in card_notes if n["orientation"] == "landscape"]
        if landscape:
            warnings.append(
                f"{len(landscape)} 张角色卡是横版（{'、'.join(n['code'] for n in landscape)}）："
                "成片画幅跟着卡走，这批会出横屏——想竖屏就换竖版卡，别指望提示词里写 9:16 压得住"
            )
        mixed = _card_mixed_orientation_note(card_notes)
        if mixed:
            warnings.append(mixed)
        unknown = [n for n in card_notes if not n["orientation"]]
        if unknown:
            warnings.append(
                f"{len(unknown)} 张卡量不到画幅（{'、'.join(n['code'] for n in unknown)}）："
                "入库时 ffprobe 没探出尺寸，投产前自己点开看一眼，画幅是这张卡说了算"
            )
    elif data.card_asset_ids:
        warnings.append("挑的角色卡一张都没落上（本该在参数校验时就报 400，这条属于内部口径漂移）")
    elif not card_key:
        warnings.append(
            "本批没挂角色卡 → picDatas 为空，画中人全靠模型自由发挥（历史上「上下集换装」就是这么来的）。"
            "定妆照先在素材库当图片传上来，投产时挑它"
        )
    # 批 P：扇出口径当场说人话——建单的人必须知道"这 20 张是 2 份稿子 × 10 组参数"，
    # 不然事后对账会以为模型多跑了 18 次（并没有，扇出只换词、不花钱）。
    if element_rows:
        combo = "＋".join(
            f"{element_labels.get(k) or k} {len(v)} 个"
            for k, v in (data.element_values or {}).items()
            if v
        )
        warnings.append(
            f"按参数扇出：每条文案 {len(element_rows)} 张（{combo}，{'全组合' if (data.element_mode or pesvc.MATRIX_ZIP) == pesvc.MATRIX_PRODUCT else '按行配对'}）。"
            "扇出来的只是换了词的稿子，**没有再花模型钱**，但每张各占一个钩子编号、"
            "各吃一条号池额度"
        )
    for note in element_notes[:6]:
        warnings.append(note)
    if element_skipped:
        warnings.append(
            f"{len(element_skipped)} 条扇出来的稿子换完词撞上高风险词、**这条没建单**"
            f"（逐条见 element_fanout.skipped）：同批其它条照常建，改那个词再来一次"
        )
    # 当日号池真实消耗 + 本批投递分布（11-03 第 4 条：不硬限，只报数）
    batch_ids = sorted({str(p.batch_id) for p in productions if p.batch_id})
    scope = (
        [AssetProduction.batch_id.in_([uuid.UUID(b) for b in batch_ids])] if batch_ids else []
    )
    dispatch_counts = await _dispatch_counts(db, *scope)
    return {
        "created": len(productions),
        "results": results,
        # 批 I（链路收敛）：新单 id 列表——投产结果页「顺势投去出片」要拿它点名投板，
        # 免得用户再回列表勾一遍。没有单是None语义复杂化，空列表=没建出来（recheck 全拦）。
        "production_ids": [str(p.id) for p in productions],
        "board": {
            "channel": channel,
            "tag": board_tag,
            "date": board_date.isoformat(timespec="seconds"),
            "board_total": board_total,
            "tasks": len(productions),
            "planned_rows": planned_rows,
            "output": f"{settings.ASSET_BOARD_OUTPUT_SECONDS}s / {settings.ASSET_BOARD_OUTPUT_RESOLUTION}（不可改）",
        },
        "capacity_hint": plan,
        "board_capacity": capacity,
        # 建单当场就把「今天号池已经吃掉多少、成几条败几条」摆出来：拍 n/board_total 的人
        # 只有在这一刻会看数，等到导出时再问已经晚了（11-03 第 4 条：不硬限，但要报数）
        "dispatch": dispatch_counts,
        # 复核结论回显给审核台：拦了几条、豁免了几条，当场看得见，不用翻审计（A2-1）
        "recheck_failed": recheck_failed,
        "recheck_waived": waived_rows,
        "prompt_skeleton_gaps": skeleton_gaps,
        "drifted": drifted,
        # 批 G：本次投产挂的角色卡（顺序＝picDatas 顺序）+ 逐张画幅判读，
        # 前端把这几行原样显示即可——"哪张卡会出横屏"必须在建单这一屏看到。
        "cards": card_notes,
        "card_asset_ids": card_ids,
        # P1 #19：推荐标题正文超 18 字的逐条清单（软校验，单子照常建、状态照常走）
        "title_warnings": title_warnings,
        # 模板自报偏差：同内容也已并进各单 dispatch_note（导出 txt 里人眼能看到的那份）
        "deviations": deviations,
        # 批 P：扇出结果回显——前端结果页要照这份说「这批是参数扇出来的，没多花模型钱」，
        # 也要把"哪几条因为撞高风险词没建单"当场点名，而不是只塞在 warnings 里滚过去。
        "element_fanout": ({
            "mode": data.element_mode or pesvc.MATRIX_ZIP,
            "rows_per_copy": len(element_rows),
            "params": {
                (element_labels.get(k) or k): v for k, v in (data.element_values or {}).items() if v
            },
            "skipped": element_skipped,
            "notes": element_notes,
        } if element_rows else None),
        "warnings": warnings,
        "message": (
            f"已生成 {len(productions)} 条生产单（{len(data.summary_ids)} 条文案 × {n} 份差异化"
            + (f" × 扇出 {len(element_rows)} 张" if element_rows else "")
            + f"，每条出 {board_total} 版 → 投放 {planned_rows} 条）。"
            + (
                f"其中 {len(recheck_failed)} 条被投产前复核拦下、{len(waived_rows)} 条经管理员豁免。"
                if (recheck_failed or waived_rows)
                else ""
            )
            + "本口只到生产单为止（还没上板、不吃号池）：下一步用「投去 AI 出片」自动连板，"
              "或导出任务文件手工投完再补记投板结果。"
        ),
    }


# ──────────────────────────────────────────────
# 投递状态：回写口 + 计数（11-03 拍板第 4 条：号池不硬限，但要知道投了多少、成多少、败多少）
# ──────────────────────────────────────────────

# 这里只允许人报这四个态。superseded/cancelled/skipped 是**系统态**（撤审作废 / 熔断挡下），
# 从外部写进来等于让人手改台账，一律拒绝。
_DISPATCH_STATES = (PR_QUEUED, PR_RUNNING, PR_SUCCESS, PR_FAILED)
# 允许的迁移（同态重报按幂等跳过，不进这里）：
# - order_ready → 四个态都收：一线常常投完直接来报结果，不会先报「已投」；
# - failed → queued/running：重投一次（attempts 是这么涨起来的）；failed → success：补报纠正；
# - success → failed：只允许「成片回收后发现不可用」这一种改判，且必须写成因。
_DISPATCH_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    PR_ORDER_READY: (PR_QUEUED, PR_RUNNING, PR_SUCCESS, PR_FAILED),
    PR_QUEUED: (PR_RUNNING, PR_SUCCESS, PR_FAILED),
    PR_RUNNING: (PR_SUCCESS, PR_FAILED),
    PR_FAILED: (PR_QUEUED, PR_RUNNING, PR_SUCCESS),
    PR_SUCCESS: (PR_FAILED,),
}
# 「还没投出去」的态：用来判 attempts 该不该 +1（补报也算投过一次的证据）
_NOT_DISPATCHED = (PR_ORDER_READY,)
# 「投过、但后来被系统作废」的单（R-5：撤审把 failed 单一并 supersede）。
# 这类单**当日确实占了号池**，计数时必须还当已投——否则「今天投了多少条」会因为
# 事后一次撤审而变小，一线据此再排今天的量就会超。判据用 started_at（没真投过的
# 作废单这个字段是 NULL，撤审只改 status 不改 started_at，两者不会互相污染）。
_VOIDED_BUT_SENT = and_(AssetProduction.status == PR_SUPERSEDED, AssetProduction.started_at.is_not(None))


async def _converge_produce_stage(db: AsyncSession, asset_ids: set) -> Dict[str, str]:
    """按「本素材**全部**生产单」重算 produce 阶段，回 `素材 id → 新阶段`。

    抽出来是因为 11-05 批 H 之后 produce 阶段有了**第二个写入方**（自动投板协程）：
    人工回写走一套判据、机器回写走另一套，同一条素材会因为"谁来收尾"而给出不同的
    列表颜色——这类分叉在审核台一致性上已经被点名过一次（R-6），不再犯第二遍。

    四条判据（顺序即优先级）：
    - 没有单 / 全是 `order_ready` → pending：一张都没投出去，本环节还没开始；
    - 还有 queued/running/order_ready → running：**没投完的也算在跑**。一批 20 张里
      19 张成功 1 张还在板上，整条素材不能显示"成功"，否则一线会拿它去排发布；
    - 全终态且有 success → success：部分失败不整条判死，败几条去 `by_status` 看；
    - 其余（全 failed）→ failed。
    作废三态（superseded/cancelled/skipped）**不参与重算**：撤审作废掉的单不代表这条
    素材的生产结果，把它们数进来会让"撤审后素材退回待投产"变成"素材成功"。
    """
    stage_by_asset: Dict[str, str] = {}
    for aid in asset_ids:
        states = [
            str(s)
            for s in (
                await db.execute(
                    select(AssetProduction.status).where(
                        AssetProduction.asset_id == aid,
                        AssetProduction.status.notin_([PR_SUPERSEDED, PR_CANCELLED, PR_SKIPPED]),
                    )
                )
            ).scalars().all()
        ]
        if not states or all(s == PR_ORDER_READY for s in states):
            state = STAGE_PENDING
        elif any(s in (PR_QUEUED, PR_RUNNING, PR_ORDER_READY) for s in states):
            state = STAGE_RUNNING      # 还有没投完/在跑的，本环节没收
        elif any(s == PR_SUCCESS for s in states):
            state = STAGE_SUCCESS      # 全终态且有成功：部分失败不整条判死，败几条看 by_status
        else:
            state = STAGE_FAILED
        asset = await db.get(AssetItem, aid)
        if asset is not None:
            stage_by_asset[str(aid)] = svc.apply_stage(
                asset, "produce", state, has_approved_copy=asset.has_approved_copy
            )
    return stage_by_asset


async def _dispatch_counts(
    db: AsyncSession, *conds, soft_cap: Optional[int] = None, owner_uid: Optional[Any] = None
) -> dict:
    """生产单投递计数。`by_status` 是全量分布（含未投的 order_ready），`today` 是号池当日事实。

    两个口径必须分开，别混着看：
    - **scope 计数**（跟着 batch_id/asset_id 过滤）回答「这批/这条投得怎么样」；
    - **today 计数**不受 scope 约束——「今天号池吃进去多少、到手多少」是全队事实
      （实测 ≈120 条/日那条线），按批次过滤后就变成「这批占今天多少」，
      回答不了「今天还能不能再投」。
    `owner_uid`（A′ 按运营隔离）：只进 **scope 聚合**（「我的链路投得怎么样」），
    **today 号池口径绝不受它影响**——号池是全站一本账，按人切了就是「我占今天多少」，
    与「今天还能不能再投」是两个问题。注释与测试双钉（test_output_groups……隔离矩阵）。
    `success_rate` 分母只算**已终态**（success+failed），在投/出片中不进分母；
    没有终态时回 None，不是 0——0 会被读成「一条都没成」。
    `dispatched` 含**投过后被作废**的单（见 `_VOIDED_BUT_SENT`）：作废是审核侧的追溯动作，
    不改变「号池那天已经被吃掉」这个事实；`voided_after_dispatch` 单列出来给前端说明用。
    """
    if owner_uid is not None:
        conds = [*conds, AssetProduction.created_by == owner_uid]
    stmt = select(AssetProduction.status, func.count()).group_by(AssetProduction.status)
    if conds:
        stmt = stmt.where(and_(*conds))
    by_status = {str(s): int(n) for s, n in (await db.execute(stmt)).all()}

    void_conds = [AssetProduction.status == PR_SUPERSEDED, AssetProduction.started_at.is_not(None)]
    if conds:
        void_conds.extend(conds)
    voided_after_dispatch = int(
        (await db.execute(select(func.count()).select_from(AssetProduction).where(and_(*void_conds)))).scalar()
        or 0
    )

    succeeded = by_status.get(PR_SUCCESS, 0)
    failed = by_status.get(PR_FAILED, 0)
    dispatched = sum(by_status.get(s, 0) for s in _DISPATCH_STATES) + voided_after_dispatch
    terminal = succeeded + failed

    day_start = svc.board_timestamp().replace(hour=0, minute=0, second=0, microsecond=0)
    today_rows = (
        await db.execute(
            select(
                AssetProduction.status,
                func.coalesce(func.sum(AssetProduction.board_total), 0),
                func.count(),
            ).where(
                AssetProduction.board_date >= day_start,
                AssetProduction.board_date < day_start + timedelta(days=1),
                # 只数**已投**的：没投上板的单不吃号池额度。produce 口的
                # board_capacity.already_today 含未投单（那是"今天打算投多少"的口径），
                # 两者不等价，别在页面上互相换算。
                or_(AssetProduction.status.in_(list(_DISPATCH_STATES)), _VOIDED_BUT_SENT),
            ).group_by(AssetProduction.status)
        )
    ).all()
    # 列序是 (status, Σ board_total, 行数)：状态分布按**行数**算，不是按 board_total
    today_status = {str(r[0]): int(r[2]) for r in today_rows}
    cap = int(settings.ASSET_BOARD_DAILY_SOFT_CAP if soft_cap is None else soft_cap)
    # 列序是 (status, Σ board_total, 行数)：tasks＝生产单行数，board_rows＝号池吃掉的条数
    today_tasks = sum(int(cnt) for _s, _total, cnt in today_rows)
    today_board_rows = sum(int(total) for _s, total, _cnt in today_rows)
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "order_ready": by_status.get(PR_ORDER_READY, 0),
        "dispatched": dispatched,
        "voided_after_dispatch": voided_after_dispatch,
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": round(succeeded / terminal, 3) if terminal else None,
        "scope_note": (
            "by_status 含未投的 order_ready；success_rate 只按已终态（成功+失败）算，"
            "在投/出片中不进分母；投上板后又被撤审作废的单仍计入 dispatched（号池那天真被吃了）"
        ),
        "today": {
            "day": day_start.strftime("%Y-%m-%d"),
            "tasks": today_tasks,
            "board_rows": today_board_rows,
            "by_status": today_status,
            "succeeded": today_status.get(PR_SUCCESS, 0),
            "failed": today_status.get(PR_FAILED, 0),
            "dispatched": sum(today_status.get(s, 0) for s in _DISPATCH_STATES)
            + today_status.get(PR_SUPERSEDED, 0),
            "soft_cap": cap,
            # 软提示线是**条/日**（号池实测 120 条），所以比的是 Σ board_total 不是行数：
            # 6 张 ×20 条的板面吃掉 120 条＝已到线，按 tasks 算只会得出 6，永远提示不到人。
            "over_cap": max(0, today_board_rows - cap) if cap > 0 else 0,
            "note": (
                "当日口径按板面本地时区切日（与建任务的 board_date 同一套），"
                f"board_rows=Σ total（号池真正吃掉的条数），tasks=生产单行数；"
                + (
                    f"已超号池实测 ≈{cap} 条/日，超出部分预计到手率明显下降（不硬拦，产能不限）"
                    if cap > 0 and today_board_rows > cap
                    else "号池不做硬拦，这里只报数"
                )
            ),
        },
    }


@router.post("/assets/productions/status")
async def update_production_status(
    data: ProductionStatusRequest,
    current_user: Annotated[User, Depends(require_roles(*_REVIEW_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """生产单**投递状态回写**：把板上真实结果写回台账，并让素材的 produce 阶段跟着收敛。

    为什么 P0 就要这个口（11-03 拍板）：真正投板的是人（导出 payload → 企微后台建任务），
    系统看不到板面。没有回写口，`asset_productions.status` 永远停在 order_ready，
    「昨天投的 120 条到手几条」在库里根本不存在，对账页只能靠人回忆。

    权限放 `_REVIEW_ROLES`（operator/admin）：回写的是**投产台账**，与建单/投产同一侧；
    素材专员能导入反推出文案，但不能改生产结果——那是「生产者不得自审」的同一条纪律。

    三条硬规矩：
    - `ids` 里有不存在的 → 整批 400 不落库。台账动作说「改了 12 条」就必须 12 条都改了，
      静默跳过会留下一条永远没人补；
    - 判 `failed` 必须带 `error`（我们侧判读，板上失败行没有原因字段）；
    - `board_tid` 是**逐条**回读主键，只允许单条传（多条批量传 tid 会把 20 条钉成同一个 tid）。
    """
    if data.status not in _DISPATCH_STATES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"status 只支持 {'/'.join(_DISPATCH_STATES)}；"
                "superseded/cancelled/skipped 是系统态（撤审作废、熔断挡下），不由这里写"
            ),
        )
    cap = _analyze_max_per_call()
    if not data.ids:
        raise HTTPException(status_code=400, detail="请选择要回写状态的生产单")
    if len(data.ids) > cap:
        raise HTTPException(status_code=400, detail=f"单次最多回写 {cap} 条，当前 {len(data.ids)} 条请分次")
    if data.status == PR_FAILED and not (data.error or "").strip():
        raise HTTPException(
            status_code=400,
            detail="判失败必须写成因（error）：板上失败行不带原因，我们记的是自己的判读，空着事后无从对账",
        )
    if data.board_tid and len(data.ids) > 1:
        raise HTTPException(
            status_code=400,
            detail="board_tid 是逐条的回读主键，多条请一次一条（批量传会把所有单钉成同一个 tid，回收时全串错）",
        )

    ids = [_as_uuid(i, "生产单 id") for i in data.ids]
    rows = list(
        (await db.execute(select(AssetProduction).where(AssetProduction.id.in_(ids)))).scalars().all()
    )
    # R-5（11-04 批 B）双保险：撤审当场已经把失败单作废（见 `_supersede_productions`），
    # 但还有一条补不上时间差的路——**撤审那一刻这张单正在板上（queued/running）**，
    # 按口径不动它；它随后失败落成 failed，一线报「失败重投」→ failed→queued→又能导出。
    # 所以从 failed 往外走的每一次重投，都回来确认一眼：这张单的文案现在还是过审状态吗。
    summary_state: Dict[str, str] = {}
    sid_set = {str(p.summary_id) for p in rows if p.summary_id and p.status == PR_FAILED}
    if sid_set:
        for sid, state in (
            await db.execute(
                select(AssetSummary.id, AssetSummary.audit_status).where(
                    AssetSummary.id.in_([uuid.UUID(s) for s in sid_set])
                )
            )
        ).all():
            summary_state[str(sid)] = str(state)
    found = {str(p.id) for p in rows}
    missing = [str(i) for i in ids if str(i) not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"这些生产单不存在，整批未回写（先刷新列表拿准 id）：{', '.join(missing[:5])}",
        )

    now = datetime.utcnow()
    results: List[dict] = []
    blocked: List[dict] = []
    unchanged: List[str] = []
    touched_assets: List[Any] = []
    errors_before: Dict[str, Optional[str]] = {}
    for p in rows:
        before_status = p.status
        errors_before[str(p.id)] = p.error
        entry = {
            "id": str(p.id), "hook_code": p.hook_code, "seq": p.seq,
            "asset_id": str(p.asset_id), "batch_id": str(p.batch_id) if p.batch_id else None,
            "from": before_status, "to": data.status,
        }
        if before_status == data.status:
            # 幂等：同态重报不改任何字段，也不重算阶段（否则连点两次会把 attempts 加两回）
            unchanged.append(str(p.id))
            entry["reason"] = f"已是 {data.status}，未重复写入"
            results.append(entry)
            continue
        if before_status in (PR_SUPERSEDED, PR_CANCELLED, PR_SKIPPED):
            entry["reason"] = _export_block_reason(p)
            blocked.append(entry)
            continue
        # R-5：failed 想重投，先确认它的文案还站在过审那一侧（撤审前就已在板上的漏网路径）
        if (
            before_status == PR_FAILED
            and p.summary_id
            and summary_state.get(str(p.summary_id)) not in REVIEW_PASSED_STATES
        ):
            entry["reason"] = (
                "关联文案已不是过审状态（撤审/驳回/待重写），失败单不重投；"
                "要再投请先让文案回到过审，或重新投产生成新单"
            )
            blocked.append(entry)
            continue
        if data.status not in _DISPATCH_TRANSITIONS.get(before_status, ()):
            entry["reason"] = (
                f"不允许从 {before_status} 直接到 {data.status}"
                "（作废/系统态不经此口；改判只认 success→failed 且必须带成因）"
            )
            blocked.append(entry)
            continue

        p.status = data.status
        if before_status in _NOT_DISPATCHED or data.status == PR_QUEUED:
            # 首次投出去 = 第 1 次；回到 queued（重投）再 +1。补报（order_ready→success）同样算投过
            p.attempts = int(p.attempts or 0) + 1
        if p.started_at is None:
            p.started_at = now
        if data.status in (PR_SUCCESS, PR_FAILED):
            p.completed_at = now
        if data.status == PR_FAILED:
            p.error = str(data.error)[:500]
        else:
            p.error = None  # 改判/重投后旧成因不留着，历史在 AuditLog 的 before 里
        if data.board_tid:
            p.board_tid = str(data.board_tid)[:60]
        entry["attempts"] = p.attempts
        results.append(entry)
        touched_assets.append(p.asset_id)

    # 素材阶段收敛：逐条按「本素材全部生产单」重算，而不是照抄本次回写的状态
    # （判据抽成 `_converge_produce_stage`，人工回写与自动投板共用一套，见那里的说明）
    stage_by_asset = await _converge_produce_stage(db, {a for a in touched_assets if a})

    await _write_audit(
        db,
        action="asset.production_status",
        operator=current_user,
        target_type="asset_production",
        target_id=results[0]["id"] if len(results) == 1 else None,
        before={
            "ids": [r["id"] for r in results],
            "from": {r["id"]: r["from"] for r in results},
            "error": errors_before,
        },
        after={
            "to": data.status,
            "error": data.error,
            "board_tid": data.board_tid,
            "updated": [r["id"] for r in results if "reason" not in r],
            "unchanged": unchanged,
            "blocked": blocked,
            "asset_status": stage_by_asset,
        },
    )
    await db.commit()

    batch_ids = sorted({r["batch_id"] for r in results if r.get("batch_id")})
    if batch_ids:
        counts = await _dispatch_counts(
            db, AssetProduction.batch_id.in_([uuid.UUID(b) for b in batch_ids])
        )
    else:
        counts = await _dispatch_counts(db)
    changed = [r for r in results if "reason" not in r]
    return {
        "updated": len(changed),
        "results": results,
        "unchanged": unchanged,
        "blocked": blocked,
        "asset_status": stage_by_asset,
        "dispatch": counts,
        "message": (
            f"已回写 {len(changed)} 条为 {data.status}"
            + (f"，{len(unchanged)} 条同态未动" if unchanged else "")
            + (f"，{len(blocked)} 条被迁移规则挡下" if blocked else "")
            + (f"；所在批次累计成功 {counts['succeeded']} / 失败 {counts['failed']}"
               if batch_ids else "")
        ),
    }


@router.get("/assets/productions")
async def list_productions(
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    owner: Optional[str] = None,
    ids: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """生产单列表 + 投递计数（11-03 拍板第 4 条）。

    `dispatch.by_status` 走的是**过滤前的口径**：只跟着 batch_id/asset_id 走，不受
    `status=` 影响。前端筛「失败」时如果 by_status 也跟着筛，列表就变成
    「failed: 12」自己报自己，成功几条这个关键数消失了——那正是今天要对账的东西。

    `owner`（A′ 按运营隔离，2026-11-07）：GET 读口的查询偏好。owner=me → 按
    `created_by=me` 过滤（谁投账算谁）；scope 聚合同步带 owner，`today` 号池口径
    保持全站；响应另带 `dispatch_all`（同 scope 的全站口径），前端「我的/全站」
    两行并排。写口权限不受 owner 影响。

    `ids`（11-10 一屏到底）：逗号拼接的**单个字符串**（与 export 同一口径）。
    开单成功后前端要立刻把**刚建的那几张**顶进投板确认窗，而当前列表可能正筛着
    状态/批次/「我的」——靠分页翻不一定会翻到。只进 `conds`，**不进 `scope`**：
    投递计数（`dispatch`）说的还是这一屏的账，不该被一次点名改成三张单的账。
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 300)
    conds = []
    scope = []
    if ids:
        id_list = [_as_uuid(x.strip(), "ids") for x in str(ids).split(",") if x.strip()]
        if not id_list:
            raise HTTPException(status_code=400, detail="ids 是逗号拼接的 ID，不能是空的")
        if len(id_list) > 300:
            raise HTTPException(status_code=400, detail="ids 一次最多点 300 张单，请分批")
        conds.append(AssetProduction.id.in_(id_list))
    if status:
        conds.append(AssetProduction.status == status)
    if batch_id:
        conds.append(AssetProduction.batch_id == _as_uuid(batch_id, "batch_id"))
        scope.append(AssetProduction.batch_id == _as_uuid(batch_id, "batch_id"))
    if asset_id:
        conds.append(AssetProduction.asset_id == _as_uuid(asset_id, "asset_id"))
        scope.append(AssetProduction.asset_id == _as_uuid(asset_id, "asset_id"))
    if owner not in (None, "", "me", "all"):
        raise HTTPException(status_code=400, detail="owner 只支持 me（我的链路）或 all（全量），缺省=all")
    if owner == "me":
        # ⚠️ owner 只进 conds 与 _dispatch_counts 的 owner_uid 参数，**不进 scope**——
        # dispatch_all（全站口径一行）要用不带 owner 的 scope 重算。
        conds.append(AssetProduction.created_by == current_user.id)
    stmt = select(AssetProduction).where(and_(*conds)) if conds else select(AssetProduction)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(stmt.order_by(AssetProduction.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    dispatch = await _dispatch_counts(db, *scope, owner_uid=current_user.id if owner == "me" else None)
    # A′：「我的」视图附全站口径一行（today 本就全站；scope 的全站版给前端两行并排）
    dispatch_all = (
        await _dispatch_counts(db, *scope)
        if owner == "me"
        else None
    )

    # 批 I：整页一次聚合每单的成片数（与上面 summaries 的 out_counts 同一个套路——
    # 逐行数＝100 次查询）。排除 package/copy 附属文件，只数片。
    out_counts: Dict[Any, int] = {}
    pids = [p.id for p in rows]
    if pids:
        orows = (
            await db.execute(
                select(AssetOutput.production_id, func.count(AssetOutput.id))
                .where(
                    AssetOutput.production_id.in_(pids),
                    AssetOutput.kind.notin_(("package", "copy")),
                )
                .group_by(AssetOutput.production_id)
            )
        ).all()
        out_counts = {pid: int(cnt) for pid, cnt in orows}
    # A′：投产人显示名一次聚合
    owner_names = await _user_names(db, {p.created_by for p in rows})
    # 批 M（11-10）：这一页各单所属文案的**钩子原型名**（整页一次聚合，逐行查＝100 次）。
    # 原型是「每种钩子给几个可换元素」的分组依据，投产弹窗抽可替换元素要按它筛槽位；
    # 名字口径与审核台 `category_name` 同一个 `_category_name_map`（下线行也读得到名字）。
    summary_cats: Dict[Any, Any] = {}
    sids = {p.summary_id for p in rows if p.summary_id}
    if sids:
        summary_cats = {
            sid: cid
            for sid, cid in (
                await db.execute(
                    select(AssetSummary.id, AssetSummary.category_id).where(
                        AssetSummary.id.in_(sids)
                    )
                )
            ).all()
        }
    cat_names = await _category_name_map(db)

    def _prod_category_name(p: AssetProduction) -> Optional[str]:
        cid = summary_cats.get(p.summary_id)
        return cat_names.get(str(cid)) if cid else None

    return {
        "items": [
            _serialize_production(
                p,
                output_count=out_counts.get(p.id, 0),
                owner_name=owner_names.get(str(p.created_by)) if p.created_by else None,
                category_name=_prod_category_name(p),
            )
            for p in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "dispatch": dispatch,
        "dispatch_all": dispatch_all,
        "owner": owner or "all",
    }


def _export_block_reason(p: AssetProduction) -> str:
    """挡下导出的成因（回显给前端，别让一线猜）。"""
    if p.status == PR_SUPERSEDED:
        return "文案已被撤销过审，这张是作废旧单：正文不给，防止投出去烧号池额度"
    if p.status == PR_CANCELLED:
        return "生产单已取消"
    if p.status == PR_SKIPPED:
        return "被批次熔断挡下（额度/预算），未投递"
    if p.status == PR_FAILED:
        return f"生产失败单，无可交付产物{('：' + p.error) if p.error else ''}"
    return f"状态 {p.status} 不在可交付集内"


async def _asset_code_map(db: AsyncSession, asset_ids: set) -> Dict[str, str]:
    """生产单 → 素材短码（产出清单要用，别让一线拿 UUID 去对文件）。"""
    if not asset_ids:
        return {}
    rows = (
        await db.execute(select(AssetItem.id, AssetItem.code).where(AssetItem.id.in_(list(asset_ids))))
    ).all()
    return {str(r[0]): (r[1] or "") for r in rows}


async def _build_delivery(
    db: AsyncSession, rows: List[AssetProduction], fmt: str, *, exclude_ids: set | None = None
) -> dict:
    """format=txt / payload 的两块交付内容（A3-1）。

    只吃「可交付 + 有正文」的单：作废/失败/裸单（expand=false）在这里继续被挡，
    和 items[] 的 prompt_text 置空是同一道闸，不给第二条出口。
    `exclude_ids` 是调用方在这道闸之上再叠的一层（R-4：导出前重扫词表命中的行），
    同样不给第二条出口——items[] 置灰的行，txt/payload 里也必须没有它。
    """
    skip = exclude_ids or set()
    ready = [
        p for p in rows
        if p.status in EXPORTABLE_PRODUCTION_STATES
        and str(p.id) not in skip
        and (p.prompt_text or "").strip()
    ]
    codes = await _asset_code_map(db, {p.asset_id for p in ready})
    manifest = svc.format_output_manifest([
        {
            "hook_code": p.hook_code, "board_name": p.board_name,
            "asset_code": codes.get(str(p.asset_id)), "seq": p.seq,
        }
        for p in ready
    ])
    out: dict = {"delivery_count": len(ready), "manifest": manifest or None,
                 "excluded": len(rows) - len(ready)}
    if fmt == "txt":
        blocks = [
            svc.format_export_block(
                hook_code=p.hook_code, prompt_text=p.prompt_text,
                video_titles=p.video_titles or [], dispatch_note=p.dispatch_note,
            )
            for p in ready
        ]
        out["export_text"] = "\n\n".join(blocks + ([manifest] if manifest else []))
        return out

    # payload：逐条给出可直接 POST 的七键。
    # 批 G（11-05）改 here：旧写法是"按 key 去重、只装 1 项"——一部剧一张卡是常态，
    # 但多卡（男女主各一张）时那套会把第 2、3 张**静默丢掉**，而 picDatas 少一张
    # 照样投得出去，只是画中人不对。现在**逐张取、逐张装**，顺序＝`card_asset_ids`
    # 顺序＝板上 picDatas 顺序；同 key 被两张卡共用时仍只读一次对象存储（缓存按 key）。
    # 单张取不到**点名到是哪一张**，不静默给一个短了的数组。
    b64_by_key: Dict[str, List[str]] = {}
    card_errors: Dict[str, str] = {}
    sources = await _card_sources_for(db, ready)
    payloads = []
    card_problem_rows = 0
    for p in ready:
        warns: List[str] = []
        refs = sources.get(str(p.id)) or []
        pics: List[str] = []
        for ref in refs:
            key = ref.get("key")
            if not key:
                warns.append(f"角色卡 {ref['label']} 取不到 → picDatas 缺这一张")
                continue
            if key not in b64_by_key and key not in card_errors:
                # 两层都要防：minio_service.download_file 把 S3Error **吞成 None**（不判这层
                # 就等于"读不到卡"静默成空 picDatas，投放时才在板面上炸），而 executor
                # 之外的任何异常都不该把整批导出变成 500——逐条点名比整批失败有用。
                try:
                    raw = await download_file(ref["bucket"] or settings.MINIO_BUCKET_RAW, key)
                except Exception as exc:
                    logger.warning("角色卡读取异常 %s: %s", key, exc)
                    raw = None
                if raw:
                    b64_by_key[key] = [svc.card_b64_from_bytes(raw)]
                else:
                    card_errors[key] = "对象存储里没有这个 key，或读取失败（自有 raw 桶）"
            if key in b64_by_key:
                pics.extend(b64_by_key[key])
            else:
                warns.append(
                    f"角色卡 {ref['label']} 读取失败（{card_errors[key]}）→ picDatas 缺这一张"
                )
        if not refs:
            warns.append("本单没挂角色卡 → picDatas 为空：画中人全靠模型自由发挥（历史上「上下集换装」就是这么来的）")
        elif len(pics) != len(refs):
            # 逐张已经点名了，这里再给一条**总数**：多卡单最容易漏的就是"以为挂齐了"
            warns.append(f"挂了 {len(refs)} 张卡、只取到 {len(pics)} 张：先补齐再投，别少一张就发车")
        # 导出前再卡一道（批 G）：画幅由卡宽高比决定，这一屏是钱花出去前最后一次看见它
        landscape = [
            r for r in refs
            if r.get("orientation") == "landscape"
        ]
        if landscape:
            warns.append(
                f"{len(landscape)} 张卡是横版（{'、'.join(str(r.get('ratio') or '?') for r in landscape)}）："
                "成片画幅跟卡走，这支会出横屏"
            )
        orientations = {r.get("orientation") for r in refs if r.get("orientation")}
        if len(orientations) > 1:
            warns.append(
                f"卡的方向不一致（{'、'.join(sorted(orientations))}）：同一支片里换画幅，成片两头不靠"
            )
        if warns:
            card_problem_rows += 1
        if not p.board_name:
            warns.append("缺推荐标题 → 板上 name 为空，投放后无法按标题回收，先补 expand 再投")
        payloads.append({
            "id": str(p.id),
            "seq": p.seq,
            "hook_code": p.hook_code,
            "asset_code": codes.get(str(p.asset_id)),
            "cards": [
                {
                    "asset_id": r.get("asset_id"), "label": r.get("label"),
                    "key": r.get("key"), "ratio": r.get("ratio"),
                    "orientation": r.get("orientation"), "legacy": bool(r.get("legacy")),
                    "loaded": bool(r.get("key")) and (r.get("key") in b64_by_key),
                }
                for r in refs
            ],
            "payload": svc.build_board_payload(
                production_id=p.id, board_tag=p.board_tag, board_total=p.board_total,
                board_date=p.board_date, prompt_text=p.prompt_text,
                board_name=p.board_name, card_b64_items=pics,
            ),
            "warnings": warns,
        })
    out["payloads"] = payloads
    out["card_check"] = {
        "rows_with_card_issues": card_problem_rows,
        "note": (
            "逐张卡的读取与画幅都在这张单上（payloads[].cards / warnings）："
            "缺卡、横版、方向不一，任何一条都要在投板前处理掉——"
            "picDatas 少一张或画幅错了，投出去照样成功，账上看不出来"
        ),
    }
    out["card_advisory"] = (
        "picDatas 为**未缩放的原始字节** base64（后端没有 Pillow）。权威口径要求长边≤1024 的 JPEG q80："
        "卡是原图传上来的请先压一遍，板侧收到超大 picData 会静默建失败、事后查不到成因"
    )
    return out


def _risk_recheck_map(
    rows: List[AssetProduction], book: Dict[str, List[str]], exemptions: Dict[str, Any]
) -> Dict[str, List[Dict[str, str]]]:
    """R-4：按**当前**词表重扫每张单的正文，返回 `生产单 id → block 级命中`。

    只扫 block：warn 级当年在审核台就只是留痕，导出侧再拦一遍等于偷偷把口径收紧，
    一线会看到「昨天还能投今天不能」且没人解释过为什么。要升级警告级别请先改词表级别。
    """
    out: Dict[str, List[Dict[str, str]]] = {}
    for p in rows:
        if p.status not in EXPORTABLE_PRODUCTION_STATES or not (p.prompt_text or "").strip():
            continue
        hits = svc.risk_block_hits(svc.scan_risk(p.prompt_text, lexicon=book, exemptions=exemptions))
        if hits:
            out[str(p.id)] = hits
    return out


@router.get("/assets/productions/export")
async def export_productions(
    batch_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    ids: Optional[str] = None,
    accounts: int = 1,
    format: str = "json",
    force_risk: bool = False,
    force_reason: Optional[str] = None,
    current_user: User = Depends(require_functions("produce")),
    _export_role_gate: User = Depends(require_roles(*_REVIEW_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """导出提示词（每行一条可直接粘进豆包的完整提示词）。

    accounts 由调用方声明「这批准备用几个豆包号跑」——本系统没有豆包号池表
    （豆包是一条 CDP 浏览器会话＝一个登录号），所以不能自己去数 ChannelAccount：
    那是**视频号发布号**，跟豆包产能无关，拿它算天数会算出个漂亮的假数字。
    折成天数用的是单号 3 条/日的**额度墙**，不是工时。

    A2-2：作废态（superseded/cancelled/skipped/failed）的单子**状态照实回显、正文不外泄**
    （prompt_text 置空 + 挡下的成因）。撤销过审后留下的旧单如果被复制去投放，
    就是拿废弃文案烧号池额度，事后对账还看不出来。

    A3-1（format=）：
    - `json`（默认，兼容既有前端）→ 只有 items[]；
    - `txt` → 再加 `export_text`：每条一整块「段头（五位编号）+ 正文 + 推荐标题（编号在尾）」，
      末尾接批次级「产出清单」——11-02 版权威要求编号出现在这三处，一块粘进豆包就够；
    - `payload` → 再加 `payloads[]`，每条是可直接 POST `/api-g/aivideo/create` 的**七键**
      `tag/reqID/total/date/prompt/name/picDatas`（键序与 pipeline.py 一致，多一键板侧不认）。
      `reqID` 用生产单 id（不是随机 uuid4）：重复导出不换号，回收时 reqID 直接回指这张单。
    txt/payload 两种只吃「可交付 + 有正文」的单，与 items 的置空口径是同一道闸，不开第二条出口。

    A2-4：导出＝交付动作，留一条审计（谁、什么时候、拿走了哪几张单）。GET 带副作用
    在这里是有意的——交付口径要能被追溯，比"GET 必须只读"更重要。

    R-4（11-04 第二轮）：**导出前按当前词表重扫一遍正文**。审核时扫的是当时的词表，
    运营后来往 `asset_risk_lexicon` 里加的禁词不会回头找已经建好的生产单——
    「过审 → 建单 → 加词 → 导出投放」这条路上，导出是最后一道还碰得到人的闸，
    不重扫就等于新词永远管不到存量单。命中 block 级的行置灰（items 里 `risk_hits` 说明白），
    txt/payload 同样不吐正文（和 A2-2 那道闸共用 `_build_delivery` 的 exclude 口径）。
    放行只给 admin：`force_risk=true` 且必须带 `force_reason`，放行了哪几张、为什么，进审计。
    """
    conds = []
    if ids:
        id_list = [_as_uuid(x.strip(), "ids") for x in ids.split(",") if x.strip()]
        if id_list:
            conds.append(AssetProduction.id.in_(id_list))
    if batch_id:
        conds.append(AssetProduction.batch_id == _as_uuid(batch_id, "batch_id"))
    if asset_id:
        conds.append(AssetProduction.asset_id == _as_uuid(asset_id, "asset_id"))
    stmt = select(AssetProduction).where(and_(*conds)) if conds else select(AssetProduction)
    rows = list((await db.execute(stmt.order_by(AssetProduction.created_at.desc()))).scalars().all())

    account_count = max(1, min(int(accounts or 1), 50))
    fmt = (format or "json").strip().lower()
    if fmt not in ("json", "txt", "payload"):
        raise HTTPException(status_code=400, detail="format 只认 json / txt / payload")

    # R-4 的放行闸门：**只有 admin**能带着理由把重扫命中的单放出去，且理由必填。
    # 素材专员能导出但不能自评自放——和「生产者不得自审」「生产台账只有 operator/admin 改得动」
    # 是同一条纪律：挡词的闸如果谁都能踩，加词的人第二天就会发现那闸没人当回事。
    if force_risk:
        if current_user.role != UserRole.admin.value:
            raise HTTPException(
                status_code=403,
                detail="带风险词强制导出只有 admin 能做（导出侧的重扫命中由审核口径决定，不是投放同学自己判的）",
            )
        if not (force_reason or "").strip():
            raise HTTPException(
                status_code=400,
                detail="强制导出必须写理由（force_reason）：放行的是「这个词在这批语境里没问题」，"
                "不留一句话，事后对账只看到一个绕过闸门的导出记录",
            )

    book, exemptions = await _risk_lexicon(db)
    risk_hits = _risk_recheck_map(rows, book, exemptions)
    forced_ids = sorted(risk_hits) if (force_risk and risk_hits) else []
    # 命中但没被放行的 → 和状态不可交付同一套处置：正文不给、txt/payload 里也不出现
    risk_blocked_ids = {pid for pid in risk_hits if not force_risk}

    items = []
    blocked: List[dict] = []
    for p in rows:
        pid = str(p.id)
        status_ok = p.status in EXPORTABLE_PRODUCTION_STATES
        exportable = status_ok and pid not in risk_blocked_ids
        entry = {
            "id": pid,
            "asset_id": str(p.asset_id),
            "seq": p.seq,
            "hook_code": p.hook_code,
            "project_title": p.project_title,
            "prompt_text": p.prompt_text if exportable else None,
            "dispatch_note": p.dispatch_note if exportable else None,
            "video_titles": p.video_titles or [],
            "variant_basis": p.variant_basis,
            "drift": bool(p.drift),
            "drift_reason": p.drift_reason,
            "status": p.status,
            "exportable": exportable,
            "board_name": p.board_name,
            "board_total": p.board_total,
            "board_tag": p.board_tag,
            "board_date": utc_iso(p.board_date) if p.board_date else None,
            "character_card_key": p.character_card_key,
            # 批 G：json 形态也要能看到挂了几张卡（payload 形态的逐张明细在 payloads[].cards）
            "card_asset_ids": [str(x) for x in (p.card_asset_ids or []) if str(x or "").strip()],
        }
        # 命中信息**放行与否都回显**：一线要看得见「哪张被新词表点了名、放行的是哪几张」，
        # 别做成"放行就当没发生过"
        if pid in risk_hits:
            entry["risk_hits"] = risk_hits[pid]
            entry["risk_forced"] = bool(force_risk and pid in risk_hits)
        items.append(entry)
        if not exportable:
            if not status_ok:
                reason = _export_block_reason(p)
            else:
                reason = (
                    "文案过审后词表被改过：这条正文现在含高风险词「"
                    + "、".join(h["word"] for h in risk_hits[pid])
                    + "」（按当前词表重扫命中）。改文案后重新投产，或让 admin 带理由强制导出"
                )
            blocked.append({"id": pid, "seq": p.seq, "status": p.status, "reason": reason})

    await _write_audit(
        db,
        action="asset.production.export",
        operator=current_user,
        target_type="asset_production",
        target_id=None,
        after={
            "filters": {"batch_id": batch_id, "asset_id": asset_id, "ids": ids},
            "requested": len(rows),
            "exported": len(rows) - len(blocked),
            "blocked": [b["id"] for b in blocked] or None,
            "blocked_detail": blocked or None,
            "accounts": account_count,
            # 交付形态也入审计：事后能还原"当时拿走的是 json 还是可直接投的 payload"
            "format": fmt,
            # R-4：重扫结果单独记一份。**放行的那几张必须能单独查出来**——
            # 词表是运营加的、放行是 admin 点的，出了事要能回答「谁放行的、放了哪几张、凭什么」
            "risk_recheck": {
                "hits": {pid: [h["word"] for h in hits] for pid, hits in risk_hits.items()} or None,
                "blocked_ids": sorted(risk_blocked_ids) or None,
                "forced_ids": forced_ids or None,
                "forced_reason": (force_reason or "").strip()[:500] or None,
            } if risk_hits else None,
        },
        # 11-06 拍板①：强制导出（绕过风险词闸）审计写失败就拒绝这次导出——
        # 数据还没交付给调用方，500 掉就是「操作被拒」，不会有绕闸记录缺席。
        strict=bool(force_risk),
    )
    await db.commit()

    delivery = await _build_delivery(db, rows, fmt, exclude_ids=risk_blocked_ids) if fmt != "json" else {}
    return {
        "format": fmt,
        "items": items,
        "count": len(items),
        "ready": sum(1 for i in items if i["prompt_text"]),
        "blocked_count": len(blocked),
        "blocked": blocked,
        "risk_recheck": {
            "hit_count": len(risk_hits),
            "blocked": sorted(risk_blocked_ids),
            "forced": forced_ids,
            "forced_reason": (force_reason or "").strip() or None,
            "note": (
                "导出前按**当前**风险词表重扫过正文：命中 block 级的行已置灰、正文不进 txt/payload。"
                + (
                    f"本次由 admin 带理由放行 {len(forced_ids)} 张。"
                    if forced_ids else ""
                )
                + "词表在审核台之外的改动不会回头找存量单，这一道是存量单唯一的重扫点。"
            ),
        },
        "capacity": svc.estimate_production_days(
            len(items), account_count=account_count,
            per_account_per_day=settings.ASSET_DOUBAO_PER_ACCOUNT_PER_DAY,
        ),
        "note": (
            "prompt_text 为空的有三种：作废/失败单（不可投放，见 status）、展开失败"
            "（看生产单 error）、按当前词表重扫命中高风险词（见 blocked），都别硬投"
        ),
        **delivery,
    }


# ──────────────────────────────────────────────
# 自动投板（11-05 批 H）：可自动投板，但**逐批人工确认**
# ──────────────────────────────────────────────
#
# **批量数学**（11-04 拍板④要求把这条写进注释与 UI，别只写在文档里）：
# - N 份差异化提示词 = **N 张生产单**，每张单一次 `create`、板上 `total` 默认 1；
# - 号池当天吃的是 **Σ board_total**，不是"单的行数"。20 张单 × total=3 是 **60 条**额度，
#   而投递台账上只有 20 行——对账看 `dispatch.today.board_rows`，按行数算会少看三倍；
# - 「同一条文案出 3 版挑最好」才用 total>1，「要 3 条不同钩子」用 N。两个量混用就是白烧。
#
# 与人工投板（导出 payload → 人去板面建任务）的关系：**同一条交付线，两个入口**。
# payload 仍然走 `_build_delivery`（和导出同一个函数），闸门仍然是那四条，
# 所以"机器投的比人投的松"这种分叉在这里不存在——真要说区别，只有一处：
# 自动投板会**当场把 board_date 重新按投递时刻生成**（人工投板是建单时的日期，
# 隔几天再投就会把量记到错误的那一天，见下面 `_refresh_board_date` 的说明）。

# 板子出来的产物在 `asset_outputs.kind` 里就记 `doubao_raw`（模型列注释那一档）：
# 通道的后端是豆包，任务板只是排队派号，落到桶里的是**没经过我们加工的原片**。
BOARD_OUTPUT_KIND = "doubao_raw"
# 进不了投递口的状态：各自成因见 `_dispatch_gate`
_NOT_DISPATCHABLE = (PR_SUPERSEDED, PR_CANCELLED, PR_SKIPPED, PR_FAILED, PR_SUCCESS)


def _dispatch_max_per_call() -> int:
    return max(1, int(settings.ASSET_DISPATCH_MAX_PER_CALL or 20))


def _board_poll_interval_seconds() -> float:
    """轮询间隔（秒），下限 0.05s。

    下限不是洁癖：`ASSET_BOARD_POLL_INTERVAL=0` 会让整个轮询变成**不带喘气的忙等**
    （每轮一次回读＋可能一次下载），几十个单一起跑就是把板子当压测目标。
    回归用例要快就设到这个下限——真板子 45s 一轮的节奏在用例里没必要复现。
    """
    return max(0.05, float(settings.ASSET_BOARD_POLL_INTERVAL or 45))


def _board_poll_max_minutes() -> float:
    """轮询最长等待（分钟），下限 0.02 分钟（≈1.2s，保证到期判读这条码路真被执行过）。"""
    return max(0.02, float(settings.ASSET_BOARD_POLL_MAX_MINUTES or 45))


def _refresh_board_date(p: AssetProduction) -> None:
    """投板前把 `board_date` 按**投递时刻**重新生成（只动这一次真的要新建任务的单）。

    为什么必须重生成：`board_date` 是建单时（`/produce`）盖章的，而"建完单当天就投"
    只是理想情况——一线经常今天建单、明天投。板上按 `date` 排日，用昨天的日期建任务，
    量就记到昨天那天的号池上（当日余量提示跟着算错），回收时按今天查还查不到。
    格式仍然是**后端生成的完整时间戳**（`svc.board_timestamp`），不是前端传的日期：
    只写日期或不带时分秒＝接口照样回 succ、但 `info?date=` 永远查不到，额度白烧
    （1021 实测 120 条就是这么丢的）。
    """
    p.board_date = svc.board_timestamp(tz_offset_hours=settings.ASSET_BOARD_TZ_OFFSET_HOURS)


async def _dispatch_gate(
    db: AsyncSession,
    rows: List[AssetProduction],
    *,
    operator: User,
    force_risk: bool,
    force_reason: Optional[str],
    recover_only: bool,
) -> Dict[str, Any]:
    """把点名的单分成三堆：`to_create`（新建板任务）/ `to_recover`（只回读回收）/ `blocked`。

    闸门四条（11-04 拍板④＋第二轮审核 R-4/R-5 的口径，一条都不能少）：
    1. **只投 `order_ready`**：已经 success 的不再动；failed 的**不在这里自动重投**——
       板上失败行没有原因字段，重投与否要人判读（「不自动补投隔夜」是同一条纪律）；
       superseded/cancelled/skipped 是系统作废态，投出去就是拿废弃文案烧号池；
    2. **`drift=false`**：展开结果和过审文案不是同一条的单，投出去烧的是号池、
       发出去的是没人审过的词——这条**不给豁免**（豁免风险词是给语境判断，
       漂移是"文案没审过"，不是语境问题）；
    3. **未作废**：见第 1 条；
    4. **按当前词表重扫不命中 block**：与导出侧 R-4 同一道闸、同一个 admin 放行口径
       （`force_risk` 只有 admin 能用且必须写理由，放行了哪几张进审计）。

    另外三条是这条线特有的（人工投板靠人眼，自动投板没人看板面）：
    - 必须有 `prompt_text`（expand=false 的裸单没有正文，投出去是空提示词）；
    - 必须有 `board_name`（板上 name 空＝回收时按标题找不到、交付文件名也无从生成）；
    - 通道必须是 `wework_aivideo`（别的通道这块板子不认）。

    `to_recover` 不过内容闸门：回读＋下载**一分钱不花**，片子已经在那儿了。
    已经付过钱的产物因为"撤审时它正在板上"而取不回来，那才是真亏。
    """
    if force_risk:
        if operator.role != UserRole.admin.value:
            raise HTTPException(
                status_code=403,
                detail="带风险词强制投板只有 admin 能做（挡词的闸由审核口径决定，不是投放同学自己判的）",
            )
        if not (force_reason or "").strip():
            raise HTTPException(
                status_code=400,
                detail="强制投板必须写理由（force_reason）：投出去就烧号池额度，不留一句话事后只看到一个绕过闸门的记录",
            )

    book, exemptions = await _risk_lexicon(db)
    risk_hits = _risk_recheck_map(rows, book, exemptions)
    risk_blocked = {pid for pid in risk_hits if not force_risk}
    forced_ids = sorted(risk_hits) if (force_risk and risk_hits) else []

    if forced_ids:
        # 11-06 拍板①：强制投板是**不可逆烧号池额度**的动作，审计必须在动板子
        # **之前**落定（strict）——审计写失败＝这次强制投板根本不开始，而不是
        # 「投出去了、账没记上」。后面那笔常规审计照旧 fail-soft。
        await _write_audit(
            db,
            action="asset.production.dispatch",
            operator=operator,
            target_type="asset_production",
            target_id=None,
            strict=True,
            after={
                "phase": "forced_pre",
                "forced_ids": forced_ids,
                "force_reason": (force_reason or "").strip()[:500],
            },
        )
        await db.commit()

    to_create: List[AssetProduction] = []
    to_recover: List[AssetProduction] = []
    blocked: List[dict] = []

    def _block(p: AssetProduction, reason: str) -> None:
        blocked.append({"id": str(p.id), "seq": p.seq, "hook_code": p.hook_code, "reason": reason})

    for p in rows:
        pid = str(p.id)
        if p.status == PR_SUCCESS:
            _block(p, "这张单已经成功到手，投递口不再动它（要重做请重新投产生成新单）")
            continue
        if p.status in (PR_SUPERSEDED, PR_CANCELLED, PR_SKIPPED):
            _block(p, _export_block_reason(p))
            continue
        if p.status == PR_FAILED:
            _block(
                p,
                "失败单不在这里自动重投：板上失败行没有原因字段，重投与否要人判读——"
                "要重投就在生产单列表对这行点「按同文案重开单」（用同一句过审文案重新投产，"
                "失败单本身留档不动）；不用重投就补记手工投板结果留档"
                # 批 N（评审二·P0-1）：旧话术建议「走回写口把它带回 queued」再投——但投递口
                # 只接 order_ready，带回 queued 的路自己就走不通，一线照着指走必撞墙。
            )
            continue
        if p.board_tid:
            # 拍板②「已拿到 board_tid 的单只回读不重建」：这张的号池额度**已经花掉了**，
            # 再 POST 一次就是同一条文案烧两遍。进程重启、协程被带走时靠这条路把片子取回来。
            to_recover.append(p)
            continue
        if p.status != PR_ORDER_READY:
            _block(p, f"状态是 {p.status}，不是待投的 order_ready；投递口只接没投过的单")
            continue
        if recover_only:
            _block(p, "本次是「只回读回收」（recover_only=true），这张还没投上过板，不动它")
            continue
        if p.channel and p.channel != CH_WEWORK_AIVIDEO:
            _block(
                p,
                f"通道是 {p.channel}，不是后台任务板（wework_aivideo）；这条投递线只认任务板",
            )
            continue
        if not (p.prompt_text or "").strip():
            _block(p, "没有展开后的提示词正文（expand=false 的裸单）：先补 expand 再投")
            continue
        if not (p.board_name or "").strip():
            _block(p, "缺推荐标题 → 板上 name 会是空的，投放后按标题回收不到、交付文件名也无从生成")
            continue
        if p.drift:
            _block(
                p,
                f"提示词与过审文案不是同一条（{p.drift_reason or 'drift=true'}）：漂移单不给豁免、不自动投",
            )
            continue
        if pid in risk_blocked:
            _block(
                p,
                "文案过审后词表被改过：正文现在含高风险词「"
                + "、".join(h["word"] for h in risk_hits[pid])
                + "」。改文案后重新投产，或让 admin 带理由强制投板",
            )
            continue
        to_create.append(p)

    return {
        "to_create": to_create,
        "to_recover": to_recover,
        "blocked": blocked,
        "risk_hits": risk_hits,
        "risk_blocked_ids": risk_blocked,
        "forced_ids": forced_ids,
        "forced_reason": (force_reason or "").strip() or None,
    }


async def _dispatch_capacity(db: AsyncSession, planned_rows: int) -> Dict[str, Any]:
    """号池当日余量（Σ board_total 口径）。**只提示不拦**——用户拍板「产能不限」。

    为什么不拦：这条线唯一的实测结论是"超出 ≈120 条的部分到手率明显掉"，不是"投不进去"；
    把它做成熔断就会在一线真需要冲量的那天挡错人。要拦请先给出可信的余量接口，我们没有。
    为什么这个数**天然偏乐观**：号池是单日上限、且与每天的解压线**共用**（1023 叠两份量
    → 115/120 成批 fail），而解压线在库里没有台账——这里只能算出素材库自己吃了多少。
    """
    day_start = svc.board_timestamp(tz_offset_hours=settings.ASSET_BOARD_TZ_OFFSET_HOURS).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    already = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(AssetProduction.board_total), 0)).where(
                    AssetProduction.board_date >= day_start,
                    AssetProduction.board_date < day_start + timedelta(days=1),
                    # 只数**已投上板**的（含投过后被撤审作废的）：没投的单不吃号池
                    or_(AssetProduction.status.in_(list(_DISPATCH_STATES)), _VOIDED_BUT_SENT),
                )
            )
        ).scalar_one()
        or 0
    )
    hint = svc.board_capacity_hint(
        planned_rows, already, int(settings.ASSET_BOARD_DAILY_SOFT_CAP)
    )
    # 把"这个数没算解压线"写在返回体里，而不是只写在代码注释里：
    # 一线是看这行字排今天量的，注释帮不到他。
    hint["note"] = (
        str(hint.get("note") or "")
        + "；本数只含**素材库自己**今天投的，不含同日在板子上跑的解压线（那条线库里没有台账），"
        "所以真实余量比这里显示的小——号池是共用池"
    )
    return hint


async def _fetch_board_output(
    p: AssetProduction, task_row: Dict[str, Any], work_dir: str, *, index: int
) -> Dict[str, Any]:
    """把板上一条 succ 任务下载→落桶，返回可以直接 `AssetOutput(**…)` 的字段。

    ⚠️ 这个函数**一段 DB 都不碰**，是刻意的：轮询协程里一次下载＋上传可能耗几十秒到
    两三分钟，而现网 Postgres 的 `idle_in_transaction_session_timeout` 是 60s——
    事务开着等网络就会被服务端掐死（11-04 真链路撞过一次，那次是等模型）。
    所以口径是：读板→取文件→传桶全走完之后，调用方才开一次短事务写库。
    """
    out_url = str(task_row.get("outUrl") or "")
    tid = str(task_row.get("tid") or "")
    raw = await board.download_output(out_url)
    safe = "".join(c for c in (p.board_name or p.hook_code or str(p.asset_id)[:8]) if c not in '/\\:*?"<>|').strip()[:60]
    fname = f"{safe}_{index}_{tid[-18:] if tid else uuid.uuid4().hex[:8]}.mp4".strip() or f"{index}.mp4"
    local = os.path.join(work_dir, f"{uuid.uuid4().hex[:12]}.mp4")
    with open(local, "wb") as fh:
        fh.write(raw)
    file_key = f"asset/board/{safe or 'unknown'}/{uuid.uuid4().hex[:16]}_{fname}"
    uploaded = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW, file_key, local, content_type="video/mp4"
    )
    size = len(raw)
    info = await compose.probe_media(local) or {}
    # ⚠️ 摘要必须在删临时文件**之前**算：先删后算会抛 FileNotFoundError，
    # 而这条异常会被上层记成「片子没取回来」——其实片子已经落桶了，只是台账没写上。
    digest = compose.sha256_of(local)
    try:
        os.remove(local)
    except OSError:
        pass
    if not uploaded:
        # 桶里没这个对象，`upload_file_from_path` 已经把 S3Error 吞成 False（和 11-04
        # 「0 字节对象照样 201」是同一类坑：不信返回值就得信不了这条线）
        raise board.BoardError(f"成片已下载（{size} 字节）但落桶失败，板上文件还在，重试回收即可")
    resolution = None
    if info.get("width") and info.get("height"):
        resolution = f"{int(info['width'])}x{int(info['height'])}"
    return {
        "kind": BOARD_OUTPUT_KIND,
        "file_key": file_key,
        "bucket": settings.MINIO_BUCKET_RAW,
        "file_name": fname,
        "duration": info.get("duration"),
        "file_size": size,
        "resolution": resolution,
        "sha256": digest,
        "board_out_url": out_url,
        "tid": tid,
        "rgid": str(task_row.get("rgid") or "") or None,
        "doubao_account": str(task_row.get("doubaoName") or "") or None,
    }


@router.post("/assets/productions/dispatch")
async def dispatch_productions(
    data: DispatchRequest,
    current_user: Annotated[User, Depends(require_functions("produce"))],
    db: AsyncSession = Depends(get_db),
    _role_gate: User = Depends(require_roles(*_REVIEW_ROLES)),
):
    """把点名的生产单**真投上企微后台任务板**，轮询出片并回收成片（11-05 批 H）。

    拍板口径（11-04 晚④）：「可自动投板，但**逐批人工确认**」——机器连板、那一下由人点。
    所以本口没有"整批今晚自动投掉"的形态：`ids` 必须点名，`confirm` 必须为 true，
    不自动补投隔夜、不自动 QC、号池余量只提示不拦。

    为什么默认 `async_mode=true`：一次投板＝建任务＋等出片（实测单条 45s 一轮、25 分钟
    到手，整批排队更久）＋下载落桶，几十分钟的活同步等必然顶穿超时链
    （前端 960s > 后端 900s > …）。它是四类后台任务里唯一**默认就走后台**的：
    出文案/投产留了同步档给脚本与回归用例，这两条没有"几十分钟"的负担，投板有。
    后台协程复用**本函数**（`_job_endpoint(JOB_DISPATCH)`），闸门与审计只有一套口径。

    三条不重复烧钱的硬规矩：
    - 已拿到 `board_tid` 的单**只回读不重建**（它们进 `to_recover`）；
    - `ids` 里有不存在的 → 整批 400 不落库（和投递状态回写口同一条纪律：
      台账动作说"投了 12 张"就必须 12 张都投了，静默跳过会留下一张永远没人补）；
    - 建任务失败的单**留在 order_ready**、不判 failed：连板都没上，没有"失败"可言，
      判 failed 会让它出现在失败计数里、把当天的到手率算低。

    失败只重启一次（拍板口径）：板面 `fail` 的行没有原因字段，重试一次仍失败就落
    failed 并把成因写进 `error`（"我们侧判读"），交回人工——不自动补投隔夜。

    没配凭据时**当场白话拒绝**（连库都不查、不进任务台账）：`AIVIDEO_AUTH` /
    `ASSET_BOARD_BASE_URL` 是这条线的唯一开关，判据就写在 `board.is_configured()`。
    拒绝的措辞必须把"那我现在怎么办"说清楚——导出 payload 人工投板、投完走回写口记账，
    这条路一直没断。
    """
    if not board.is_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "自动投板还没启用：后台板地址（ASSET_BOARD_BASE_URL）或凭据（AIVIDEO_AUTH）"
                "没配进环境变量。这一批请照旧导出 payload 人工投板，投完用「投递状态回写」"
                "把结果记账；配好凭据后重启服务即可用本口自动投。"
            ),
        )
    ids = [_as_uuid(x, "生产单 id") for x in data.ids]
    if not ids:
        raise HTTPException(status_code=400, detail="请点名要投板的生产单（ids 为空）")
    cap = _dispatch_max_per_call()
    if len(ids) > cap:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多投 {cap} 张（号池是单日上限，一次点太多只会一起排队）；当前 {len(ids)} 张请分批",
        )
    rows = list((await db.execute(select(AssetProduction).where(AssetProduction.id.in_(ids)))).scalars().all())
    found = {str(r.id) for r in rows}
    missing = [str(i) for i in ids if str(i) not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"这些生产单不存在，整批未投（先刷新列表拿准 id）：{', '.join(missing[:5])}",
        )

    gate = await _dispatch_gate(
        db,
        rows,
        operator=current_user,
        force_risk=data.force_risk,
        force_reason=data.force_reason,
        recover_only=data.recover_only,
    )
    to_create, to_recover, blocked = gate["to_create"], gate["to_recover"], gate["blocked"]

    # ── 投递稿 override（11-06 拍板：只改投出去的那一份，库里不动）──
    overrides: Dict[str, str] = {
        str(k).strip(): (v or "").strip()
        for k, v in (data.prompt_overrides or {}).items()
        if (v or "").strip()
    }
    if overrides:
        creatable = {str(p.id): p for p in to_create}
        unknown = sorted(k for k in overrides if k not in creatable)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    "投递稿只能改这次要新建的单（回收的单投的是原稿，改了也不生效）："
                    f"这些 id 不在新建堆里：{', '.join(unknown[:5])}"
                ),
            )
        too_long = sorted(k for k, v in overrides.items() if len(v) > _PROMPT_OVERRIDE_MAX_LEN)
        if too_long:
            raise HTTPException(
                status_code=400,
                detail=f"改后的投递稿单条最长 {_PROMPT_OVERRIDE_MAX_LEN} 字：{', '.join(too_long[:5])}",
            )
        if not data.force_risk:
            book, exemptions = await _risk_lexicon(db)
            bad = {
                pid: svc.risk_block_hits(svc.scan_risk(text, lexicon=book, exemptions=exemptions))
                for pid, text in overrides.items()
            }
            bad = {k: v for k, v in bad.items() if v}
            if bad:
                parts = [
                    f"{creatable[pid].hook_code or pid[:8]}：{'、'.join(w for w, _ in hits[:3])}"
                    for pid, hits in list(bad.items())[:5]
                ]
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "改后的投递稿命中了 block 级高风险词（改稿不等于豁免，跟原稿同一道闸）："
                        + "；".join(parts)
                        + "。确要投请 admin 勾「带高风险词强行投板」并写理由"
                    ),
                )
        # 逐条留痕（fail-soft）：改前原文、改后正文（截断存）、是否踩着 force 投的。
        # 库里的 prompt_text 一字不改——投递稿只活在这一次请求（与任务台账 params 一起存档）。
        for pid, text in overrides.items():
            p = creatable[pid]
            await _write_audit(
                db,
                action="asset.production.dispatch_override",
                operator=current_user,
                target_type="asset_production",
                target_id=p.id,
                before={"hook_code": p.hook_code, "prompt_text": (p.prompt_text or "")[:800]},
                after={"override": text[:800], "risk_forced": bool(data.force_risk)},
            )


    # ── 自动拼接的入参校验（11-10 批 Q，需求⑤「钩子成片生成出来以后自动拼成可投放素材」）──
    # 判据在投出去**之前**跑完：拼装要求要是等回收到了才发现拼不了（挑的是图片／
    # 那条链接素材还没取回原片），号池已经烧了，片子只能人工另拼一遍。
    # 校验复用手工拼接口的 `_resolve_concat_input`——同一套 400 话术、同一个"图片不能当一段"
    # 的闸门，两处各写一遍必然分叉（批 M 的 R-6 就是三入口口径不一被点名）。
    concat_spec: Optional[Dict[str, Any]] = None
    concat_clear = False
    if data.concat_asset_id is not None:
        raw_concat = str(data.concat_asset_id).strip()
        if not raw_concat:
            concat_clear = True
        else:
            seg = await _resolve_concat_input(
                db, compose.SOURCE_ASSET, raw_concat, current_user, "拼接素材"
            )
            concat_spec = {
                "asset_id": raw_concat,
                "label": seg["label"],
                "order": compose.resolve_auto_order(data.concat_order),
            }

    if to_create and not data.confirm:
        # P0 的人工确认位：不带 confirm=true 就当没确认过。放在这里而不是让前端拦，
        # 是因为这条线**任何**调用方都该被拦——脚本、按钮、将来的定时任务都得先过人这一关。
        raise HTTPException(
            status_code=400,
            detail=(
                f"要新建 {len(to_create)} 张板任务，必须带 confirm=true（逐批人工确认）。"
                "投出去吃的是当天号池额度，且板面失败行没有原因字段，事后只能靠这张单自己的台账——"
                "所以这一下只能由人点。只回收已投出去的片子请带 recover_only=true，那不看 confirm"
            ),
        )
    if data.recover_only and not to_recover:
        raise HTTPException(
            status_code=400,
            detail="只回读回收模式下没有可回收的单：这几张都还没拿到 board_tid（没投上过板，无从回读）",
        )
    if not to_create and not to_recover:
        # 全被挡＝一次网都没出（不花钱），所以这里可以放心把成因说全：一线看到"投不了"
        # 必须当场知道**为什么**，否则只会反复点同一个按钮。
        # ⚠️ 措辞纪律：400 的响应体只有 detail 一个字符串，绝不写"见 blocked"这种
        # 指向不存在字段的指引（11-05 用例抓出来的：让人去结果里找一个永远不会出现的键）。
        detail = "点名的单子一张都投不了：" + "；".join(
            f"{b['hook_code'] or b['id'][:8]}：{b['reason']}" for b in blocked[:5]
        )
        if len(blocked) > 5:
            detail += f"（另有 {len(blocked) - 5} 张被挡，本条只列前 5 张）"
        raise HTTPException(status_code=400, detail=detail)

    # 11-06 拍板②：新建板任务吃号池额度，替别人批次投之前先让人确认；回收已投的单
    # 一分钱不花（`to_recover` 不过内容闸门的同一口径），不走这道闸。
    crosses = (
        await _cross_person_gate(
            db,
            operator=current_user,
            batch_ids=[p.batch_id for p in to_create],
            action_label="投板",
            confirmed=data.cross_person_confirm,
        )
        if to_create
        else []
    )
    gate["cross_person"] = crosses or None

    # 拍板②：新建的这批按**投递时刻**重新排日（人工投板用不到这条，见函数头说明）
    for p in to_create:
        _refresh_board_date(p)

    # 投板前统一挂卡：给出时对要新建的单逐张覆盖写（数组列＋兼容单值列，与 produce
    # 同一套写法），放在 _build_delivery **之前**——它逐张取卡装 payload，读的就是
    # 覆盖后的值。卡是生产输入，改的是单本身，随下面那次 commit 一起落库；
    # 回收档不动（已在板上，再挂卡也不会重建任务）。
    card_override_applied: List[str] = []
    if data.card_asset_ids is not None and to_create:
        cards = await _resolve_card_assets(db, data.card_asset_ids)
        override_card_ids = [str(a.id) for a in cards]
        override_card_key = cards[0].file_key if cards else None
        for p in to_create:
            p.card_asset_ids = override_card_ids or None
            p.character_card_key = override_card_key
        card_override_applied = [str(p.id) for p in to_create]
    card_override = (
        {"applied_to": card_override_applied, "card_asset_ids": [str(x) for x in (data.card_asset_ids or [])]}
        if card_override_applied
        else None
    )

    # 自动拼装的拼装要求**钉在生产单行上**（而不是只活在这次请求里）：
    # 回收可能是几十分钟后另一个进程做的（进程重启后带 recover_only=true 再跑一次），
    # 那时读的就是这两列——不钉行上的话"接续回收"就不会拼，一线只能手工再拼一遍，
    # 而这正是需求⑤要消掉的那一步。新建堆和回收堆都写：回收档这次刚拿到片子，照样要拼。
    # 和挂卡不同，这里**不**放在 `_build_delivery` 之前有任何副作用——那函数只看 payload。
    concat_applied: List[str] = []
    if concat_spec is not None or concat_clear:
        for p in to_create + to_recover:
            if concat_spec is not None:
                p.concat_asset_id = _as_uuid(concat_spec["asset_id"], "concat_asset_id")
                p.concat_order = concat_spec["order"]
            else:
                p.concat_asset_id = None
                p.concat_order = None
        concat_applied = [str(p.id) for p in (to_create + to_recover)]
    concat_request = (
        {**concat_spec, "applied_to": concat_applied} if concat_spec is not None
        else ({"cleared_for": concat_applied} if concat_applied else None)
    )

    # payload 与导出**同一个函数**（`_build_delivery`）：逐张取卡、保持 `card_asset_ids`
    # 顺序＝板上 picDatas 顺序、缺一张就点名。这里多花一次 MinIO 读是值当的——
    # 它是"投出去画中人不对"这类事故在烧钱前唯一还能看见它的地方。
    delivery = await _build_delivery(db, to_create, "payload") if to_create else {"payloads": []}
    # 投递稿 override 在这里落地：只改 `payload["prompt"]` 这一个键——生产单行的
    # prompt_text / 审计快照 / 漂移判定全都不碰，下一次再投仍是原稿。
    for x in delivery.get("payloads", []):
        if overrides.get(x["id"]):
            x["payload"]["prompt"] = overrides[x["id"]]
            x["prompt_overridden"] = True
    await db.commit()  # ⚠️ 建任务前必须收掉事务：板子一次 POST 最长 90s，趴着等会撞 60s 掐断
    payloads_by_id = {x["id"]: x for x in delivery.get("payloads", [])}
    card_warnings = [
        {"id": x["id"], "hook_code": x.get("hook_code"), "warnings": x.get("warnings") or []}
        for x in delivery.get("payloads", [])
        if x.get("warnings")
    ]
    # `_build_delivery` 会按自己的口径再过一道（不可交付态/无正文）。闸门已经拦过一遍，
    # 走到这里还少行的话说明两处口径分叉了——**点名报出来**，绝不静默少投。
    lost = [p for p in to_create if str(p.id) not in payloads_by_id]
    if lost:
        blocked.extend(
            {
                "id": str(p.id), "seq": p.seq, "hook_code": p.hook_code,
                "reason": "交付构造这层没给出 payload（与投递闸门口径不一致，请报给后端）",
            }
            for p in lost
        )
        to_create = [p for p in to_create if str(p.id) in payloads_by_id]

    planned_rows = sum(int(p.board_total or 1) for p in to_create)
    capacity = await _dispatch_capacity(db, planned_rows)

    if data.async_mode:
        job = await _start_asset_job(
            db,
            kind=JOB_DISPATCH,
            data=data,
            operator=current_user,
            batch_id=None,
            planned_units=len(to_create) + len(to_recover),
            cross_person=crosses,
        )
        return {
            **_job_accepted(job, "投板"),
            "precheck": {
                "will_create": len(to_create),
                "will_recover": len(to_recover),
                "planned_board_rows": planned_rows,
                "blocked": blocked,
                "card_warnings": card_warnings,
                "capacity": capacity,
                "cross_person": crosses or None,
                "prompt_overrides": sorted(overrides),
                "card_override": card_override,
                "concat": concat_request,
                "note": (
                    "预检已过：闸门按导出/回写同一套判据，payload 与导出同一个函数。"
                    "后台会建任务、轮询出片、把成片落进产物；跑完整份结果在任务台账里"
                    + (f"；其中 {len(overrides)} 张投的是改过的投递稿（库里原稿不动）" if overrides else "")
                    + (
                        f"；出片后每支自动和 {concat_spec['label']} 拼一条"
                        f"（{'钩子片在前' if concat_spec['order'] == compose.ORDER_HOOK_FIRST else '素材片段在前'}）"
                        if concat_spec is not None
                        else ("；已取消这几张的自动拼接" if concat_applied else "")
                    )
                ),
            },
        }

    return await _execute_dispatch(
        db,
        to_create=to_create,
        to_recover=to_recover,
        payloads_by_id=payloads_by_id,
        operator=current_user,
        gate=gate,
        blocked=blocked,
        capacity=capacity,
        card_warnings=card_warnings,
        recover_only=data.recover_only,
        card_override=card_override,
    )


async def _execute_dispatch(
    db: AsyncSession,
    *,
    to_create: List[AssetProduction],
    to_recover: List[AssetProduction],
    payloads_by_id: Dict[str, dict],
    operator: User,
    gate: Dict[str, Any],
    blocked: List[dict],
    capacity: Dict[str, Any],
    card_warnings: List[dict],
    recover_only: bool,
    card_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """投板执行体（后台协程走的就是这里）：建任务 → 钉 tid → 轮询 → 回收 → 落库。

    事务纪律（本函数最容易踩的一条）：**所有网络等待都发生在事务之外**。
    每一段的结构都是「读库拿数据 → commit → 出网（板子/桶）→ 开短事务写结果 → commit」。
    建任务 90s、下载 180s、轮询整批可能几十分钟，任何一个趴在开着的事务里，
    Postgres 的 `idle_in_transaction_session_timeout`（现网 60s）就会把连接掐死，
    然后一线看到"任务失败"，而板子上那批其实好端端在跑——号池白烧一遍。
    """
    created: List[dict] = []
    uncertain: List[dict] = []
    errors: List[dict] = []
    tracked: Dict[str, Dict[str, Any]] = {}   # 生产单 id → {prod, tids, tag, payload, restart_used}

    # ── ① 建任务（只有 to_create；逐张 POST，逐张拿 tid）──
    for p in to_create:
        item = payloads_by_id[str(p.id)]
        payload: Dict[str, Any] = dict(item["payload"])
        tag = str(payload.get("tag") or "")
        recovered_note: Optional[str] = None
        days = board.days_to_query([p.board_date])
        try:
            before = await board.readback(days, tag)
        except board.BoardError as e:
            # 投前快照拿不到就不敢投：拿不到"已有的 tid 集合"就没法用差集认这条新任务，
            # 硬投出去只会得到一张对不上账的单（宁可不投，也别投一张认领不了的）。
            errors.append({"id": str(p.id), "hook_code": p.hook_code, "stage": "投前快照", "error": str(e)})
            continue
        try:
            await board.create_task(payload)
            after = await board.readback(days, tag)
        except board.BoardError as e:
            # POST 失败/超时 ≠ 板上没有这条。先做一次差集回读认领：
            # 真建上了就照实记账（这条最重要——否则重投会把号池烧两遍），
            # 确实没建上才留在 order_ready 并说清"没投出去"。
            try:
                after = await board.readback(days, tag)
            except board.BoardError:
                uncertain.append({
                    "id": str(p.id), "hook_code": p.hook_code,
                    "error": f"{e}；而且回读也失败，这张单**状态未知**——请到板面看一眼再决定重投",
                })
                continue
            new_tids = [t for t in after if t not in before]
            if not new_tids:
                errors.append({"id": str(p.id), "hook_code": p.hook_code, "stage": "建任务", "error": str(e)})
                continue
            recovered_note = str(e)[:200]
        else:
            new_tids = [t for t in after if t not in before]
        if not new_tids:
            # 板子回了 succ 但按日期/tag 查不到新行——这正是 1021 那次「date 写错、
            # 120 条永久找不回」的形状。不猜它在哪，直接点名让人工去板面对。
            uncertain.append({
                "id": str(p.id), "hook_code": p.hook_code,
                "error": "建任务回了成功，但按批次日＋今天都没回读到新任务（date/tag 对不上？）："
                         "这张单先不钉 tid，请立刻到板面核对，直接重投会烧两遍额度",
            })
            continue
        _adopt_tids(p, after, new_tids)
        tracked[str(p.id)] = {"prod": p, "tids": new_tids, "tag": tag, "payload": payload, "restart_used": False}
        row: Dict[str, Any] = {"id": str(p.id), "hook_code": p.hook_code, "tids": new_tids, "to": PR_QUEUED}
        if recovered_note:
            # POST 这一步报了错，但差集回读认领到了新任务＝板子上真建上了。
            # 照实记账（并把报错原文带上），别让下一轮把它当没投过再烧一遍。
            row["recovered_after_error"] = recovered_note
        created.append(row)
        # ⚠️ 逐张提交：进程在两张中间被带走时，已建上的那张必须已经带着 tid 落库，
        # 否则重启后它既没 tid 又已被重投＝同一条烧两遍（这正是拍板②要防的事）。
        await db.commit()

    # ── ② 认领已投出去的（回读不重建）──
    for p in to_recover:
        tag = str(p.board_tag or settings.ASSET_BOARD_TAG)
        tracked[str(p.id)] = {
            "prod": p, "tids": [str(p.board_tid)], "tag": tag,
            "payload": None, "restart_used": True,   # 接续回收的这一批**不再重启**，只取片子
        }

    if not tracked:
        await _write_audit(
            db,
            action="asset.production.dispatch",
            operator=operator,
            target_type="asset_production",
            target_id=None,
            after={
                "requested": len(to_create) + len(to_recover),
                "created": 0,
                "blocked": blocked,
                "errors": errors,
                "uncertain": uncertain,
                "recover_only": recover_only,
                "cross_person": gate.get("cross_person"),
            },
        )
        await db.commit()
        counts = await _dispatch_counts(db)
        return {
            "dispatched": 0,
            "recovered": 0,
            "created": created,
            "blocked": blocked,
            "errors": errors,
            "uncertain": uncertain,
            "card_warnings": card_warnings,
            "capacity": capacity,
            "dispatch": counts,
            "message": (
                f"一张都没投出去：{len(errors)} 张建任务被板子拒绝、{len(blocked)} 张过不了闸门"
                + ("；" + str((errors or blocked)[0].get("error") or (errors or blocked)[0]["reason"])[:200]
                   if (errors or blocked) else "")
            ),
        }

    # ── ③ 轮询回收 ──
    outcome = await _poll_and_collect(db, tracked, recover_only=recover_only)

    # ── ③b 这次真落库的产物补排 1 张首帧（批 K：素材墙靠它当缩略图）──
    # 批 F 留的「豆包成片是 output_thumb 第二个写入方」就在这里接上。放在阶段收敛
    # commit 之后单独调：_start_asset_job 自己 commit、失败路径会 rollback，
    # 早调会把没提交的收敛一起卷进去。fail-soft 口径与导入/拼接侧一致——
    # 帧没排上只是墙上一时没图，片子已经真金白银回收了，不连累回收结果。
    _new_output_ids = [
        rec["_output_id"] for rec in outcome["outputs"]
        if rec.get("_inserted") and rec.get("_output_id")
    ]
    if _new_output_ids:
        _frames_note = await _enqueue_frames(
            db,
            asset_ids=[],
            output_ids=_new_output_ids,
            operator=operator,
            why=f"豆包成片回收落库（{_new_output_ids[0][:8]} 等 {len(_new_output_ids)} 条）",
        )
        outcome["frames_note"] = _frames_note.get("note")

    # ── ③c 成片到手后自动拼接（11-10 批 Q，需求⑤）──
    # 排在补帧之后、阶段收敛之前：这一步只读产物行（已经 commit 过了），
    # 拼出来的新产物行自己逐条 commit，绝不把回收结果的写回窗口拖长。
    # **整段 fail-soft**：片子是真金白银烧号池收回来的，拼不上只是"这条还得人工拼"，
    # 不许把回收结果改判失败——那会让人以为号池白烧，其实成片就在产物里。
    concat_note = await _auto_concat_recovered(db, outcome, operator=operator)
    outcome["concat"] = concat_note

    # ── ④ 阶段收敛 + 审计 + 计数 ──
    stage_by_asset = await _converge_produce_stage(db, {t["prod"].asset_id for t in tracked.values()})
    await db.commit()
    await _write_audit(
        db,
        action="asset.production.dispatch",
        operator=operator,
        target_type="asset_production",
        target_id=list(tracked)[0] if len(tracked) == 1 else None,
        before={
            "ids": sorted(tracked),
            "from": {pid: t["prod"].status for pid, t in tracked.items()},
            "board_tid_before": {pid: t["prod"].board_tid for pid, t in tracked.items()},
        },
        after={
            "recover_only": recover_only,
            "created": created,
            "card_override": card_override,
            "concat": outcome.get("concat"),
            "outcome": outcome["summary"],
            "outputs": outcome["outputs"],
            "uncertain": uncertain,
            "errors": errors,
            "blocked": blocked,
            "asset_status": stage_by_asset,
            "capacity": capacity,
            "forced_risk": {"ids": gate["forced_ids"], "reason": gate["forced_reason"]} if gate["forced_ids"] else None,
            "cross_person": gate.get("cross_person"),
            "payload_keys": list(svc.BOARD_PAYLOAD_KEYS),
        },
    )
    await db.commit()

    batch_ids = sorted({str(t["prod"].batch_id) for t in tracked.values() if t["prod"].batch_id})
    if batch_ids:
        counts = await _dispatch_counts(db, AssetProduction.batch_id.in_([uuid.UUID(b) for b in batch_ids]))
    else:
        counts = await _dispatch_counts(db)

    n_ok = sum(1 for s in outcome["summary"].values() if s["status"] == PR_SUCCESS)
    n_fail = sum(1 for s in outcome["summary"].values() if s["status"] == PR_FAILED)
    n_open = len(outcome["summary"]) - n_ok - n_fail
    return {
        "dispatched": len(created),
        "recovered": len(to_recover),
        "succeeded": n_ok,
        "failed": n_fail,
        "still_running": n_open,
        "results": outcome["summary"],
        "outputs": outcome["outputs"],
        "created": created,
        "blocked": blocked,
        "errors": errors,
        "uncertain": uncertain,
        "card_warnings": card_warnings,
        "asset_status": stage_by_asset,
        "capacity": capacity,
        "dispatch": counts,
        "concat": outcome.get("concat"),
        "message": (
            f"投板完成：新建 {len(created)} 张、接续回收 {len(to_recover)} 张 → "
            f"到手 {n_ok} / 失败 {n_fail}"
            + (f" / 还在板上 {n_open}" if n_open else "")
            + (f"，新增产物 {len(outcome['outputs'])} 支" if outcome["outputs"] else "")
            + (f"，自动拼接 {(outcome.get('concat') or {}).get('note')}"
               if (outcome.get("concat") or {}).get("note") else "")
            + (f"；闸门挡下 {len(blocked)} 张" if blocked else "")
            + (f"；{len(uncertain)} 张状态未知需人工看板" if uncertain else "")
            + f"；号池今天已吃 {capacity['total_today']} 条（软提示线 ≈{capacity['soft_cap']}，不硬拦）"
        ),
    }


async def _auto_concat_recovered(
    db: AsyncSession,
    outcome: Dict[str, Any],
    *,
    operator: User,
) -> Dict[str, Any]:
    """把这次刚落库的豆包成片，逐支和「投板时点名的那条素材」拼成可投放素材（11-10 批 Q）。

    需求⑤原话：「钩子成片生成出来以后，需要导入拼接视频自动拼接成可投放素材。」
    11-10 定下的形态是**回收后自动拼：钩子片 + 人指定的拼接素材**——第二段由人在投板那一屏
    点名，机器不挑素材、不做智能选点（11-04 已经把拼接简化成"两段直拼、顺序可选"，这里沿用）。
    拼装要求钉在 `asset_productions.concat_asset_id`／`concat_order` 上，所以**接续回收
    （进程重启后带 `recover_only=true` 再跑一次）同样会拼**，不用人再点一遍。

    四条规矩，每条都对应一个跑过才知道的坑：
    1. **一支只拼一次**：幂等键是 `asset_outputs.composed_from_output_id`。回收会跑很多轮
       （到期后再点一次、重启后补收），没有幂等键同一支片子会被拼出 N 条一模一样的产物，
       成片墙就没法对账了。
    2. **失败绝不连累回收**：逐支单独包异常，成因写进该单的 `concat_last_result` 给界面看。
       片子是真金白银烧号池收回来的，拼不上只是"这条还得人工拼"，把回收改判失败会让人
       以为号池白烧，其实成片就在产物里。
    3. **0 元**：不调模型、不调智令，纯本机 ffmpeg——和手工口同一个口径，所以不进预算闸门、
       不写任何 cost_*，但每条都留审计（谁拼的、哪两段、什么顺序）。
    4. **不在事务里等网络**：`_concat_render`（两次下载＋一次转码＋一次上传）全在事务外跑，
       跑完才开短事务写行并**逐条 commit**——中途某支炸了不许把前面已经拼好的回滚掉。

    挂行口径与手工口一致：拼接产物**不挂生产单**（`production_id=NULL`），否则生产单行上
    「成片」那列会一支算两支（批 I 定的口径）；要回溯走 `hook_production_id`
    ＋`composed_from_output_id` 两条线。
    """
    prods: Dict[str, AssetProduction] = outcome.get("prods") or {}
    recs = [
        r for r in (outcome.get("outputs") or [])
        if r.get("_inserted") and r.get("_output_id") and prods.get(str(r.get("production_id") or ""))
    ]
    wanted = [r for r in recs if getattr(prods[str(r["production_id"])], "concat_asset_id", None)]
    if not wanted:
        return {"attempted": 0, "composed": 0, "failed": 0, "already": 0, "results": [], "note": ""}

    # 一次性把要用的素材行读齐：拼接素材（可能是同一条被多张单共用）＋各单产物要挂的那条来源素材
    concat_ids = {str(prods[str(r["production_id"])].concat_asset_id) for r in wanted}
    hook_ids = {str(prods[str(r["production_id"])].asset_id) for r in wanted}
    by_id: Dict[str, AssetItem] = {
        str(a.id): a
        for a in (
            await db.execute(
                select(AssetItem).where(AssetItem.id.in_([uuid.UUID(x) for x in (concat_ids | hook_ids)]))
            )
        ).scalars().all()
    }
    # 幂等预查：这些产物支里，哪几支以前已经自动拼过了（重跑回收就会命中）
    already = {
        str(u)
        for u in (
            await db.execute(
                select(AssetOutput.composed_from_output_id).where(
                    AssetOutput.composed_from_output_id.in_(
                        [uuid.UUID(str(r["_output_id"])) for r in wanted]
                    )
                )
            )
        ).scalars().all()
        if u
    }
    await db.commit()  # ⚠️ 收掉这次读事务：下面每一支都要出网几十秒（现网事务上限 60s）

    results: List[Dict[str, Any]] = []
    per_prod: Dict[str, Dict[str, Any]] = {}
    composed_output_ids: List[str] = []
    n_ok = n_failed = n_already = 0
    for rec in wanted:
        prod = prods[str(rec["production_id"])]
        out_id = str(rec["_output_id"])
        cid = str(prod.concat_asset_id)
        order = compose.resolve_auto_order(prod.concat_order)
        item: Dict[str, Any] = {
            "production_id": str(prod.id), "hook_code": prod.hook_code,
            "from_output_id": out_id, "order": order,
        }
        acc = per_prod.setdefault(
            str(prod.id), {"ok": 0, "failed": 0, "already": 0, "last_error": None, "order": order,
                           "concat_asset_id": cid}
        )
        if out_id in already:
            # 同一支不拼第二遍：这不是失败，是"上一轮已经拼好了"
            n_already += 1
            acc["already"] += 1
            item.update({"result": "already", "reason": "这支此前已经自动拼过了（幂等键命中），没重拼"})
            results.append(item)
            continue
        material = by_id.get(cid)
        if material is None:
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = "拼接素材已不在库里（被删了？）"
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue
        if material.media_kind == MEDIA_IMAGE:
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = _image_block_reason(material, "拼接")
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue
        if not material.file_key:
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = (
                f"拼接素材（{material.code}）还没有可拼的文件：链接素材要先取回原片"
                "（`POST /assets/resolve`），文件素材要确认上传成功"
            )
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue
        if not rec.get("file_key"):
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = "豆包成片没有落桶路径（回收那步就没成），无法拼接"
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue

        hook_seg = {
            "bucket": rec.get("bucket") or settings.MINIO_BUCKET_RAW,
            "file_key": rec["file_key"],
            "file_name": rec.get("file_name") or f"{prod.hook_code or out_id[:8]}.mp4",
            "label": f"钩子·{prod.hook_code or rec.get('file_name') or out_id[:8]}",
        }
        material_seg = _asset_concat_segment(material)
        first, second = (
            (material_seg, hook_seg) if order == compose.ORDER_TAIL_AFTER_HOOK
            else (hook_seg, material_seg)
        )
        hook_asset = by_id.get(str(prod.asset_id))
        raw_name = f"{prod.hook_code or 'HOOK'}×{material.code}"
        safe = "".join(c for c in raw_name if c not in '/\\:*?"<>|').strip()[:80] or out_id[:12]
        work_dir = tempfile.mkdtemp(prefix="asset_auto_concat_")
        try:
            rendered = await _concat_render(
                first, second,
                work_dir=work_dir,
                safe_name=safe,
                key_prefix_code=(hook_asset.code if hook_asset is not None else str(prod.asset_id)[:8]),
            )
        except HTTPException as exc:
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = str(exc.detail)[:400]
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue
        except Exception as exc:  # noqa: BLE001 — 拼接炸不许把回收带崩（规矩 2）
            logger.exception("回收自动拼接异常（生产单 %s）", prod.id)
            n_failed += 1
            acc["failed"] += 1
            acc["last_error"] = f"{type(exc).__name__}: {exc}"[:400]
            item.update({"result": "failed", "error": acc["last_error"]})
            results.append(item)
            continue
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        # 短事务：写产物行 + 来源素材的拼接阶段 + 审计，写完立刻 commit（规矩 4）
        out_row = AssetOutput(
            production_id=None,
            asset_id=prod.asset_id,
            kind=compose.KIND_COMPOSED,
            hook_production_id=prod.id,
            composed_from_output_id=uuid.UUID(out_id),
            **rendered["output_kwargs"],
        )
        db.add(out_row)
        before_stage = hook_asset.stage_compose if hook_asset is not None else None
        before_status = hook_asset.status if hook_asset is not None else None
        if hook_asset is not None:
            # 和手工口同一条：拼成功就把五阶段里唯一"靠拼接才点亮"的 compose 置 success，
            # 派生态随之从 producing/composing 走到 ready——"可投放素材"就是 ready 这个态。
            hook_asset.stage_compose = STAGE_SUCCESS
            hook_asset.status = svc.derive_status(
                {
                    "import": hook_asset.stage_import,
                    "prompt": hook_asset.stage_prompt,
                    "summary": hook_asset.stage_summary,
                    "produce": hook_asset.stage_produce,
                    "compose": STAGE_SUCCESS,
                },
                bool(hook_asset.has_approved_copy),
            )
        await _write_audit(
            db,
            action="asset.concat.auto",
            operator=operator,
            target_type="asset_output",
            target_id=None,
            before={
                "production_id": str(prod.id),
                "from_output_id": out_id,
                "asset_id": str(prod.asset_id),
                "stage_compose": before_stage,
                "status": before_status,
            },
            after={
                "first": first["label"],
                "second": second["label"],
                "order": order,
                "concat_asset_id": cid,
                "target_resolution": out_row.resolution,
                "duration": out_row.duration,
                "file_key": out_row.file_key,
                "cost": 0,
                "elapsed_seconds": rendered["elapsed_seconds"],
            },
        )
        await db.commit()
        await db.refresh(out_row)
        composed_output_ids.append(str(out_row.id))
        n_ok += 1
        acc["ok"] += 1
        item.update({
            "result": "composed", "output_id": str(out_row.id),
            "file_key": out_row.file_key, "with": material_seg["label"],
            "resolution": out_row.resolution, "duration": out_row.duration,
        })
        results.append(item)

    # 每单一份「拼没拼」结果写回行上（界面列 + 台账话术都读它，不参与任何判定）
    for pid, acc in per_prod.items():
        prod = prods.get(pid)
        if prod is None:
            continue
        if acc["failed"] and not acc["ok"]:
            status = "failed"
        elif acc["failed"]:
            status = "partial"
        elif acc["ok"]:
            status = "success"
        else:
            status = "already"
        prod.concat_last_result = {
            "status": status,
            "ok": acc["ok"], "failed": acc["failed"], "already": acc["already"],
            "order": acc["order"],
            "concat_asset_id": acc["concat_asset_id"],
            "last_error": acc["last_error"],
            "at": utc_iso(datetime.utcnow()),
        }
    await db.commit()

    # 拼出来的产物也补 1 张首帧（成片墙靠它当缩略图，与手工口/回收侧同一个动作）。
    # fail-soft：帧没排上只是墙上一时没图，产物已经落库了。
    frames_note = None
    if composed_output_ids:
        frames_note = await _enqueue_frames(
            db,
            asset_ids=[],
            output_ids=composed_output_ids,
            operator=operator,
            why=f"回收自动拼接（{len(composed_output_ids)} 条）",
        )

    note = (
        f"自动拼接：拼成 {n_ok} 支"
        + (f"、失败 {n_failed} 支（成因见生产单「拼没拼」，可手工另拼）" if n_failed else "")
        + (f"、此前已拼 {n_already} 支" if n_already else "")
    )
    return {
        "attempted": len(wanted), "composed": n_ok, "failed": n_failed, "already": n_already,
        "results": results, "note": note,
        "frames_note": (frames_note or {}).get("note"),
    }


def _adopt_tids(p: AssetProduction, board_rows: Dict[str, Dict[str, Any]], new_tids: List[str]) -> None:
    """把刚建上的板任务认领给这张生产单：钉 tid/rgid、落 queued、attempts+1。

    `board_tid` 是**逐条**主键，一行只有一个位置：一条 create 出 `total` 个任务时，
    这里存第一个（代表），其余 tid 由**本次协程在内存里**逐个跟踪并各自落一条产物。
    这就是"每张单 board_total=1"这条口径存在的原因（拍板④）：total>1 时其余几版
    只能靠 name＋批次日回查，跨天接续回收会认不全，所以**批量请开 N 张单、每张 total=1**。
    """
    first = board_rows.get(new_tids[0]) or {}
    p.board_tid = str(new_tids[0])[:60]
    if first.get("rgid"):
        p.board_rgid = str(first["rgid"])[:60]
    p.status = PR_QUEUED
    p.attempts = int(p.attempts or 0) + 1
    if p.started_at is None:
        p.started_at = datetime.utcnow()
    p.completed_at = None
    p.error = None
    # 批 L：认领瞬间先钉一个初始板侧状态——从这一刻到轮询第一轮回读之间
    # （最长一个轮询间隔），界面上有「已投板」可看，而不是干等列全空。
    p.board_last_status = "已投板"
    p.board_last_check_at = datetime.utcnow()


async def _poll_and_collect(
    db: AsyncSession,
    tracked: Dict[str, Dict[str, Any]],
    *,
    recover_only: bool,
) -> Dict[str, Any]:
    """轮询板面直到这批全终态或到期，其间把 succ 的成片下载落桶并写产物。

    节奏：`ASSET_BOARD_POLL_INTERVAL`（默认 45s）一轮、最多 `ASSET_BOARD_POLL_MAX_MINUTES`
    （默认 45 分钟，实测单条 45s 一轮、25 分钟内到手）。**到期不判失败**：还在板上跑的单
    留在 queued/running，由人再点一次回收（`recover_only=true`）——按拍板口径
    「不自动补投隔夜」，把没出片的单判成失败会诱导人去重投，那才是真烧钱。

    三条判读规矩都来自板子的实测行为，别"优化"掉：
    - `waiting`／看不懂的词＝**还在跑**。判死→重投→同一条烧两遍号池（11-04 真踩过）；
    - 回读失败／这一天查不到＝**跳过这一轮**，不是失败（11-04 反推轮询同一条教训）；
    - `total>1` 的单**全版到手才落 success**：先判成功，剩下的版次再没人回收。
    """
    work_dir = tempfile.mkdtemp(prefix="asset_board_")
    pids = [uuid.UUID(pid) for pid in tracked]
    # 已经落过库的 outUrl：防重复插产物（同一张单回收两次／进程重启后重新跟踪同一批）
    seen_urls = {
        str(u)
        for u in (
            await db.execute(
                select(AssetOutput.board_out_url).where(
                    AssetOutput.production_id.in_(pids), AssetOutput.board_out_url.is_not(None)
                )
            )
        ).scalars().all()
        if u
    }
    await db.commit()  # ⚠️ 收掉事务：下面每一轮出网（回读/下载/传桶）都可能几十秒到两三分钟

    summary: Dict[str, Dict[str, Any]] = {
        pid: {
            "id": pid,
            "hook_code": t["prod"].hook_code,
            "asset_id": str(t["prod"].asset_id),
            "board_total": int(t["prod"].board_total or 1),
            "tids": list(t["tids"]),
            "status": t["prod"].status,
            "board_status": None,
            "outputs": [],
            "restarted": False,
        }
        for pid, t in tracked.items()
    }
    outputs: List[dict] = []
    # 批 M（评审一·P1-1）：prod 引用一开始就钉死。人工让位的行会从 tracked 摘除，
    # 但已回读到手的产物仍要按它落库（引用还在 prod_refs 里，不会 KeyError）。
    prod_refs: Dict[str, AssetProduction] = {pid: t["prod"] for pid, t in tracked.items()}

    async def _take_outputs(pid: str, t: Dict[str, Any], rows: List[Dict[str, Any]], s: Dict[str, Any]) -> None:
        """把这几条 succ 任务下载→落桶，攒进 outputs（**不碰数据库**，写库统一在轮询外）。"""
        for idx, r in enumerate(rows, start=1):
            url = str(r.get("outUrl") or "")
            if not url or url in seen_urls:
                continue
            try:
                rec = await _fetch_board_output(t["prod"], r, work_dir, index=idx)
            except board.BoardError as e:
                # 片子取不回**不改投递状态**：单子在板上是真成功了，取文件是我们这侧的事。
                # 混成 failed 会让"今天的到手率"看不出到底谁掉了。
                s.setdefault("download_errors", []).append({"tid": str(r.get("tid") or ""), "error": str(e)[:200]})
                continue
            seen_urls.add(url)
            outputs.append({"production_id": pid, **rec})
            s["outputs"].append(rec["file_key"])

    deadline = time.monotonic() + _board_poll_max_minutes() * 60
    rounds = 0
    read_fail_rounds = 0
    # 批 M（评审一·P1-1）：人工回写 vs 轮询写回的并发防护。
    # 轮询持有的是 dispatch 时加载的 ORM 对象（expire_on_commit=False，整轮不重读库），
    # 期间人工经投递状态回写口改状态（failed→queued 重投是迁移表明确放行的路）：
    # 按旧快照直接写回就是 lost update；更糟的是人工改回 queued 后板面 fail 还会按
    # 旧快照再自动重启一次——同一条烧两遍号池。
    # 规矩：库里 status ≠ 本轮快照（或行没了）＝所有权已交还人工——这一行**整行让位**：
    # 恢复轮前快照（撤销本轮全部改动）、状态/心跳一律不写、从 tracked 摘除不再跟踪，
    # summary 里留 note 点名。已下载到手的产物照插：那是板侧已发生的事实（本单 tid
    # 出的片子），与状态互不覆盖。
    # 每轮查两次：开工时一次（防按旧快照重启烧号池），写回前一次 SELECT ... FOR UPDATE
    # （行锁把「轮询 commit vs 人工回写 UPDATE」串行化，写回窗口从整轮几分钟缩到毫秒级）。
    # 两次都裹在 no_autoflush 里：本轮的改动此刻还只在内存里，绝不能被 autoflush 先冲下去，
    # 否则重读读到的是自己的旧快照、判「没人动过」就白防了。
    _POLLER_OWNED_COLS = (
        "status", "error", "completed_at", "board_tid", "board_rgid",
        "attempts", "started_at", "board_last_status", "board_last_check_at",
    )

    def _reown(pid: str, db_status: Optional[str], when: str) -> None:
        """人工已接管的行整行让位：摘出跟踪、恢复轮前快照、summary 里点名。"""
        t = tracked.pop(pid, None)
        pending.pop(pid, None)
        if t is not None:
            for k, v in pre_round_attrs[pid].items():
                setattr(t["prod"], k, v)
        s = summary[pid]
        if db_status:
            s["status"] = db_status
            s["note"] = (
                f"{when}人工已把状态改成 {db_status}（轮询按快照记的还是 {pre_round_status[pid]}）："
                "这行交还人工——轮询不再跟踪、本轮状态与板侧心跳都没有写回"
                + ("；已回读到的产物照常落库" if when == "写回前" else "")
            )
        else:
            s["note"] = f"{when}这张生产单已不存在（人工删除？）：整行让位，轮询不再跟踪、不写回"

    while True:
        pending = {pid: t for pid, t in tracked.items() if summary[pid]["status"] not in (PR_SUCCESS, PR_FAILED)}
        if not pending:
            break
        if time.monotonic() > deadline:
            for pid in pending:
                summary[pid]["note"] = (
                    f"轮询到期（{_board_poll_max_minutes():g} 分钟）仍没出终态：板子上还在跑，"
                    "单子留在现在这个态不判失败；稍后带 recover_only=true 再回收一次即可"
                )
            break
        pre_round_status = {pid: str(summary[pid]["status"]) for pid in pending}
        pre_round_attrs = {
            pid: {k: getattr(t["prod"], k) for k in _POLLER_OWNED_COLS}
            for pid, t in pending.items()
        }
        # ① 开工重读：上一轮 commit 之后人工可能已改状态。改走的行当场摘除——
        #    尤其不能让它在下面的板面 fail 分支里按旧快照再自动重启一次（烧两遍号池）。
        stale_start: Dict[str, Optional[str]] = {}
        with db.sync_session.no_autoflush:
            for pid in list(pending):
                db_status = (
                    await db.execute(
                        select(AssetProduction.status).where(AssetProduction.id == uuid.UUID(pid))
                    )
                ).scalar_one_or_none()
                if db_status is None or db_status != pre_round_status[pid]:
                    stale_start[pid] = db_status
        if stale_start:
            for pid, db_status in stale_start.items():
                _reown(pid, db_status, "轮询开工重读：")
        # ⚠️ 无论有没有人让位都要收掉这个事务：开工重读的 SELECT 已经把事务打开了，
        # 不收的话它会一直开着度过整轮出网（回读/下载几分钟），撞上现网 60s 的
        # idle_in_transaction_session_timeout 把连接掐死（见 _dispatch_board 头注释）。
        # 此刻本轮还没有任何改动，commit 是干净的收尾。
        await db.commit()
        rounds += 1
        # 按 tag 分组回读（不同 tag 是不同拥有者的账，合一次查询会把别人的任务读进来）
        snapshots: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for tag in {t["tag"] for t in pending.values()}:
            days = board.days_to_query([x["prod"].board_date for x in pending.values() if x["tag"] == tag])
            try:
                snapshots[tag] = await board.readback(days, tag)
            except board.BoardError as e:
                read_fail_rounds += 1
                snapshots[tag] = {}
                for pid, t in pending.items():
                    if t["tag"] == tag:
                        summary[pid]["last_read_error"] = str(e)[:200]
        changed = False
        # ⚠️ 对快照迭代：重启前重读若发现行被人工改走，_reown 会当场把行从 pending
        # 摘掉（整行让位），直接迭代 .items() 会撞 dictionary changed size。
        for pid, t in list(pending.items()):
            rows = snapshots.get(t["tag"], {})
            mine = [rows[tid] for tid in t["tids"] if tid in rows]
            s = summary[pid]
            if not mine:
                # 查不到自己的 tid：可能是回读这一天失败（上面记了 last_read_error），
                # 也可能是板子把行挪走了。两种都不判死，下一轮再说。
                continue
            s["board_status"] = "/".join(sorted({str(r.get("status") or "").lower() for r in mine}))
            # 批 L（投放进度可视化）：板侧状态写回生产单行。就算这轮没有任何状态迁移
            # （还在跑），也让「板子还活着、上轮检查是什么时候」落到库上——所以写回
            # 本身计 changed，走本轮末尾那次短事务 commit（出网都在事务外，不冲突）。
            t["prod"].board_last_status = s["board_status"][:60]
            t["prod"].board_last_check_at = datetime.utcnow()
            changed = True
            got = [r for r in mine if board.state_after_board(r.get("status")) == "success"]
            bad = [r for r in mine if str(r.get("status") or "").strip().lower() == board.STATE_FAIL]
            if got and len(got) == len(mine):
                # 全版都 succ＝板侧事实已定，状态一律 success。个别片子没取回来
                # 不改这个结论——缺的片子在 `download_errors` 里点名，回收动作再做一次即可。
                await _take_outputs(pid, t, got, s)
                t["prod"].status = PR_SUCCESS
                t["prod"].completed_at = datetime.utcnow()
                t["prod"].error = None
                s["status"] = PR_SUCCESS
                changed = True
            elif bad and not got:
                if t["payload"] and not t["restart_used"] and not recover_only:
                    # 批 M（评审一·P1-1）：重启是**第二次烧号池**的动作，动手前用独立短会话
                    # 再读一眼库里的真实状态。主会话此刻不能开事务（下面紧跟出网，开着事务
                    # 等网络会撞 60s idle 掐断），也不能 commit（会把其他行本轮还没重读过的
                    # 改动先写下去）——所以借 _database 的模块属性开一次性会话（测试替身
                    # 重新指 factory 时这里自动跟着走）。人工若已把状态改走（判读后改回
                    # queued 准备自己重投是最典型形状），这行当场让位：绝不按旧快照再重启。
                    async with _database.async_session_factory() as probe:
                        live_status = (
                            await probe.execute(
                                select(AssetProduction.status).where(AssetProduction.id == uuid.UUID(pid))
                            )
                        ).scalar_one_or_none()
                    if live_status is None or live_status != pre_round_status[pid]:
                        _reown(pid, live_status, "重启前重读，")
                        changed = True
                        continue
                    # 失败**只重启一次**（拍板口径）：同一条 payload 再建一次任务、重新认领 tid
                    t["restart_used"] = True
                    days = board.days_to_query([t["prod"].board_date])
                    try:
                        before = await board.readback(days, t["tag"])
                        await board.create_task(t["payload"])
                        after = await board.readback(days, t["tag"])
                    except board.BoardError as e:
                        _mark_dispatch_failed(t["prod"], s, f"板面失败，重启这步也没成：{e}")
                        changed = True
                        continue
                    new_tids = [x for x in after if x not in before]
                    if not new_tids:
                        _mark_dispatch_failed(
                            t["prod"], s,
                            "板面失败，重启的任务建上了但回读不到（date/tag 对不上？）："
                            "停在 failed 交人工看板，别再自动重投",
                        )
                        changed = True
                        continue
                    _adopt_tids(t["prod"], after, new_tids)
                    t["tids"] = new_tids
                    s["tids"] = list(new_tids)
                    s["restarted"] = True
                    s["board_status"] = None
                    s.pop("last_read_error", None)
                    changed = True
                    # 批 L：重启后旧板侧状态已不属于新任务，_adopt_tids 已重钉「已投板」。
                else:
                    _mark_dispatch_failed(
                        t["prod"], s,
                        "板面 status=fail（板上失败行没有原因字段，这条成因是我们侧判读）；"
                        + (
                            "已按口径重启过一次，仍失败"
                            if t["restart_used"] and t["payload"]
                            else "本次是只回读回收，不重启"
                        ),
                    )
                    changed = True
            else:
                # 还在跑：先把手里已经 succ 的版次取回来（多版单里"先出的那版"），
                # 再把单子标成 running——有 outUrl 或状态非终态都是"正在出片"的实证。
                if got:
                    await _take_outputs(pid, t, got, s)
                if t["prod"].status != PR_RUNNING:
                    t["prod"].status = PR_RUNNING
                    s["status"] = PR_RUNNING
                    changed = True
        if changed:
            # ② 写回前重读（FOR UPDATE）：此刻本轮改动还只在内存里、本短事务还没发过
            #    任何语句，no_autoflush 保证这次 SELECT 读到的是最后一次提交的真值——
            #    状态已被人工改走的行整行让位（恢复快照＋摘除＋note），剩下的照常写回。
            stale_end: Dict[str, Optional[str]] = {}
            with db.sync_session.no_autoflush:
                for pid in list(pending):
                    db_status = (
                        await db.execute(
                            select(AssetProduction.status)
                            .where(AssetProduction.id == uuid.UUID(pid))
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if db_status is None or db_status != pre_round_status[pid]:
                        stale_end[pid] = db_status
            for pid, db_status in stale_end.items():
                _reown(pid, db_status, "写回前，")
            # 短事务：只在真的多了产物/改了状态时开一次，写完立刻 commit（出网都在事务外）
            for rec in outputs:
                if rec.get("_inserted"):
                    continue
                prod = prod_refs[rec["production_id"]]
                new_out = AssetOutput(
                    production_id=prod.id,
                    asset_id=prod.asset_id,
                    **{
                        k: v
                        for k, v in rec.items()
                        if k not in ("production_id", "tid", "rgid", "doubao_account", "_inserted")
                    },
                )
                db.add(new_out)
                # 批 K：把生成的产物 id 留在 rec 里——轮询结束后要按它排首帧任务
                await db.flush()
                rec["_output_id"] = str(new_out.id)
                rec["_inserted"] = True
            await db.commit()
        else:
            await asyncio.sleep(_board_poll_interval_seconds())

    shutil.rmtree(work_dir, ignore_errors=True)
    return {
        "summary": summary,
        "outputs": outputs,
        # 批 Q：把 prod 引用一并交出去。人工让位的行会从 tracked 摘除（`_reown`），
        # 但它这次到手的产物仍要按它落库、也仍要拼——自动拼接若只认 tracked，
        # 「刚被人工改过状态的单」就会静默少拼一条。
        "prods": prod_refs,
        "rounds": rounds,
        "read_fail_rounds": read_fail_rounds,
    }


def _mark_dispatch_failed(p: AssetProduction, s: Dict[str, Any], reason: str) -> None:
    p.status = PR_FAILED
    p.error = str(reason)[:500]
    p.completed_at = datetime.utcnow()
    s["status"] = PR_FAILED
    s["error"] = p.error


# ──────────────────────────────────────────────
# 产物 / 反推任务详情（P0 只读；写入属 P1）
# ──────────────────────────────────────────────


@router.get("/assets/outputs")
async def list_outputs(
    asset_id: Optional[str] = None,
    production_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    kind: Optional[str] = None,
    qc_status: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """产物列表。11-04 起 `kind=composed`（简单拼接）有写入方，其余仍等 P1。

    批 K（成片素材墙）：加 `batch_id`（按素材的批次收敛，拼接产物不挂生产单也查得到）、
    `offset` + `total`（墙要翻页要计数）、每行带 `asset_code`（卡片上认得出是哪条素材）
    和 `thumb_url`（产物首帧 presign，墙当缩略图；没帧就 null，前端画「没有预览图」）。
    `qc_status`（2026-11-07）：墙上验收筛选真正生效——此前前端筛了但没传参，纯摆设。
    """
    conds = []
    if asset_id:
        conds.append(AssetOutput.asset_id == _as_uuid(asset_id, "asset_id"))
    if production_id:
        conds.append(AssetOutput.production_id == _as_uuid(production_id, "production_id"))
    if batch_id:
        # 走素材侧收敛而不是生产单侧：拼接产物 production_id 可空，但 asset_id 永远在。
        # "none" 是哨兵＝未挂批次的素材（分组清单里「未挂批次」那组展开时用）。
        if batch_id == "none":
            conds.append(
                AssetOutput.asset_id.in_(select(AssetItem.id).where(AssetItem.batch_id.is_(None)))
            )
        else:
            conds.append(
                AssetOutput.asset_id.in_(
                    select(AssetItem.id).where(AssetItem.batch_id == _as_uuid(batch_id, "batch_id"))
                )
            )
    if kind:
        conds.append(AssetOutput.kind == kind)
    if qc_status:
        conds.append(AssetOutput.qc_status == qc_status)
    if owner not in (None, "", "me", "all"):
        raise HTTPException(status_code=400, detail="owner 只支持 me（我的链路）或 all（全量），缺省=all")
    if owner == "me":
        # A′：成片按投产人隔离（IN 半连接，不是 INNER JOIN——不丢行）。
        # 拼接产物（production_id NULL，不挂生产单）＝公共，所有视图可见。
        conds.append(or_(
            AssetOutput.production_id.is_(None),
            AssetOutput.production_id.in_(
                select(AssetProduction.id).where(AssetProduction.created_by == current_user.id)
            ),
        ))
    base = select(AssetOutput).where(and_(*conds)) if conds else select(AssetOutput)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    )
    rows = list(
        (
            await db.execute(
                base.order_by(AssetOutput.created_at.desc())
                .offset(max(0, offset))
                .limit(min(max(1, limit), 300))
            )
        ).scalars().all()
    )

    # 卡片要认素材码 / 生产单号：两把小映射，别在循环里逐行查
    codes: Dict[uuid.UUID, str] = {}
    prod_names: Dict[uuid.UUID, str] = {}
    if rows:
        asset_rows = (
            await db.execute(
                select(AssetItem.id, AssetItem.code).where(AssetItem.id.in_({o.asset_id for o in rows}))
            )
        ).all()
        codes = {r[0]: r[1] for r in asset_rows}
        prod_rows = (
            await db.execute(
                select(AssetProduction.id, AssetProduction.hook_code, AssetProduction.created_by).where(
                    AssetProduction.id.in_({o.production_id for o in rows if o.production_id})
                )
            )
        ).all()
        prod_names = {r[0]: r[1] for r in prod_rows}
        # A′：投产人显示名（片层灰字标注；拼接产物 production_id NULL＝公共，前端标注）
        prod_owner_names = await _user_names(db, {r[2] for r in prod_rows if r[2]})
        # 首帧：每个产物最多 1 张 output_thumb（部分唯一索引保证）
        frame_rows = (
            await db.execute(
                select(AssetFrame).where(
                    AssetFrame.output_id.in_([o.id for o in rows]),
                    AssetFrame.kind == FRAME_OUTPUT_THUMB,
                )
            )
        ).scalars().all()
        thumb_urls: Dict[uuid.UUID, Optional[str]] = {}
        for f in frame_rows:
            thumb_urls[f.output_id] = await get_presigned_url(
                f.bucket or settings.MINIO_BUCKET_RAW,
                f.file_key,
                expires_seconds=_FRAME_URL_TTL_SECONDS,
            )
    else:
        thumb_urls = {}

    return {
        "total": total,
        "items": [
            {
                "id": str(o.id),
                "asset_id": str(o.asset_id),
                # 11-04 起可空（拼接产物不挂生产单）：裸 str(None) 会回字符串 "None"，
                # 前端拿到就当有生产单了——必须显式回 null。
                "production_id": str(o.production_id) if o.production_id else None,
                "kind": o.kind,
                "file_name": o.file_name,
                "file_key": o.file_key,
                "bucket": o.bucket,
                "duration": o.duration,
                "file_size": o.file_size,
                "resolution": o.resolution,
                "qc_status": o.qc_status,
                "qc_note": o.qc_note,
                "created_at": utc_iso(o.created_at),
                "downloaded_at": utc_iso(o.downloaded_at) if o.downloaded_at else None,
                # 批 K：卡片标注 + 缩略图（没帧 = null，前端画占位不报错）
                "asset_code": codes.get(o.asset_id),
                "hook_code": prod_names.get(o.production_id) if o.production_id else None,
                "owner_name": prod_owner_names.get(o.production_id) if o.production_id else None,
                "thumb_url": thumb_urls.get(o.id),
            }
            for o in rows
        ]
    }


async def _outputs_awaiting(
    db: AsyncSession, *, owner: Optional[str], current_user: User, batch_id: Optional[str]
) -> dict:
    """成片墙空态要说的三句真话（11-10 用户口径「我投去了，生产出来了就给我看，不要搞这么复杂」）。

    墙空着的时候，一线分不清三件事：①**只建了单还没投板**、②**投出去了还在出片**、
    ③**回收过了但这一屏的筛选把它藏了**。以前只会说「还没有成片」，三件事全糊在一句里，
    人只能自己去猜——猜不动就以为系统坏了。这里按同一套 owner／批次口径把数算出来，
    空态直接摆「20 条已投板，出片了会自动回到这里」。

    只数生产单，不动 `kind`／`qc` 筛选：那两个是「成片怎么摆」的口径，
    和「有没有在途的单」没关系，掺进来只会让人更看不懂。
    """
    p_conds = []
    if owner == "me":
        p_conds.append(AssetProduction.created_by == current_user.id)
    if batch_id:
        p_conds.append(AssetProduction.batch_id == _as_uuid(batch_id, "batch_id"))

    waiting = never_dispatched = 0
    for st, tid in (
        await db.execute(
            select(AssetProduction.status, AssetProduction.board_tid).where(*p_conds)
        )
    ).all():
        if st in (PR_SUCCESS, PR_FAILED):
            continue  # 终态：成片有没有，墙自己会说话
        if st in (PR_QUEUED, PR_RUNNING) or tid:
            waiting += 1  # 投出去了（含人工回写过 tid 但状态还停在待投的老单）
        elif st == PR_ORDER_READY:
            never_dispatched += 1  # 只建了单，一张号都没占

    o_conds = []
    if owner == "me":
        o_conds.append(
            or_(
                AssetOutput.production_id.is_(None),
                AssetOutput.production_id.in_(
                    select(AssetProduction.id).where(AssetProduction.created_by == current_user.id)
                ),
            )
        )
    if batch_id:
        o_conds.append(
            AssetOutput.asset_id.in_(
                select(AssetItem.id).where(AssetItem.batch_id == _as_uuid(batch_id, "batch_id"))
            )
        )
    last_at = (
        await db.execute(select(func.max(AssetOutput.created_at)).where(*o_conds))
    ).scalar()

    return {
        "waiting_on_board": waiting,
        "order_ready_not_dispatched": never_dispatched,
        "last_output_at": utc_iso(last_at) if last_at else None,
    }


@router.get("/assets/outputs/groups")
async def list_output_groups(
    group_by: str = "asset",
    batch_id: Optional[str] = None,
    kind: Optional[str] = None,
    qc_status: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """成片墙两级视图的第一级：按素材（钩子）或按批次聚合一层清单。

    2026-11-07 用户口径：墙不再一屏摊开所有片子——先按批次/钩子列一层清单
    （每组带成片数＋最近回收时间＋最新一条的缩略图），点开一层再看这组的墙。
    聚合口径与 /assets/outputs 同一套（batch_id 走素材侧收敛；kind/qc 同参数）；
    缩略图取该组最新一条的首帧 presign（1h TTL，与列表口同款）。
    """
    if group_by not in ("asset", "batch"):
        raise HTTPException(status_code=400, detail="group_by 只支持 asset（按素材/钩子）或 batch（按批次）")
    if owner not in (None, "", "me", "all"):
        raise HTTPException(status_code=400, detail="owner 只支持 me（我的链路）或 all（全量），缺省=all")
    conds = []
    if kind:
        conds.append(AssetOutput.kind == kind)
    if qc_status:
        conds.append(AssetOutput.qc_status == qc_status)
    if owner == "me":
        # A′：组层计数与片层同一套 owner 口径（IN 半连接；拼接产物＝公共，各组都可见）
        conds.append(or_(
            AssetOutput.production_id.is_(None),
            AssetOutput.production_id.in_(
                select(AssetProduction.id).where(AssetProduction.created_by == current_user.id)
            ),
        ))
    if batch_id:
        conds.append(
            AssetOutput.asset_id.in_(
                select(AssetItem.id).where(AssetItem.batch_id == _as_uuid(batch_id, "batch_id"))
            )
        )
    cap = min(max(1, limit), 200)

    if group_by == "asset":
        rows = list(
            (
                await db.execute(
                    select(
                        AssetOutput.asset_id,
                        func.count().label("cnt"),
                        func.max(AssetOutput.created_at).label("latest"),
                    )
                    .where(and_(*conds))
                    .group_by(AssetOutput.asset_id)
                    .order_by(func.max(AssetOutput.created_at).desc())
                    .limit(cap)
                )
            ).all()
        )
        keys = [r[0] for r in rows]
        items_meta: Dict[uuid.UUID, dict] = {}
        hook_map: Dict[uuid.UUID, List[str]] = {}
        if keys:
            for r in (
                await db.execute(
                    select(AssetItem.id, AssetItem.code, AssetItem.title, AssetItem.batch_id).where(
                        AssetItem.id.in_(keys)
                    )
                )
            ).all():
                items_meta[r[0]] = {"code": r[1], "title": r[2], "batch_id": r[3]}
            # 钩子号挂在生产单上：按素材汇总去重，让人在列表层就能认出「这是哪条钩子」
            prods = (
                await db.execute(
                    select(AssetProduction.asset_id, AssetProduction.hook_code).where(
                        AssetProduction.asset_id.in_(keys),
                        AssetProduction.hook_code.is_not(None),
                    )
                )
            ).all()
            for aid, hc in prods:
                bucket = hook_map.setdefault(aid, [])
                if hc not in bucket:
                    bucket.append(hc)
        groups = [
            {
                "key": str(aid),
                "label": (items_meta.get(aid, {}).get("code") or str(aid)[:8])
                + (
                    f"｜{items_meta[aid]['title']}"
                    if items_meta.get(aid, {}).get("title")
                    else ""
                ),
                "sub": "钩子 " + "、".join(hook_map.get(aid, [])) if hook_map.get(aid) else None,
                "count": int(cnt),
                "latest_at": utc_iso(latest) if latest else None,
                "_latest": latest,
            }
            for aid, cnt, latest in rows
        ]
    else:
        rows = list(
            (
                await db.execute(
                    select(
                        AssetItem.batch_id,
                        func.count().label("cnt"),
                        func.max(AssetOutput.created_at).label("latest"),
                    )
                    .join(AssetItem, AssetItem.id == AssetOutput.asset_id)
                    .where(and_(*conds))
                    .group_by(AssetItem.batch_id)
                    .order_by(func.max(AssetOutput.created_at).desc())
                    .limit(cap)
                )
            ).all()
        )
        batch_ids = [r[0] for r in rows if r[0] is not None]
        batch_meta: Dict[uuid.UUID, dict] = {}
        if batch_ids:
            for b in (
                await db.execute(
                    select(AssetBatch.id, AssetBatch.code, AssetBatch.name).where(AssetBatch.id.in_(batch_ids))
                )
            ).all():
                batch_meta[b[0]] = {"code": b[1], "name": b[2]}
        groups = [
            {
                "key": str(bid) if bid is not None else "none",
                "label": (
                    f"{batch_meta[bid]['code']} · {batch_meta[bid]['name'] or '未命名'}"
                    if bid is not None and bid in batch_meta
                    else "未挂批次"
                ),
                "sub": None,
                "count": int(cnt),
                "latest_at": utc_iso(latest) if latest else None,
                "_latest": latest,
            }
            for bid, cnt, latest in rows
        ]

    # 每组最新一条的首帧缩略图：按时间倒序扫一遍候选，每组取第一遇到的（400 条有界，
    # 超界的组没图只是少张缩略图，不报错）
    if groups:
        group_keys = {g["key"] for g in groups}
        latest_rows: Dict[str, AssetOutput] = {}
        if group_by == "asset":
            scan_rows = list(
                (
                    await db.execute(
                        select(AssetOutput)
                        .where(and_(*conds))
                        .order_by(AssetOutput.created_at.desc())
                        .limit(400)
                    )
                ).scalars()
            )
            for o in scan_rows:
                gkey = str(o.asset_id)
                if gkey in group_keys and gkey not in latest_rows:
                    latest_rows[gkey] = o
        else:
            # batch 模式的组键＝该输出所属素材的批次（未挂批次的素材归入 "none" 组）
            scan_rows = list(
                (
                    await db.execute(
                        select(AssetOutput, AssetItem.batch_id)
                        .join(AssetItem, AssetItem.id == AssetOutput.asset_id)
                        .where(and_(*conds))
                        .order_by(AssetOutput.created_at.desc())
                        .limit(400)
                    )
                ).all()
            )
            for o, bid in scan_rows:
                gkey = str(bid) if bid is not None else "none"
                if gkey in group_keys and gkey not in latest_rows:
                    latest_rows[gkey] = o
        thumb_urls: Dict[str, Optional[str]] = {}
        if latest_rows:
            frame_rows = (
                await db.execute(
                    select(AssetFrame).where(
                        AssetFrame.output_id.in_([o.id for o in latest_rows.values()]),
                        AssetFrame.kind == FRAME_OUTPUT_THUMB,
                    )
                )
            ).scalars().all()
            frames_by_output = {f.output_id: f for f in frame_rows}
            for gkey, o in latest_rows.items():
                f = frames_by_output.get(o.id)
                thumb_urls[gkey] = (
                    await get_presigned_url(
                        f.bucket or settings.MINIO_BUCKET_RAW,
                        f.file_key,
                        expires_seconds=_FRAME_URL_TTL_SECONDS,
                    )
                    if f
                    else None
                )
        for g in groups:
            g["thumb_url"] = thumb_urls.get(g["key"])
    else:
        for g in groups:
            g["thumb_url"] = None

    awaiting = await _outputs_awaiting(
        db, owner=owner, current_user=current_user, batch_id=batch_id
    )
    return {
        "group_by": group_by,
        "owner": owner or "all",
        "groups": groups,
        # 空态要说真话用的三个数（见 `_outputs_awaiting`）
        "awaiting": awaiting,
    }


@router.post("/assets/outputs/package")
async def package_outputs(
    ids: List[str] = Body(..., embed=True, description="要打包的产物 id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """成片交付包（P1·评审定稿⑧，impact 9）：勾选跨组汇总 → 服务端 zip 打包下载。

    - 验收 failed 的照旧在打包口拦（与单条下载同一道闸，assets.py 下载口同款）；
    - 包内附 manifest.json：钩子号、推荐标题、剧缩、验收结论、production_id、
      reviewed_by/created_by 归属——发布侧交接「下载即落位」，不必人肉改名贴标题；
    - 文件名按板侧命名＋序号，重名自动加 (2)。
    """
    import io
    import zipfile

    uids = [_as_uuid(i, "output_id") for i in ids]
    rows = (
        await db.execute(
            select(AssetOutput).where(
                AssetOutput.id.in_(uids), AssetOutput.kind.notin_(("package", "copy"))
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="没有可打包的产物")
    blocked = [o for o in rows if o.qc_status == "failed"]
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=f"{len(blocked)} 条验收不合格被拦（先看清为什么废）："
            + "、".join((b.file_name or b.id)[:24] for b in blocked[:5]),
        )

    # 归属与标题一次聚合
    prod_ids = {o.production_id for o in rows if o.production_id}
    asset_ids = {o.asset_id for o in rows}
    prod_meta: Dict[Any, dict] = {}
    if prod_ids:
        for pid, hc, titles, cb, rb in (
            await db.execute(
                select(
                    AssetProduction.id,
                    AssetProduction.hook_code,
                    AssetProduction.video_titles,
                    AssetProduction.created_by,
                    AssetSummary.reviewed_by,
                )
                .join(AssetSummary, AssetSummary.id == AssetProduction.summary_id)
                .where(AssetProduction.id.in_(prod_ids))
            )
        ).all():
            prod_meta[pid] = {
                "hook_code": hc,
                "titles": titles or [],
                "created_by": str(cb) if cb else None,
                "reviewed_by": str(rb) if rb else None,
            }
    asset_codes: Dict[Any, str] = {}
    if asset_ids:
        for aid, code in (
            await db.execute(select(AssetItem.id, AssetItem.code).where(AssetItem.id.in_(asset_ids)))
        ).all():
            asset_codes[aid] = code
    names = await _user_names(db, {m.get("created_by") for m in prod_meta.values() if m.get("created_by")})

    # 首帧（无帧缩略不打包，manifest 照记）
    frame_rows = (
        await db.execute(
            select(AssetFrame).where(
                AssetFrame.output_id.in_([o.id for o in rows]),
                AssetFrame.kind == FRAME_OUTPUT_THUMB,
            )
        )
    ).scalars().all()
    frames_by_output = {f.output_id: f for f in frame_rows}

    manifest_entries = []
    used_names: Dict[str, int] = {}
    import asyncio as _aio

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for o in rows:
            meta = prod_meta.get(o.production_id) or {}
            base = (o.file_name or f"{o.id}").rsplit(".", 1)[0][:80] or "clip"
            ext = (o.file_name or "clip.mp4").rsplit(".", 1)[-1] or "mp4"
            name = f"{base}.{ext}"
            n = used_names.get(name, 0)
            if n:
                name = f"{base}({n + 1}).{ext}"
            used_names[name] = n + 1
            url = await get_presigned_url(
                o.bucket or settings.MINIO_BUCKET_RAW, o.file_key, expires_seconds=600
            )
            async with httpx.AsyncClient(timeout=300) as cl:
                resp = await cl.get(url)
                resp.raise_for_status()
            zf.writestr(name, resp.content)
            fr = frames_by_output.get(o.id)
            manifest_entries.append(
                {
                    "file": name,
                    "asset_code": asset_codes.get(o.asset_id),
                    "hook_code": meta.get("hook_code"),
                    "recommended_title": (meta.get("titles") or [""])[0],
                    "qc_status": o.qc_status,
                    "duration": o.duration,
                    "resolution": o.resolution,
                    "produced_by": names.get(meta.get("created_by") or ""),
                    "reviewed_by": names.get(meta.get("reviewed_by") or ""),
                    "thumb_url": (
                        await get_presigned_url(
                            fr.bucket or settings.MINIO_BUCKET_RAW,
                            fr.file_key,
                            expires_seconds=_FRAME_URL_TTL_SECONDS,
                        )
                        if fr
                        else None
                    ),
                }
            )
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "exported_at": utc_iso(datetime.utcnow()),
                    "exported_by": current_user.username,
                    "items": manifest_entries,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    buf.seek(0)
    await _write_audit(
        db,
        action="asset.outputs_package",
        operator=current_user,
        target_type="asset_output",
        target_id=None,
        after={"count": len(rows), "ids": [str(o.id) for o in rows[:20]]},
    )
    await db.commit()
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="delivery-package.zip"'},
    )


@router.get("/assets/outputs/{output_id}/download")
async def download_output(
    output_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """产物下载：presigned（走外部 endpoint，浏览器可直连）。

    A2-4：交付动作留痕——presigned 是一次性外链，谁在什么时候拿过哪条产物，
    事后对账只能靠这里的 AuditLog + `downloaded_at`。审计/回写失败不挡下载本身
    （下载是既成事实，记不上总比记错好），所以放在拿到 url 之后、fail-soft。
    """
    oid = _as_uuid(output_id, "output_id")
    out = (
        await db.execute(select(AssetOutput).where(AssetOutput.id == oid))
    ).scalar_one_or_none()
    if out is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    # 产物所属素材必须存在（11-03 口径变更：不再按导入人过滤，交付口全量可达）
    await _get_asset_or_404(db, out.asset_id)
    # 不合格不得交付（设计方案 §8：不静默把 warn/failed 塞进包里）
    if out.qc_status == "failed":
        raise HTTPException(status_code=409, detail=f"该产物验收不合格：{out.qc_note or '见验收记录'}")
    if not out.file_key:
        raise HTTPException(status_code=404, detail="产物没有可下载文件")
    url = await get_presigned_url(
        out.bucket or settings.MINIO_BUCKET_SLICED,
        out.file_key,
        expires_seconds=3600,
        as_attachment=True,
        filename=out.file_name or f"{out.kind}.mp4",
    )
    if not url:
        raise HTTPException(status_code=502, detail="生成下载地址失败")

    now = datetime.utcnow()
    first_at = out.downloaded_at
    out.downloaded_at = now
    await _write_audit(
        db,
        action="asset.output.download",
        operator=current_user,
        target_type="asset_output",
        target_id=str(out.id),
        before={"downloaded_at": first_at.isoformat(timespec="seconds") if first_at else None},
        after={
            "downloaded_at": now.isoformat(timespec="seconds"),
            "first_download": first_at is None,
            "asset_id": str(out.asset_id),
            "production_id": str(out.production_id),
            "kind": out.kind,
            "file_name": out.file_name,
            "file_key": out.file_key,
            "qc_status": out.qc_status,
        },
    )
    await db.commit()
    return {
        "url": url,
        "file_name": out.file_name,
        "kind": out.kind,
        "qc_status": out.qc_status,
        "downloaded_at": utc_iso(now),
    }


@router.get("/assets/outputs/{output_id}/preview")
async def preview_output(
    output_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """产物**内联预览**地址（批 E）：抽屉里点开就能播，不落到存盘。

    与 `/download` 的三点区别都刻意的：

    1. presign **不带 `as_attachment`**——挂了 `response-content-disposition=attachment`
       的链接给 `<video>` 就是黑屏，这正是"接口 200 但播不了"的根因；
    2. **验收不合格的也让播**：`/download` 对 `qc_status=failed` 直接 409（别把废片投出去），
       但预览是"看一眼为什么废"，拦死等于让人盲判。这里把 `qc_status`/`qc_note` 一起回，
       前端在播放器上方标红，判的人自己看得见；
    3. **不写审计、不动 `downloaded_at`**：那个字段是"已交付"的凭据，看一眼不算交付。

    Range 由 MinIO 直接响应（presigned 签名不覆盖 Range），后端不做视频代理，
    所以拖进度条不占后端连接、也不受 `idle_in_transaction_session_timeout` 那套影响。
    """
    oid = _as_uuid(output_id, "output_id")
    out = (await db.execute(select(AssetOutput).where(AssetOutput.id == oid))).scalar_one_or_none()
    if out is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    await _get_asset_or_404(db, out.asset_id)
    if not out.file_key:
        raise HTTPException(status_code=404, detail="产物没有可预览的文件")
    url = await get_presigned_url(
        out.bucket or settings.MINIO_BUCKET_SLICED,
        out.file_key,
        expires_seconds=3600,
    )
    if not url:
        raise HTTPException(status_code=502, detail="生成预览地址失败（对象存储不可达）")
    return {
        "url": url,
        "file_name": out.file_name,
        "kind": out.kind,
        "size": out.file_size,
        "duration": out.duration,
        "resolution": out.resolution,
        "qc_status": out.qc_status,
        "qc_note": out.qc_note,
        "expires_in": 3600,
    }


# ──────────────────────────────────────────────
# 拼接（11-04 简化口径：两段视频按人选的顺序拼一条，不选点不剪切）
# ──────────────────────────────────────────────

class ConcatRequest(BaseModel):
    """`POST /assets/concat` 的入参。

    A 段固定是素材库里的一条素材（产物要挂在它名下、`stage_compose` 要写它），
    B 段由一线现场选：素材库里另一条 / 现网已切的切片产物 / 本地文件（前端先传成
    素材再当 B 段，服务端不留任何"临时未入库文件"——留了就没人能对账）。
    """

    asset_id: str = Field(..., description="A 段：素材库里的这条素材（asset_items.id）")
    second_source: str = Field(..., description=f"B 段来源：{' 或 '.join(compose.INPUT_SOURCES)}")
    second_id: str = Field(..., description="B 段 ID（asset_items.id 或 slice_outputs.id）")
    order: str = Field(compose.ORDER_ASSET_FIRST, description="顺序：asset_first＝本条在前 / second_first＝另一段在前")
    production_id: Optional[str] = Field(None, description="可选：挂回某条生产单（拼接不强制要有生产单）")
    title: Optional[str] = Field(None, max_length=120, description="可选：产物文件名前缀，默认用素材编号")


def _asset_concat_segment(asset: AssetItem) -> Dict[str, Any]:
    """素材行 → 拼接的一段（bucket/file_key/file_name/label）。

    手工口 `_resolve_concat_input` 和批 Q 的回收自动拼共用这一份写法：自动拼那侧已经
    把素材行读在手里了（一次批量读，避免逐支开事务查库），只要别再各写一遍 label 格式，
    否则审计里两次拼接写的同一条素材会长得不一样，对账时没人说得清是不是同一条。
    调用方负责先过"不是图片／桶里有文件"两道判断。
    """
    return {
        "bucket": asset.bucket or settings.MINIO_BUCKET_RAW,
        "file_key": asset.file_key,
        "file_name": asset.file_name or f"{asset.code}.mp4",
        "label": f"{asset.code}·{asset.title or asset.file_name or '未命名'}",
    }


async def _resolve_concat_input(
    db: AsyncSession,
    source: str,
    value: str,
    current_user: User,
    label: str,
) -> Dict[str, Any]:
    """把「哪一段」翻成 {bucket, file_key, file_name, label}，取不到就 4xx，绝不带着空往下走。"""
    if source == compose.SOURCE_ASSET:
        asset = await _get_asset_or_404(db, value)
        # 批 G：图片不能当拼接的一段（两段里哪一段是图都会让 ffmpeg 在解码时炸）。
        # 在这里挡 = A/B 两段同一个口径，不用调用方各写一遍。
        if asset.media_kind == MEDIA_IMAGE:
            raise HTTPException(
                status_code=400, detail=f"{label}：{_image_block_reason(asset, '拼接')}"
            )
        if not asset.file_key:
            raise HTTPException(
                status_code=400,
                detail=f"{label}（{asset.code}）还没有可拼的文件：链接素材要先取回原片"
                       f"（`POST /assets/resolve`），文件素材要确认上传成功",
            )
        return _asset_concat_segment(asset)
    if source == compose.SOURCE_SLICE:
        out = (
            await db.execute(
                select(SliceOutput).where(SliceOutput.id == _as_uuid(value, "second_id"))
            )
        ).scalar_one_or_none()
        if out is None or not out.file_key:
            raise HTTPException(status_code=404, detail=f"{label}：切片产物不存在或没有文件")
        # 切片产物不属于素材库那套「全量可见」口径（11-03 取消的是 asset_* 的行级过滤）。
        # 这里沿用 preview.py `_check_output_scope` 的同一条隔离链：output→task→episode→project，
        # 无权限按 404 处理（不泄露存在性），与主系统口径一致。
        task = (
            await db.execute(select(SliceTask).where(SliceTask.id == out.task_id))
        ).scalar_one_or_none()
        episode = None
        if task is not None:
            episode = (
                await db.execute(select(Episode).where(Episode.id == task.episode_id))
            ).scalar_one_or_none()
        if episode is not None:
            await check_project_access_by_episode(db, episode, current_user)
        return {
            "bucket": settings.MINIO_BUCKET_SLICED,
            "file_key": out.file_key,
            "file_name": out.file_name or "slice.mp4",
            "label": f"切片·{out.file_name or out.id}",
        }
    raise HTTPException(
        status_code=400,
        detail=f"second_source 只能是 {' 或 '.join(compose.INPUT_SOURCES)}",
    )


async def _concat_render(
    first: Dict[str, Any],
    second: Dict[str, Any],
    *,
    work_dir: str,
    safe_name: str,
    key_prefix_code: str,
) -> Dict[str, Any]:
    """两段（已排好顺序的）视频取回→探规格→ffmpeg 直拼→落桶，返回 `AssetOutput(**kwargs)` 的字段。

    手工口（`POST /assets/concat`）和批 Q 的回收自动拼**共用这一段**。两处各写一遍
    ffmpeg 接线迟早漂移，而漂移的表现形式是「手工拼出来能播、自动拼出来不能播」
    ——那种差别只有真投出去才知道，验收拦不住。所以转码配方只留一份。

    ⚠️ **一段数据库都不碰**（与 `_fetch_board_output` 同一条纪律）：两次下载＋一次转码
    ＋一次上传，快的十几秒、慢的按分钟算，趴着等会把现网 60s 的
    `idle_in_transaction_session_timeout` 撞穿（11-04 等模型时真撞过一次）。
    调用方在事务外跑完这一段，再开短事务写行。

    目标画幅＝**排在最前那一段**（`first`）：调用方换顺序就等于换画幅，这是 11-04
    定下的口径（不复用 `upload.py::_ffmpeg_concat`，它回退硬编码 1920×1080 横屏）。
    """
    started = time.monotonic()
    paths: List[str] = []
    for idx, seg in enumerate((first, second)):
        local = os.path.join(work_dir, f"in_{idx}.mp4")
        ok = await download_to_file(seg["bucket"], seg["file_key"], local)
        if not ok:
            raise HTTPException(
                status_code=502,
                detail=f"取回第{idx + 1}段失败（{seg['bucket']}/{seg['file_key'][:60]}），稍后重试",
            )
        paths.append(local)

    infos: List[Optional[Dict[str, Any]]] = [await compose.probe_media(p) for p in paths]
    target = infos[0]
    if target is None:
        raise HTTPException(status_code=400, detail="第1段探不出视频流，不是能拼的视频文件")
    if infos[1] is None:
        raise HTTPException(status_code=400, detail="第2段探不出视频流，不是能拼的视频文件")
    for idx, info in enumerate(infos):
        dur = info.get("duration")
        if dur and dur > compose.MAX_SEGMENT_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"第{idx + 1}段 {dur:.0f}s 超过单次拼接上限 "
                       f"{compose.MAX_SEGMENT_SECONDS:.0f}s（同步等 ffmpeg，别拿它当队列）",
            )

    out_path = os.path.join(work_dir, "out.mp4")
    err = await compose.concat_segments(paths, target, out_path)
    if err:
        raise HTTPException(status_code=502, detail=err)

    out_info = await compose.probe_media(out_path) or target
    size = os.path.getsize(out_path) if os.path.isfile(out_path) else None
    file_key = f"asset/composed/{key_prefix_code}/{uuid.uuid4().hex[:16]}_{safe_name}.mp4"
    uploaded = await upload_file_from_path(
        settings.MINIO_BUCKET_RAW, file_key, out_path, content_type="video/mp4"
    )
    if not uploaded:
        raise HTTPException(status_code=502, detail="拼接成功但产物上传失败，请重试（原片未动）")
    return {
        "output_kwargs": {
            "file_key": file_key,
            "bucket": settings.MINIO_BUCKET_RAW,
            "file_name": f"{safe_name}.mp4",
            "duration": out_info.get("duration"),
            "file_size": size,
            "resolution": f"{int(out_info['width'])}x{int(out_info['height'])}",
            "sha256": compose.sha256_of(out_path),
        },
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


@router.post("/assets/concat", status_code=201)
async def concat_two_videos(
    data: ConcatRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """**简单拼接**：两段视频按人选的顺序拼成一条，落一条 `asset_outputs(kind=composed)`。

    口径（11-04 用户改定，覆盖设计方案 §八 原先挂在切片引擎上的那套重方案）：
    不做智能选点、不做智能剪切、不调 `SliceTask.hook_video_keys` / `hook_mix_mode`。
    顺序可选就是用户要的全部控制粒度——「拼在前或者拼在后」。

    三条实现约束（都是踩过的人才写得出来的，别当过度设计删掉）：
    1. **目标规格＝排在最前那一段**（宽/高/帧率），后一段 scale+pad 进去。
       所以「选顺序」同时决定了画幅：把竖屏放前面就出竖屏。
       不复用 `api/upload.py::_ffmpeg_concat` 是因为它的重编码回退硬编码 1920×1080 横屏
       （upload.py:644），会把我们的 9:16 加黑边塞进横框——成功但构图坏。
    2. **一律 `filter_complex` 重编码，绝不流拷贝**（混规格流拷贝出坏片，切片引擎
       同结论 `slice-worker/engines/slice.py:4577-4580`）。
    3. **任一段没有音轨就补一条静音轨**，不静默丢音轨、也不让整条命令失败。

    成本：**0 元**——不调智令、不调模型，纯本机 ffmpeg，所以不进预算闸门、不写 cost_*。
    同步等：单段上限 `MAX_SEGMENT_SECONDS`（默认 600s）先挡一道；两条短片的拼接是秒级，
    真要把批量拼接排上去属 P1 队列化（与投产串行展开同一个坑，见 `_call_autoclip` 注释）。
    """
    started = time.monotonic()
    compose.resolve_input_order(data.order, "A", "B")  # 先验 order，非法值别等到下载完文件才报
    if data.second_source not in compose.INPUT_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"second_source 只能是 {' 或 '.join(compose.INPUT_SOURCES)}",
        )
    asset = await _get_asset_or_404(db, data.asset_id)
    compose.check_inputs_differ(str(asset.id), data.second_source, data.second_id)

    seg_a = await _resolve_concat_input(db, compose.SOURCE_ASSET, str(asset.id), current_user, "A 段")
    seg_b = await _resolve_concat_input(db, data.second_source, data.second_id, current_user, "B 段")
    first, second = (
        (seg_b, seg_a) if data.order == compose.ORDER_SECOND_FIRST else (seg_a, seg_b)
    )

    production = None
    if data.production_id:
        production = await db.get(AssetProduction, _as_uuid(data.production_id, "production_id"))
        if production is None:
            raise HTTPException(status_code=404, detail="生产单不存在")

    work_dir = tempfile.mkdtemp(prefix="asset_concat_")
    try:
        safe = "".join(c for c in (data.title or asset.code) if c not in '/\\:*?"<>|').strip()[:80] or asset.code
        # 取回两段 → 探规格 → ffmpeg 直拼 → 落桶，全在 `_concat_render`（与批 Q 自动拼同一份配方）
        rendered = await _concat_render(
            first, second, work_dir=work_dir, safe_name=safe, key_prefix_code=asset.code
        )
        out_row = AssetOutput(
            production_id=production.id if production is not None else None,
            asset_id=asset.id,
            kind=compose.KIND_COMPOSED,
            **rendered["output_kwargs"],
        )
        db.add(out_row)
        # 拼接是 AssetItem 五阶段里唯一还没有写入方的那一个（stage_compose）。
        # 拼成功就置 success，派生态自然从 composing 走到 ready（derive_status 第一命中）。
        before_stage = asset.stage_compose
        before_status = asset.status
        asset.stage_compose = STAGE_SUCCESS
        asset.status = svc.derive_status(
            {
                "import": asset.stage_import,
                "prompt": asset.stage_prompt,
                "summary": asset.stage_summary,
                "produce": asset.stage_produce,
                "compose": STAGE_SUCCESS,
            },
            bool(asset.has_approved_copy),
        )
        await _write_audit(
            db,
            action="asset.concat",
            operator=current_user,
            target_type="asset_output",
            target_id=None,
            before={
                "asset_id": str(asset.id),
                "stage_compose": before_stage,
                "status": before_status,
            },
            after={
                "first": first["label"],
                "second": second["label"],
                "order": data.order,
                "target_resolution": out_row.resolution,
                "duration": out_row.duration,
                "file_key": out_row.file_key,
                "cost": 0,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
        )
        await db.commit()
        await db.refresh(out_row)
        # 批 F：产物也补 1 张帧（豆包成片要等批 H 才有第二个 AssetOutput 写入方，
        # 今天这条是拼接产物唯一的补帧路径）。同样不许把已经拼完的活儿带崩。
        frames = await _enqueue_frames(
            db, asset_ids=[], output_ids=[str(out_row.id)], operator=current_user,
            why="拼接产物",
        )
        return {
            "id": str(out_row.id),
            "kind": out_row.kind,
            "asset_id": str(out_row.asset_id),
            "production_id": str(out_row.production_id) if out_row.production_id else None,
            "file_name": out_row.file_name,
            "file_key": out_row.file_key,
            "bucket": out_row.bucket,
            "duration": out_row.duration,
            "file_size": out_row.file_size,
            "resolution": out_row.resolution,
            "asset_status": asset.status,
            "order": data.order,
            "segments": [first["label"], second["label"]],
            "frames": frames,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "message": "拼好了，产物每条一行不覆盖，可反复拼不同顺序",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ──────────────────────────────────────────────
# 回源解析（D-5：11-03 拍板「解析费计入批次成本」）
# ──────────────────────────────────────────────

# provider 兜底链里的**免费**渠道：命中它们不花钱，cost_parse 就必须记 0——
# 给免费的一次记 0.01 等于在对账页上造一笔没发生的钱。其余（zhiling doc/107，
# 以及任何 WECHAT_DL_PROVIDERS 里配的自定义 HTTP 服务商）按 PRICE_PARSE_PER_CALL 计。
_FREE_PARSE_CHANNELS = ("yuanbao", "preview")


async def _recompute_batch_actual_cost(db: AsyncSession, batch_ids) -> None:
    """批次实扣 = Σ(该批每条的 cost_prompt + cost_parse)。

    重算而不是累加：同一批可能被反复点名，累加会越记越大；按行汇总则天然幂等，
    也自动把「解析失败不记账」的条目排除在外（它们的 cost_parse 还是 0）。

    批 G 加了 `media_kind != image`：图片的 cost_* 恒为 0（四个花钱环节都不走它），
    加这一条**不改数**，是把"图不计费"写成断言——将来谁要是给图片写了成本，
    这条过滤会让它不进批次账，而不是悄悄混进对账单。
    """
    for bid in {b for b in batch_ids if b}:
        charged = (
            await db.execute(
                select(func.coalesce(func.sum(AssetItem.cost_prompt + AssetItem.cost_parse), 0.0)).where(
                    AssetItem.batch_id == bid
                ).where(AssetItem.media_kind != MEDIA_IMAGE)
            )
        ).scalar_one()
        batch = await db.get(AssetBatch, bid)
        if batch is not None:
            batch.cost_actual = round(float(charged), 4)


def _cached_play_url(asset: AssetItem) -> tuple[Optional[str], float]:
    """时效直链缓存（11-06 播放直链修复）：返回 (缓存直链, 距取链小时数)。

    缓存只在 `ASSET_PLAY_URL_TTL_HOURS`（默认 6，与源站时效直链「约 6 小时有效」
    同口径）内算数；过期返回 (None, age)。取链时间缺失/直链为空＝没有缓存。
    """
    if not asset.play_url or asset.play_url_at is None:
        return None, 0.0
    age_h = (datetime.utcnow() - asset.play_url_at).total_seconds() / 3600.0
    if age_h > float(settings.ASSET_PLAY_URL_TTL_HOURS):
        return None, age_h
    return asset.play_url, age_h


@router.post("/assets/resolve")
async def resolve_link_assets(
    data: ResolveRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """链接素材**按需回源解析**：拿真实时长（顺带回一条时效直链），解析费计入批次成本。

    为什么必须是人点的（而不是反推时顺手做）：一条 0.01 元看着不多，但 200 条分享链接
    就是 2 元**没人签字**的支出，而绝大多数素材根本不按时长筛。所以口径是——
    前端先调 `/assets/cost/estimate?need_parse=true` 拿预估，≥2 条要带 `confirmed=true`，
    闸门（余额 blocked / 超预算 need_approval）与反推同一套，blocked **没有 force 后门**。

    三条「不重复花钱」的硬规矩（11-06 播放直链修复后，跳过分两种）：
    - 已有 `duration` 的**不进 todo**：缓存直链还在 TTL 内 → 免费**回放**（channel=cache，
      0 元、不调解析接口，results 里带 play_url）；缓存过期 → 跳过并提示带 `retake=true`
      重取（唯一自愈出口：强制重解析、按渠道记账 0.01 元/次）；
    - 整批排队只取 `duration IS NULL 且 cost_parse=0` 的：解析过但源站不给时长的**不再自动重排**，
      免得同一条被反复扣 0.01；确实要再试就点名 asset_ids；
    - 直链素材走 ffprobe 本地探测，**不发**解析接口（0 元）。

    解析成功后把直链 + 取链时间**落库**（`play_url`/`play_url_at`），source-preview 与
    下一次 resolve 靠它免费回放——「取了直链再进来直链就没了」的根因就是以前只回响应不落库。

    记账口径：**发出去就记**，与拿不拿得到时长无关——付费渠道收了钱不会因为我们不读
    duration 就退钱。逐条 fail-soft，一条失败不连坐整批，失败的不记账。
    """
    cap = _analyze_max_per_call()
    queue_batch_id, per_call, asset_ids = _queue_or_ids(data, cap, what="回源解析")

    queue: Optional[dict] = None
    if queue_batch_id:
        conds = [
            AssetItem.batch_id == _as_uuid(queue_batch_id, "batch_id"),
            AssetItem.source_kind == SOURCE_LINK,
            AssetItem.duration.is_(None),
            AssetItem.cost_parse == 0,
            AssetItem.stage_import.in_([STAGE_SUCCESS, STAGE_SKIPPED]),
        ]
        total = (
            await db.execute(select(func.count()).select_from(AssetItem).where(and_(*conds)))
        ).scalar_one()
        assets = list(
            (
                await db.execute(
                    select(AssetItem)
                    .where(and_(*conds))
                    .order_by(AssetItem.created_at, AssetItem.code)
                    .offset(int(data.offset or 0))
                    .limit(per_call)
                )
            ).scalars().all()
        )
        remaining = max(0, int(total) - int(data.offset or 0) - len(assets))
        queue = {
            "batch_id": queue_batch_id,
            "offset": int(data.offset or 0),
            "limit": per_call,
            "picked": len(assets),
            "remaining": remaining,
            "hint": "付过一次费的（含没探出时长的）会自己离开队列；同一条要再试请点名 asset_ids",
        }
    else:
        assets = [await _get_asset_or_404(db, aid) for aid in asset_ids]

    todo: List[AssetItem] = []
    skipped: List[dict] = []
    # 11-06 播放直链修复：已解析过的素材如果缓存直链还在时效内，免费回放（0 元、
    # 不调解析接口）。之前 play_url 只活在当次响应里，用户付了钱取的直链一关抽屉
    # 就没了，再点按钮还会撞上「已有时长不重复付费」的 skip——链接既拿不回来、
    # 也不会再扣钱，死锁在播不了。
    cached_entries: List[dict] = []
    for a in assets:
        if a.media_kind == MEDIA_IMAGE:
            # 批 G：图片没有"时长"这回事，回源解析对它既无意义又收费（0.01 元/条）
            skipped.append({
                "code": a.code,
                "reason": "图片不用回源解析（静态图没有时长），它是投产用的角色卡",
            })
            continue
        if a.source_kind != SOURCE_LINK:
            skipped.append({"code": a.code, "reason": "文件素材的时长在上传时就由 ffprobe 回写，不需要回源"})
            continue
        if a.duration and not data.retake:
            cached, age_h = _cached_play_url(a)
            if cached:
                ttl = settings.ASSET_PLAY_URL_TTL_HOURS
                age_txt = f"{age_h:.1f}" if age_h >= 0.1 else "刚刚"
                cached_entries.append({
                    "asset_id": str(a.id), "code": a.code, "duration": a.duration,
                    "charged": 0.0, "channel": "cache", "ok": True,
                    "play_url": cached,
                    "note": f"回放 {age_txt} 小时前取的直链（{ttl:g} 小时内免费），没调解析接口；打不开就点重取",
                })
                continue
            skipped.append({
                "code": a.code,
                "reason": (
                    f"已有时长 {a.duration}s，不重复付费解析；上次取的直链已过期"
                    f"（超过 {settings.ASSET_PLAY_URL_TTL_HOURS:g} 小时），要重取带 retake=true"
                    "（重新解析，0.01 元/次）"
                ),
            })
            continue
        todo.append(a)

    if not todo:
        # 没活可干不是错误：点名的那条已有时长/整批都付过一次费，返回 200 + skipped 让前端
        # 把「为什么没花钱」逐条讲出来。走 400 的话，排队轮询到队尾会被当成接口故障。
        # 唯一保留的入参错误是 `_queue_or_ids` 里的「二选一/都为空」，那是调用方写错了。
        # 11-06：缓存直链回放不是「没活」——results 里要带回 play_url，前端靠它免重取播放。
        if cached_entries:
            return {
                "results": cached_entries,
                "skipped": skipped,
                "resolved": len(cached_entries),
                "charged": 0.0,
                "channels": {},
                "queue": queue,
                "estimate": None,
                "message": (
                    f"{len(cached_entries)} 条直接回放缓存直链（0 元，未发起外呼）"
                    + (f"；{len(skipped)} 条被跳过" if skipped else "")
                ),
            }
        return {
            "results": [],
            "skipped": skipped,
            "resolved": 0,
            "charged": 0.0,
            "channels": {},
            "queue": queue,
            "estimate": None,
            "message": (
                "没有一条需要回源，未发起任何外呼、未产生费用"
                + (
                    f"；本段取 {queue['picked']} 条全被跳过，队列剩余 {queue['remaining']} 条"
                    if queue else f"；{len(skipped)} 条被跳过"
                )
            ),
        }

    # 11-06 拍板②：解析费虽小（0.01/条）但是真实支出，替别人批次花之前先确认，确认后留痕
    crosses = await _cross_person_gate(
        db,
        operator=current_user,
        batch_ids=[a.batch_id for a in todo],
        action_label="回源解析",
        confirmed=data.cross_person_confirm,
    )

    # max_duration=0：只算解析这一条腿，别把反推的档位钱混进来（反推有它自己的确认单）
    estimate = svc.estimate_batch_cost(len(todo), max_duration=0, need_parse=True)
    balance_detail = await _query_zhiling_balance_detail()
    balance = balance_detail["balance"]
    # 不做批次累计口径：单请求封顶 20 条 = 0.2 元，够不到 50 元的单批预算闸门；
    # 真正能把批次吃到 50 元的是反推，那道闸门留在那里。
    gate = svc.budget_gate(
        estimate["total_cost"],
        balance,
        batch_cap=settings.ASSET_BATCH_BUDGET_CAP,
        safety_ratio=settings.ASSET_BALANCE_SAFETY_RATIO,
    )
    if balance_detail["note"]:
        gate["note"] = (
            f"{gate['note']}；{balance_detail['note']}" if gate.get("note") else balance_detail["note"]
        )

    if len(todo) >= 2 and not data.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ASSET_COST_CONFIRM_REQUIRED",
                "message": f"本批 {len(todo)} 条回源解析预估 {estimate['total_cost']} 元，须确认后提交",
                "estimate": estimate,
                "balance": balance,
                "balance_note": balance_detail["note"],
                "gate": gate,
                "queue": queue,
                "hint": "确认单点「确认」后带 confirmed=true 重发（解析按次收费，失败不退）",
            },
        )

    if not gate["allowed"]:
        if gate["level"] == "need_approval":
            is_admin = current_user.role == UserRole.admin.value
            if not (data.confirmed and is_admin):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "ASSET_BUDGET_NEED_APPROVAL",
                        "message": gate["reason"],
                        "estimate": estimate,
                        "balance": balance,
                        "hint": "本批解析费超单批预算：分段提交，或由管理员确认后带 confirmed=true 重发",
                    },
                )
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ASSET_BALANCE_BLOCKED",
                    "message": gate["reason"],
                    "estimate": estimate,
                    "balance": balance,
                    "hint": "余额不足先充值；回源解析没有 force 后门（0.01 元/次也要人签字）",
                },
            )

    results: List[dict] = list(cached_entries)
    touched_batches: List[Any] = []
    charged_total = 0.0
    channels: Dict[str, int] = {}
    for a in todo:
        entry: Dict[str, Any] = {
            "asset_id": str(a.id), "code": a.code, "duration": a.duration,
            "charged": 0.0, "channel": None, "ok": False,
        }
        if svc.looks_like_direct_url(a.source_url or ""):
            probed = await _probe_url_duration(a.source_url)
            if probed:
                a.duration = probed
                entry.update(ok=True, duration=a.duration, channel="ffprobe",
                             note="直链本地探测，未调解析接口，0 元")
            else:
                entry["error"] = "直链 ffprobe 没探出时长（源站不给或链路不通），未花钱"
            results.append(entry)
            continue

        try:
            parsed = await dispatch_parse(a.source_url)
        except ProviderParseError as exc:
            entry["error"] = f"解析失败：{str(exc)[:200]}（失败不记账）"
            results.append(entry)
            continue
        except Exception as exc:  # 网络/超时等，同样不记账但要说清是哪一条
            logger.exception("回源解析异常 %s", a.code)
            entry["error"] = f"解析异常：{str(exc)[:200]}（失败不记账）"
            results.append(entry)
            continue

        channel = str(getattr(parsed, "channel", None) or "unknown")
        entry["channel"] = channel
        channels[channel] = channels.get(channel, 0) + 1
        if channel not in _FREE_PARSE_CHANNELS:
            fee = round(float(svc.PRICE_PARSE_PER_CALL), 4)
            a.cost_parse = round(float(a.cost_parse or 0.0) + fee, 4)
            charged_total = round(charged_total + fee, 4)
            touched_batches.append(a.batch_id)
            entry["charged"] = fee

        seconds = None
        raw_duration = getattr(parsed, "duration", None)
        if isinstance(raw_duration, (int, float)) and raw_duration > 0:
            seconds = float(raw_duration)
        play_url = getattr(parsed, "play_url", None)
        if not seconds and play_url:
            # 解析接口常常只回直链不回时长（各平台字段不一），补一次 ffprobe；
            # 这条只在已经为这次解析付过钱之后发生，不再额外花钱
            seconds = await _probe_url_duration(play_url)
        if seconds:
            a.duration = round(float(seconds), 2)
            entry.update(ok=True, duration=a.duration, play_url=play_url)
        else:
            entry.update(ok=True, play_url=play_url,
                         note="解析成功但源站没给时长；已按渠道记账，时长仍为空（前端显示「未知」）")
        # 11-06 播放直链修复：直链落库（+取链时间）。哪怕源站没给时长，直链也能播，
        # 缓存期内免费回放；过由 _cached_play_url 的 TTL 判，不在这里猜。
        if play_url:
            a.play_url = play_url
            a.play_url_at = datetime.utcnow()
        title = getattr(parsed, "title", None)
        if title:
            entry["title"] = title[:200]
        results.append(entry)

    resolved = sum(1 for r in results if r.get("duration"))
    await _recompute_batch_actual_cost(db, touched_batches)
    await _write_audit(
        db,
        action="asset.resolve",
        operator=current_user,
        target_type="asset_batch" if queue_batch_id else "asset_item",
        target_id=queue_batch_id,
        after={
            "requested": len(todo),
            "resolved": resolved,
            "charged": charged_total,
            "channels": channels,
            "skipped": [s["code"] for s in skipped],
            "cache_hits": [c["code"] for c in cached_entries],
            "retake": bool(data.retake),
            "estimate": estimate["total_cost"],
            "balance": balance,
            "queue": queue,
            "cross_person": crosses or None,
        },
    )
    await db.commit()
    return {
        "results": results,
        "resolved": resolved,
        "charged": charged_total,
        "skipped": skipped,
        "channels": channels,
        "estimate": estimate,
        "balance": balance,
        "balance_note": balance_detail["note"],
        "gate": gate,
        "queue": queue,
        "message": (
            f"{len(todo)} 条回源解析：拿到时长 {resolved} 条，实扣 {charged_total} 元"
            + (f"；跳过 {len(skipped)} 条" if skipped else "")
            + (f"；队列还剩 {queue['remaining']} 条" if queue and queue["remaining"] else "")
        ),
    }


# ──────────────────────────────────────────────
# 下载原片 / 提示词预览（批 J，11-05：都是"跟着主动作顺手排"的后台任务）
# ──────────────────────────────────────────────

# 下载动作自己的状态字（models 侧不设常量：三取值只在这一个口里写，别处只读）
_DL_RUNNING, _DL_SUCCESS, _DL_FAILED = "running", "success", "failed"

# 视频容器魔数（闸门第一层）。只认「开头就摆明自己是视频」的几种，认不出交给 ffprobe 兜底。
_VIDEO_BOX_KEYS = (b"ftyp", b"styp", b"free", b"mdat", b"skip")  # ISO BMFF 族：4~8 字节是 box 类型


def _sniff_video_container(head: bytes) -> Optional[str]:
    """文件头若干字节 → 容器名；认不出回 None（不代表不是视频，交给 ffprobe 实探）。"""
    if len(head) >= 12 and head[4:8] in _VIDEO_BOX_KEYS:
        return "mp4/mov"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "mkv/webm"
    if head[:4] in (b"\x00\x00\x01\xb3", b"\x00\x00\x01\xba"):
        return "mpeg"
    if len(head) >= 189 and head[0] == 0x47 and head[188] == 0x47:
        return "mpeg-ts"  # TS 包长 188：第一包同步字节后面，第二包开头还得是 0x47（不足 189 字节别硬认，交给 ffprobe）
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head[:3] == b"FLV":
        return "flv"
    return None


def _describe_not_video(head: bytes) -> str:
    """闸门挡下时给一线看的白话原因：说清拉回来的**到底是**什么，别只说"不是视频"。"""
    text = head.decode("utf-8", "ignore").lstrip("﻿ \r\n\t")
    low = text[:2048].lower()
    if low.startswith("<!doctype html") or low.startswith("<html") or "<head" in low[:600]:
        title = re.search(r"<title[^>]*>(.*?)</title>", text[:4096], re.S | re.I)
        name = (title.group(1).strip()[:40] if title else "")
        return ("一个网页（源站/解析方给的中转引导页，不是视频流）"
                + (f"，页面标题「{name}」" if name else ""))
    sample = text[:200]
    if sample and sample.isascii() and all(c.isprintable() or c in " \t\r\n" for c in sample):
        # isprintable() 把换行算作"不可打印"，而 m3u8 / JSON 报错体都是带换行的纯文本
        return f"一段纯文本（开头是「{text[:60].strip()}」），不是视频流"
    return "认不出的字节（既不是已知视频容器，也不是文本）"


async def _video_content_gate(path: str) -> Tuple[Optional[str], Optional[float]]:
    """下载内容闸门：`返回 (挡下的原因, 顺手探到的时长)`。

    为什么必须有这道闸（2026-11-09 现网事故 `AS-BB8563FD`）：旧代码只挡 0 字节、异常和
    落桶失败，智令对一条视频号链接回的是一个 10.8KB 的 HTML 中转页——**多大都算过**，
    于是网页带着 `video/mp4` 的 content-type 进了自有桶、`download_status=success`、
    `stage_import=success`、照记 0.01 元解析费、还排了抽帧（必然 0 帧）。列表和抽屉里
    看着"下载成功"，实际点开是坏的。

    两层判据：① 容器魔数——认得出 mp4/mkv/ts/avi/flv 就直接放行，不额外花 ffprobe；
    ② 魔数认不出再实探一次时长（探得出就放行并把时长带回，别把没见过的合法容器挡死；
    探不出才判"不是视频"）。挡下的东西**不入桶、不标成功**，原因写成一线能照着换路子的大白话。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError as exc:  # pragma: no cover - 拉流声称成功但文件没落盘
        return f"下载器报了字节数但临时文件读不到（{type(exc).__name__}）", None
    if _sniff_video_container(head):
        return None, None
    probed = await _probe_duration(path)
    if probed:
        return None, probed
    return _describe_not_video(head), None


@router.post("/assets/download")
async def download_asset_sources(
    data: AssetDownloadRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """把链接素材的**原片**拉回自有桶（批 J，用户口径：反推默认顺带下载）。

    为什么跟着反推走：反推本来就要解析这条分享链接（智令 doc/120 在远端拉），
    下载只是把"解析出来的直链"顺手落到我们桶里——回看、拼接、交付都不用再
    蹲一条几小时就过期的时效直链。

    四件套（与采集侧 `run_download_pipeline` 同源但**刻意不整段复用**——那份会建
    Project/Episode，把素材库的行挂到「视频号导入」项目里，两条链就搅在一起了）：
    `dispatch_parse`（解析分享链接→直链）→ `get_downloader().download_to_file`
    （拉流，支持断点续传）→ `upload_file_from_path`（落自有桶）→ `_probe_duration`
    （ffprobe 探真实时长）。解析落到付费渠道按 0.01 元/条记 `cost_parse`
    （与 `/assets/resolve` 同一口径）；拉流、落桶、探时长都是 0 元。

    幂等：`file_key` 已非空的原样跳过（不重复下载、不重复占桶）；每条
    running→终态**逐条落库**（同 analyze 口径：一条几分钟，中途崩不能整批白跑）。
    `download_status` 是下载自己的状态，不进五阶段、不影响任何闸门。

    11-09 补第五步＝**内容闸门**（`_video_content_gate`）：字节数不为 0 不代表拿到的是视频，
    验完容器才入桶标 success；挡下的条标 failed 带白话原因、不抽帧（详见该函数注释的事故记录）。
    """
    if not data.asset_ids:
        raise HTTPException(
            status_code=400,
            detail="请点名要下载原片的素材（反推时勾了「顺带下载原片」会自动排，不用手工调）",
        )
    assets = [await _get_asset_or_404(db, aid) for aid in data.asset_ids]

    todo: List[AssetItem] = []
    skipped: List[dict] = []
    for a in assets:
        if a.media_kind == MEDIA_IMAGE:
            skipped.append({"code": a.code, "reason": "图片素材本来就在自有桶里，不用下载"})
            continue
        if a.source_kind == SOURCE_FILE:
            skipped.append({"code": a.code, "reason": "文件素材上传时已经落在自有桶里，不需要下载"})
            continue
        if a.file_key:
            skipped.append({"code": a.code, "reason": "原片已经在自有桶里（之前下载过），不重复下载"})
            continue
        if not a.source_url:
            skipped.append({"code": a.code, "reason": "这条既没有原片也没有来源链接，无从下载"})
            continue
        todo.append(a)

    if not todo:
        # 与 resolve 同口径：没活可干不是错误（排队轮询到队尾不能被当接口故障）
        return {
            "results": [],
            "skipped": skipped,
            "downloaded": 0,
            "charged": 0.0,
            "channels": {},
            "message": "没有一条需要下载（原片都已在自有桶里），未发起任何外呼"
            + (f"；{len(skipped)} 条被跳过" if skipped else ""),
        }

    # 11-06 拍板②：下载会按解析渠道计 0.01/条，替别人批次跑之前先确认，确认后留痕
    crosses = await _cross_person_gate(
        db,
        operator=current_user,
        batch_ids=[a.batch_id for a in todo],
        action_label="下载原片",
        confirmed=data.cross_person_confirm,
    )

    results: List[dict] = []
    tmp_dir = os.path.join(tempfile.gettempdir(), f"asset_download_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)
    # 逐条 commit（同 analyze_batch 的坑）：commit 后还要读 asset 的列，必须关掉过期刷新
    db.sync_session.expire_on_commit = False
    touched_batches: List[Any] = []
    charged_total = 0.0
    channels: Dict[str, int] = {}

    for a in todo:
        entry: Dict[str, Any] = {
            "asset_id": str(a.id), "code": a.code,
            "ok": False, "charged": 0.0, "channel": None, "error": None,
        }
        results.append(entry)
        a.download_status = _DL_RUNNING
        try:
            await db.commit()  # running 态先落库：中途崩列表上也看得到"正在下载"
        except Exception as e:  # pragma: no cover
            await db.rollback()
            logger.warning("download_status=running 落库失败 %s: %s", a.code, e)

        # ① 解析分享链接 → 直链（付费渠道要记账，失败不记账，与 resolve 同口径）
        try:
            parsed = await dispatch_parse(a.source_url)
        except ProviderParseError as exc:
            logger.warning("下载原片解析失败 %s channel未知: %s", a.code, str(exc)[:200])
            a.download_status = _DL_FAILED
            entry["error"] = f"解析分享链接失败：{str(exc)[:200]}（失败不记账）"
            await db.commit()
            continue
        except Exception as exc:
            logger.exception("下载原片解析异常 %s", a.code)
            a.download_status = _DL_FAILED
            entry["error"] = f"解析异常：{str(exc)[:200]}（失败不记账）"
            await db.commit()
            continue

        channel = str(getattr(parsed, "channel", None) or "unknown")
        entry["channel"] = channel
        channels[channel] = channels.get(channel, 0) + 1
        if channel not in _FREE_PARSE_CHANNELS:
            fee = round(float(svc.PRICE_PARSE_PER_CALL), 4)
            a.cost_parse = round(float(a.cost_parse or 0.0) + fee, 4)
            charged_total = round(charged_total + fee, 4)
            touched_batches.append(a.batch_id)
            entry["charged"] = fee

        play_url = getattr(parsed, "play_url", None)
        if not play_url:
            logger.warning("下载原片失败 %s：解析成功但 play_url 为空（channel=%s）", a.code, channel)
            a.download_status = _DL_FAILED
            entry["error"] = "解析成功但没拿到可下载的直链（源站没给播放地址）"
            await db.commit()
            continue

        # ② 拉流下载（断点续传在 downloader 里；HLS/直链都归它）
        local_path = os.path.join(tmp_dir, f"{a.code}.mp4")
        try:
            total = await get_downloader().download_to_file(play_url, local_path)
        except Exception as exc:
            logger.warning("下载原片拉流失败 %s（channel=%s, play_url=%s…）: %s",
                           a.code, channel, str(play_url)[:80], str(exc)[:200])
            a.download_status = _DL_FAILED
            entry["error"] = f"拉流下载失败：{str(exc)[:200]}（解析费已按渠道记账）"
            await db.commit()
            continue
        if not total:
            logger.warning("下载原片失败 %s：0 字节（channel=%s）", a.code, channel)
            a.download_status = _DL_FAILED
            entry["error"] = "下载到 0 字节（直链秒回空响应），没入桶，不假装成功"
            await db.commit()
            continue

        # ②' 内容闸门（11-09 事故补的）：字节数不为 0 ≠ 拿到的是视频，先验容器再入桶
        gate_reason, gated_duration = await _video_content_gate(local_path)
        if gate_reason:
            logger.warning("下载原片被内容闸门挡下 %s（channel=%s, size=%s）：%s",
                           a.code, channel, total, gate_reason)
            a.download_status = _DL_FAILED
            entry["error"] = (f"拉回来的不是视频：{gate_reason}。没入桶、不标成功，"
                              f"这条请换渠道/换链接重试或走人工下载（解析费已按渠道记账）")
            await db.commit()
            continue

        # ③ 落自有桶：key 风格与抽帧/拼接一致（asset/<用途>/<素材号>/…），按素材号聚得拢
        object_key = f"asset/source/{a.code}/{uuid.uuid4().hex[:16]}.mp4"
        ok = await upload_file_from_path(
            settings.MINIO_BUCKET_RAW, object_key, local_path, "video/mp4"
        )
        if not ok:
            logger.warning("下载原片失败 %s：落桶失败 key=%s（桶不可达或写入被拒）", a.code, object_key)
            a.download_status = _DL_FAILED
            entry["error"] = "对象存储入库失败（桶不可达或写入被拒）"
            await db.commit()
            continue

        # ④ 回写 + 探真实时长（已有时长的不覆盖——那是 resolve/上传时探过的口径）
        a.file_key = object_key
        a.bucket = settings.MINIO_BUCKET_RAW
        a.file_size = total
        a.file_name = a.file_name or f"{a.code}.mp4"
        if not a.duration:
            a.duration = gated_duration or await _probe_duration(local_path)
        a.download_status = _DL_SUCCESS
        entry.update(ok=True, file_key=object_key, size=total,
                     note="原片已落到自有桶，列表/抽屉里可直接预览和下载")
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.exception("下载结果落库失败 %s", a.code)
            # 桶里已经有文件了：状态先如实回 failed，重试会因 file_key 未落而再下一次（白占一份）
            a.download_status = _DL_FAILED
            entry["error"] = f"下载成功但状态未落库，重试会重复占桶：{str(e)[:200]}"

    shutil.rmtree(tmp_dir, ignore_errors=True)

    downloaded = sum(1 for r in results if r["ok"])
    await _recompute_batch_actual_cost(db, touched_batches)
    await _write_audit(
        db,
        action="asset.download",
        operator=current_user,
        target_type="asset_batch" if len(todo) > 1 else "asset_item",
        target_id=None,
        after={
            "requested": len(todo),
            "downloaded": downloaded,
            "charged": charged_total,
            "channels": channels,
            "skipped": [s["code"] for s in skipped],
            "results": [
                {k: r.get(k) for k in ("asset_id", "code", "ok", "charged", "error") if k in r}
                for r in results
            ],
            "cross_person": crosses or None,
        },
    )
    await db.commit()

    # 11-05 易操作性评估 P0-1：链接素材下载成功后**原片已在自有桶里**，却从来没人排抽帧
    # （上传 1881 行、拼接 7199 行都排，唯独下载这条漏了）——现网 asset_frames 0 行实锤，
    # 审核台卡片永远「没有预览图」，审核员全程只能凭文字审。这里搭车补排；
    # 排失败只回 note 不连累下载结果（与 _enqueue_frames 的既有口径一致）。
    downloaded_ids = [r["asset_id"] for r in results if r.get("ok")]
    frames: Optional[Dict[str, Any]] = None
    if downloaded_ids:
        frames = await _enqueue_frames(
            db, asset_ids=downloaded_ids, output_ids=[],
            operator=current_user, why="原片下载完成",
        )
    return {
        "results": results,
        "skipped": skipped,
        "downloaded": downloaded,
        "charged": charged_total,
        "channels": channels,
        "frames": frames,
        "message": (
            f"原片下载：成功 {downloaded} 条 / 共 {len(todo)} 条"
            + (f"，解析实扣 {charged_total} 元" if charged_total else "，未产生解析费")
            + (f"；跳过 {len(skipped)} 条已在桶里" if skipped else "")
            + (
                "；抽帧已排后台，几分钟内审核卡片就有图"
                if frames and frames.get("queued")
                else (f"；{frames.get('note')}" if frames and frames.get("note") else "")
            )
        ),
    }


@router.post("/assets/summaries/preview-prompt")
async def preview_prompt_for_summaries(
    data: PromptPreviewRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """过审文案 → 豆包生产提示词**预览**（批 J，用户口径：过审后提示词就备好、有处可看）。

    与投产展开（`/produce` 里的 `expand`）**同一个模型、同一份模板**，但参数取最保守的
    一档（无钩子编号、剧名缩写空、按无角色卡）——所以预览回答的是「这条文案能不能展开成
    像样的提示词」，**不是投产那一份**；投产时仍按当时的编号/卡/剧名重新展开，一字不抄这里。

    幂等：已有预览的原样复用（未重新生成、未重复等模型）；「改后过」和撤销过审会把旧预览
    作废（审核口负责置空），重新过审时这里自然重新生成。
    失败不连坐：单条展开失败只记原因，**不拦投产**（投产时反正要重新展开并过漂移判）。
    """
    if not data.summary_ids:
        raise HTTPException(
            status_code=400,
            detail="请点名要备提示词的文案（过审时会自动排上，一般不用手工调）",
        )
    results: List[dict] = []
    db.sync_session.expire_on_commit = False
    for sid in data.summary_ids:
        uuid_s = _as_uuid(sid, "summary_id")
        summary = (
            await db.execute(select(AssetSummary).where(AssetSummary.id == uuid_s))
        ).scalar_one_or_none()
        entry: Dict[str, Any] = {"summary_id": str(uuid_s), "ok": False, "reused": False, "error": None}
        results.append(entry)
        if summary is None:
            entry["error"] = "文案不存在"
            continue
        asset = await _get_asset_or_404(db, summary.asset_id)
        entry["code"] = asset.code
        if summary.audit_status not in REVIEW_PASSED_STATES:
            entry["error"] = f"这条还没过审（当前 {summary.audit_status}），不过审不备提示词"
            continue
        if (summary.prompt_preview or "").strip():
            entry.update(ok=True, reused=True, note="预览已存在，未重新生成、未重复等模型")
            continue

        drama_title = await _drama_title_of(db, asset)
        # ⚠️ 调模型前必须**结束事务**（与出文案口同一坑，11-05 现网真链路实锤）：
        # 一次展开要趴 1~5 分钟等 autoclip，开着事务等会让 PG 的
        # idle_in_transaction_session_timeout=60s 把连接掐掉——模型明明成功返回
        # 了 1449 字提示词，回写却报 connection is closed → 整个任务白跑。
        # 此刻事务里只有读取没有待写状态，commit 正好把读事务收掉；
        # 对象靠上面 expire_on_commit=False 保活，回写时自动开新事务。
        await db.commit()
        try:
            expanded = await _call_autoclip(
                "hook-copy/expand",
                {
                    "hook_copy": summary.text,
                    # 预览只展开一份：没有 N 的差异化，variant_basis 照实写"预览"
                    "seq": 1,
                    "total": 1,
                    "variant_basis": "preview",
                    # 与出文案同口径：内部只试一次，重试交给再点一次（见 _call_autoclip 说明）
                    "max_retries": 1,
                    "params": {
                        "asset_code": asset.code,
                        "platform": asset.platform or "",
                        "drama_title": drama_title,
                        # 预览取最保守参数：编号/缩写/卡都按"还不知道"处理，
                        # 投产时才知道的东西不掺进来，免得预览抄走投产的答案
                        "drama_abbr": "",
                        "duration": int(round(settings.ASSET_BOARD_OUTPUT_SECONDS)),
                        "recommended_title_count": 5,
                        "hook_code": None,
                        "has_character_card": False,
                        "compliance": "不得出现真实人名、地名、机构名、品牌名，一律使用代称。",
                    },
                },
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            entry["error"] = f"提示词没生成出来：{detail[:200]}（投产时会重新展开，不拦投产）"
            await db.commit()
            continue

        prompt_text = (expanded.get("prompt_text") or "").strip() or None
        if not prompt_text:
            entry["error"] = "模型没回提示词正文（投产时会重新展开，不拦投产）"
            await db.commit()
            continue

        kept = bool(expanded.get("hook_copy_kept_verbatim"))
        deviation = (expanded.get("deviation_note") or "").strip()
        summary.prompt_preview = prompt_text
        summary.prompt_preview_at = datetime.utcnow()
        summary.cost_preview = 0.0
        entry.update(
            ok=True,
            kept_verbatim=kept,
            note=(
                # 「预览≠投产」必须摆在明面上，否则有人会拿预览当投产结果去投板
                "预览（非投产稿）：投产时会按钩子编号/角色卡/剧名重新展开"
                + ("" if kept else "；模型自报没能原样保住文案，投产时会按漂移判拦截重试")
                + (f"；模型自报偏差：{deviation[:150]}" if deviation else "")
            ),
        )
        await _write_audit(
            db,
            action="asset.prompt_preview",
            operator=current_user,
            target_type="asset_summary",
            target_id=summary.id,
            after={
                "code": asset.code,
                "kept_verbatim": kept,
                "chars": len(prompt_text),
                "deviation": deviation[:300] or None,
            },
        )
        # 逐条落库（同 analyze 口径：一次展开 90~150s，中途崩不能整批白跑）
        # 兜底：commit 撞连接死亡时先 rollback 换新事务重写一次——对象在内存里
        # （expire_on_commit=False），重试只是重放 UPDATE，别让模型白跑一趟。
        try:
            await db.commit()
        except Exception as e:
            logger.warning("提示词预览落库第一次提交失败（%s），换新事务重试", str(e)[:120])
            await db.rollback()
            summary.prompt_preview = prompt_text
            summary.prompt_preview_at = datetime.utcnow()
            summary.cost_preview = 0.0
            try:
                await db.commit()
            except Exception as e2:
                logger.exception("提示词预览落库失败 %s", asset.code)
                entry.update(ok=False, error=f"提示词已生成但未落库，可重跑本口补写：{str(e2)[:200]}")

    ok_cnt = sum(1 for r in results if r["ok"])
    reused_cnt = sum(1 for r in results if r.get("reused"))
    await db.commit()
    return {
        "results": results,
        "message": (
            f"提示词预览：备好 {ok_cnt} 条 / 共 {len(results)} 条"
            + (f"（其中 {reused_cnt} 条用已有预览）" if reused_cnt else "")
            + "；预览是给人看的，投产时会重新展开"
        ),
    }


# ──────────────────────────────────────────────
# 单条详情 / 反推状态刷新（放在所有字面路径之后，避免吞掉 /assets/summaries 等）
# ──────────────────────────────────────────────


@router.get("/assets/{asset_id}/source-download")
async def download_asset_source(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """素材**原文件**下载地址（A4-4：P0 只有产物下载口，一线拿到一条素材想回看原片都没处点）。

    两种形态分开回，不硬凑：

    - `source_kind=file`（我们桶里有原片）→ `mode=stored` + presigned GET，浏览器直连；
    - `source_kind=link`（只存了分享链接）→ `mode=external`，`url` 为 null、把原始链接回显。
      回源解析（doc/107，0.01 元/次）11-03 已拍板**计入批次成本**，但那是显式动作
      `POST /assets/resolve`，不在下载口里自动发起——取片和取时长是两笔钱、两件事。

    和产物下载一样留审计：外链是一次性的，「谁在什么时候取过哪条原片」只能靠 AuditLog。
    审计写失败不挡下载（下载是既成事实，记不上总比记错好）。
    """
    asset = await _get_asset_or_404(db, asset_id)

    # 批 J：判「桶里有没有原片」以 **file_key 为准**，不再看 source_kind——
    # 链接素材反推后原片也会被下载进桶（download_status=success），这时它就是
    # stored 形态；只认 source_kind 会让"已经下载好的原片"仍然回 external。
    if asset.file_key:
        url = await get_presigned_url(
            asset.bucket or settings.MINIO_BUCKET_RAW,
            asset.file_key,
            expires_seconds=3600,
            as_attachment=True,
            filename=asset.file_name or f"{asset.code}.mp4",
        )
        if not url:
            raise HTTPException(status_code=502, detail="生成下载地址失败")
        mode = "stored"
    elif asset.source_kind == SOURCE_FILE:
        raise HTTPException(status_code=404, detail="该素材没有可下载的原文件（上传未成功）")
    else:
        if not asset.source_url:
            raise HTTPException(status_code=404, detail="该素材既没有原文件也没有来源链接")
        url = None
        mode = "external"

    now = datetime.utcnow()
    await _write_audit(
        db,
        action="asset.source.download",
        operator=current_user,
        target_type="asset_item",
        target_id=str(asset.id),
        after={
            "code": asset.code,
            "mode": mode,
            "source_kind": asset.source_kind,
            "file_name": asset.file_name,
            "file_key": asset.file_key,
            "source_url": (asset.source_url or "")[:300],
            "requested_at": now.isoformat(timespec="seconds"),
        },
    )
    await db.commit()

    return {
        "mode": mode,
        "url": url,
        "asset_code": asset.code,
        "file_name": asset.file_name,
        "size": asset.file_size,
        "duration": asset.duration,
        "downloaded_at": utc_iso(now),
        "expires_in": 3600 if url else None,
        "note": (
            None if url else
            "链接素材不在自有桶：url 为 null，请用 source_url 自行取片；"
            "要真实时长与时效直链走 POST /assets/resolve（doc/107 按次 0.01 元，已计入批次成本）"
        ),
        "source_url": asset.source_url if mode == "external" else None,
    }


@router.get("/assets/{asset_id}/source-preview")
async def preview_asset_source(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """素材**原文件内联预览**地址（批 E，11-04 拍板：抽屉里要能直接播）。

    和 `/source-download` 的唯一区别就是**不强制下载**：
    `as_attachment=True` 会给 presigned URL 挂上 `response-content-disposition=attachment`，
    浏览器拿到就当附件存盘，`<video src>` 挂上去是黑屏——一线反馈的"播不了"根因在这，
    不是前端播放器的问题。这里走 `as_attachment=False`（默认），MinIO 回的是对象自己的
    `Content-Type`（上传时按真实扩展名存，见 `_upload_into_batch`），
    Range 请求由 MinIO 直接响应（presigned 签名不覆盖 Range，所以拖动进度条不用我们代理）。

    **不写 AuditLog、不动 `downloaded_at`**：预览是"看"，点开抽屉就算一次，
    频率和下载不是一个量级，记进审计台账会把真正的交付动作淹掉；
    `downloaded_at` 的语义是"这条产物已交付出去过"，看一眼不能把它点亮。

    链接形态素材桶里没有文件：
    - **缓存直链还在有效期**（11-06 播放直链修复）→ 回 `mode=cached`，`url`＝上次取的
      时效直链。前端开抽屉直接把播放器架起来，0 元、不发起任何外呼——「取了直链再进来
      直链就没了」的根因就是这条路径以前不存在（resolve 只存时长不存直链）。
    - 缓存没有/已过期 → 回 `mode=external`：`url` 为 null，前端显示"这条还没回源，点解析"
      ——时效直链要 `POST /assets/resolve`（0.01 元/次）现拿现用；缓存过期的会提示带
      `retake=true` 重取。
    """
    asset = await _get_asset_or_404(db, asset_id)

    # 批 J：与 /source-download 同一条订正——桶里有没有原片以 **file_key 为准**，
    # 链接素材反推后下载进桶的，同样能内联播放。
    if asset.file_key:
        url = await get_presigned_url(
            asset.bucket or settings.MINIO_BUCKET_RAW,
            asset.file_key,
            expires_seconds=3600,
        )
        if not url:
            raise HTTPException(status_code=502, detail="生成预览地址失败（对象存储不可达）")
        mode = "stored"
    elif asset.source_kind == SOURCE_FILE:
        raise HTTPException(status_code=404, detail="该素材没有可预览的原文件（上传未成功）")
    else:
        cached, age_h = _cached_play_url(asset)
        if cached:
            url = cached
            mode = "cached"
        else:
            url = None
            mode = "external"

    return {
        "mode": mode,
        "url": url,
        "asset_code": asset.code,
        "file_name": asset.file_name,
        "source_kind": asset.source_kind,
        "platform": asset.platform,
        "size": asset.file_size,
        "duration": asset.duration,
        "resolution": asset.resolution,
        "expires_in": 3600 if url else None,
        "source_url": asset.source_url if mode == "external" else None,
        "cached": mode == "cached",
        "play_url_taken_at": (
            asset.play_url_at.isoformat() + "Z" if mode == "cached" and asset.play_url_at else None
        ),
        "note": (
            None
            if mode == "stored"
            else (
                f"回放 {age_h:.1f} 小时前取的直链（缓存，{settings.ASSET_PLAY_URL_TTL_HOURS:g} 小时内免费）；"
                "打不开或已过期就点「取直链并播放」重取（0.01 元/次）"
                if mode == "cached"
                else (
                    # external 只会是链接素材（SOURCE_FILE 没文件在上面就 404 了）
                    "上次取的直链已过期（时效直链源站会撤链）；点「取直链并播放」重取（0.01 元/次）"
                    if asset.duration
                    else "链接素材桶里没有文件，不能内联播放；点「取直链并播放」拿时效直链（0.01 元/次）后再播"
                )
            )
        ),
    }


# ──────────────────────────────────────────────
# 抽帧（批 F，11-04：审核台卡片图 + 封面图，纯呈现层）
# ──────────────────────────────────────────────

# 帧图的直链时效：卡片是"看一眼"的东西，1 小时够一轮审核；过期了前端重拉本口即可
_FRAME_URL_TTL_SECONDS = 3600

_FRAME_KIND_LABELS = {
    FRAME_THUMB: "单帧",
    FRAME_GRID: "九宫格",
    FRAME_OUTPUT_THUMB: "产物帧",
}

# 抽帧的并发锁按**事件循环**分桶。为什么不能是一个模块级 Semaphore：
# `asyncio.Semaphore` 在创建时就绑死当前 loop，测试每个用例一个新 loop、生产每个
# worker 进程一个 loop，模块级单例第二次用就是 "<Semaphore> is bound to a different
# event loop"。WeakKeyDictionary 让废弃的 loop 连带丢掉它那把锁，不漏水。
_FRAME_SEMAPHORES: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _frame_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _FRAME_SEMAPHORES.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, int(settings.ASSET_FRAME_CONCURRENCY)))
        _FRAME_SEMAPHORES[loop] = sem
    return sem


def _frame_key(
    asset_code: str, kind: str, seq: int, output_id: Optional[str] = None
) -> str:
    """桶内位置：`asset/frames/<素材码>/<kind>_<seq>.jpg`（产物帧再多一段产物短 id）。

    用**素材码**而不是素材 UUID：出问题时人眼能在桶里认出这是哪条（raw-footage 那套
    也是这么定的），而且重抽覆盖同名对象，不会越抽越多盘。
    """
    stem = f"{kind}_{seq}" if not output_id else f"{kind}_{output_id[:8]}_{seq}"
    return f"asset/frames/{asset_code}/{stem}.{framesvc.EXT}"


def _scaled_height(src_w: Optional[int], src_h: Optional[int], target_w: int) -> Optional[int]:
    """按 ffmpeg `scale=W:-2` 的算法推帧高（`-2`＝保比例且取偶数）。

    原片分辨率探不到就回 **None**：这个数只给前端占宽高比用，留空＝"不占位、加载出来再说"，
    比拿一个猜出来的数把卡片撑歪要好。
    """
    if not src_w or not src_h or src_w <= 0:
        return None
    h = int(round(target_w * src_h / src_w))
    if h <= 0:
        return None
    return h - (h % 2)


def _frame_dims(kind: str, src_w: Optional[int], src_h: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    """帧的 (宽, 高)：单帧按 `ASSET_FRAME_THUMB_WIDTH`，九宫格按整图宽 = 格宽 × 3。"""
    if kind == FRAME_GRID:
        total_w = int(settings.ASSET_FRAME_GRID_WIDTH)
        cell_w = max(64, total_w // framesvc.GRID_COLS)
        cell_h = _scaled_height(src_w, src_h, cell_w)
        return (
            cell_w * framesvc.GRID_COLS,
            None if cell_h is None else cell_h * framesvc.GRID_COLS,
        )
    w = int(settings.ASSET_FRAME_THUMB_WIDTH)
    return (w, _scaled_height(src_w, src_h, w))


async def _frames_io(task: Dict[str, Any]) -> Dict[str, Any]:
    """一段**纯 I/O**：取回片子 → ffmpeg 抽帧 → jpg 传回桶。全程不碰 db。

    和 `_ingest_one_video_file` 同一个道理（AsyncSession 不是并发安全的，所以并发只做
    I/O，写库留给调用方串行做，A4-5）。信号量在这里限流：一批 100 条同时下载＋解码
    就是把反推/拼接一起拖死。

    `task` 关键字段：`bucket` / `file_key` / `duration` / `asset_code` / `with_grid` /
    `single`（真＝只要 1 张、且改写成 output_thumb）。
    """
    bucket = task["bucket"]
    file_key = task["file_key"]
    async with _frame_semaphore():
        work = tempfile.mkdtemp(prefix="asset_frames_")
        try:
            local = os.path.join(work, "src.bin")
            if not await download_to_file(bucket, file_key, local):
                return {"ok": False, "skipped": False, "rows": [],
                        "reason": f"取回原片失败（{bucket}/{file_key[:60]}），稍后重抽"}
            dur = task.get("duration")
            if dur is None:
                # 兜底：入库时（A4-4）本该有时长，真没有就本地探一次，探不到才放弃
                dur = await _probe_duration(local)
                if dur is None:
                    return {"ok": False, "skipped": True, "rows": [],
                            "reason": "下载到本地也探不到时长，等时间轴有了再抽"}
            reason = framesvc.should_skip(dur)
            if reason:
                return {"ok": False, "skipped": True, "rows": [], "reason": reason}

            info = await compose.probe_media(local) or {}
            src_w = int(info.get("width") or 0) or None
            src_h = int(info.get("height") or 0) or None
            got = await framesvc.extract(
                local, float(dur), os.path.join(work, "out"), with_grid=bool(task["with_grid"])
            )
            picks = list(got["thumbs"])
            if task["single"]:
                # 产物只给 1 张：取**中段**那张（10% 处常常还是片头字卡，中段才是正片画面）
                picks = [picks[len(picks) // 2]] if picks else []
            if got["grid"] is not None:
                picks.append(got["grid"])
            if not picks:
                return {"ok": False, "skipped": False, "rows": [],
                        "reason": "；".join(got["errors"]) or "ffmpeg 一张都没抽出来"}

            errors = list(got["errors"])
            rows: List[Dict[str, Any]] = []
            for it in picks:
                kind = FRAME_OUTPUT_THUMB if task["single"] else it["kind"]
                seq = 0 if task["single"] else int(it["seq"])
                key = _frame_key(task["asset_code"], kind, seq, output_id=task.get("output_id"))
                w, h = _frame_dims(kind, src_w, src_h)
                uploaded = await upload_file_from_path(
                    settings.MINIO_BUCKET_RAW, key, it["path"], content_type=framesvc.CONTENT_TYPE
                )
                if not uploaded:
                    errors.append(f"{key} 传桶失败")
                    continue
                rows.append({
                    "kind": kind, "seq": seq, "t_offset": it.get("t_offset"),
                    "file_key": key, "bucket": settings.MINIO_BUCKET_RAW,
                    "width": w, "height": h, "file_size": it["file_size"],
                    "source_file_key": file_key,
                })
            if not rows:
                return {"ok": False, "skipped": False, "rows": [],
                        "reason": "；".join(errors) or "帧传桶全失败（旧帧没动）"}
            return {"ok": True, "skipped": False, "rows": rows,
                    "reason": ("部分成功：" + "；".join(errors[:2])) if errors else None}
        finally:
            shutil.rmtree(work, ignore_errors=True)


async def _store_frames(
    db: AsyncSession,
    asset: AssetItem,
    rows: List[Dict[str, Any]],
    *,
    output_id: Optional[str] = None,
) -> int:
    """先删同键旧行再插（幂等覆盖），并把第 1 张单帧写进 `cover_image_key`。

    ⚠️ 只在**这次真抽出图了**才被调用：抽失败时旧帧原样留着，一线顶多是看到旧图，
    不会看到"图没了"——那会被当成素材被删了。
    """
    conds = [AssetFrame.asset_id == asset.id]
    conds.append(AssetFrame.output_id.is_(None) if not output_id else AssetFrame.output_id == _as_uuid(output_id, "output_id"))
    await db.execute(delete(AssetFrame).where(and_(*conds)))
    oid = _as_uuid(output_id, "output_id") if output_id else None
    for r in rows:
        db.add(AssetFrame(asset_id=asset.id, output_id=oid, **r))
    # 封面＝本素材第 1 张单帧（`cover_image_key` 这列 11-04 之前**全链路没有写入方**，
    # 列表页那格永远空转；批 F 起它终于有值了。产物帧不动封面：封面是素材的卡片图）
    if not output_id:
        thumbs = sorted([r for r in rows if r["kind"] == FRAME_THUMB], key=lambda x: x["seq"])
        asset.cover_image_key = thumbs[0]["file_key"] if thumbs else None
    await db.commit()
    return len(rows)


def _frames_cap() -> int:
    return max(1, int(settings.ASSET_FRAME_MAX_PER_CALL))


async def _plan_asset_frames(
    db: AsyncSession, asset_ids: List[str], *, force: bool
) -> Tuple[List[Tuple[Dict[str, Any], AssetItem, None]], List[Dict[str, Any]]]:
    """素材侧：串行读库定「抽不抽」，返回 (待办 I/O 任务, 已定的 skip/fail 结果)。"""
    pending = []
    decided: List[Dict[str, Any]] = []
    for aid in asset_ids:
        base = {"target": "asset", "id": aid}
        asset = await db.get(AssetItem, _as_uuid(aid, "asset_ids"))
        if asset is None:
            decided.append({**base, "result": "failed", "frames": 0, "reason": "素材不存在"})
            continue
        base["code"] = asset.code
        if asset.media_kind == MEDIA_IMAGE:
            # 批 G：图不用抽帧 —— 入库时已把原图直接当封面（cover_image_key = file_key），
            # 再跑一遍 ffmpeg 只是把同一张 jpg 解码成 jpg，白占后台名额
            decided.append({**base, "result": "skipped", "frames": 0,
                            "reason": "这张本来就是图片，卡片直接用原图，不用抽帧"})
            continue
        existing = list(
            (
                await db.execute(
                    select(AssetFrame).where(
                        AssetFrame.asset_id == asset.id, AssetFrame.output_id.is_(None)
                    )
                )
            ).scalars().all()
        )
        if existing and not force:
            decided.append({**base, "result": "skipped", "frames": len(existing),
                            "reason": f"已经有 {len(existing)} 张帧（要重抽带 force=true）"})
            continue
        # 11-05 易操作性评估 P0-1（另一半）：老判据 `source_kind != SOURCE_FILE` 把
        # **下载完成的链接素材也一并拒了**——下载落桶后 file_key 非空、原片就在桶里，
        # 却照样跳过，导致"下载成功补排抽帧"在执行侧空转（现网回填实测当场暴露）。
        # 判据改为只看 file_key：有文件就抽，没有才跳过（话术区分"还没下载"与"没文件"）。
        if not asset.file_key:
            reason = (
                "链接素材的原片还没下载到自有桶，抽不了帧；先在列表/抽屉里点「下载原片」"
                "（下载成功那次会自动补排抽帧；若下载早已完成却还是没帧，"
                "在抽帧口带 asset_ids 手动补一次）（要看画面也可先在抽屉里「取直链并播放」）"
                if asset.source_kind != SOURCE_FILE
                else "这条没有可用的视频文件，抽不了帧"
            )
            decided.append({**base, "result": "skipped", "frames": 0, "reason": reason})
            continue
        reason = framesvc.should_skip(asset.duration)
        if reason:
            decided.append({**base, "result": "skipped", "frames": 0, "reason": reason})
            continue
        pending.append((
            {
                "bucket": asset.bucket or settings.MINIO_BUCKET_RAW,
                "file_key": asset.file_key,
                "duration": asset.duration,
                "asset_code": asset.code,
                "with_grid": True,
                "single": False,
                "output_id": None,
            },
            asset,
            None,
        ))
    return pending, decided


async def _plan_output_frames(
    db: AsyncSession, output_ids: List[str], *, force: bool
) -> Tuple[List[Tuple[Dict[str, Any], AssetItem, str]], List[Dict[str, Any]]]:
    """产物侧：每个产物补 1 张 `output_thumb`（豆包成片要等批 H 才有第二个写入方）。"""
    pending = []
    decided: List[Dict[str, Any]] = []
    for oid in output_ids:
        base = {"target": "output", "id": oid}
        out_row = await db.get(AssetOutput, _as_uuid(oid, "output_ids"))
        if out_row is None:
            decided.append({**base, "result": "failed", "frames": 0, "reason": "产物不存在"})
            continue
        asset = await db.get(AssetItem, out_row.asset_id)
        if asset is None:
            decided.append({**base, "result": "failed", "frames": 0,
                            "reason": "产物找不到归属素材（数据异常），没抽"})
            continue
        base["code"] = out_row.file_name
        existing = list(
            (
                await db.execute(
                    select(AssetFrame).where(AssetFrame.output_id == out_row.id)
                )
            ).scalars().all()
        )
        if existing and not force:
            decided.append({**base, "result": "skipped", "frames": len(existing),
                            "reason": f"这个产物已经有 {len(existing)} 张帧（force=true 才重抽）"})
            continue
        if not out_row.file_key:
            decided.append({**base, "result": "skipped", "frames": 0, "reason": "产物没有文件（只有外链），抽不了帧"})
            continue
        pending.append((
            {
                "bucket": out_row.bucket or settings.MINIO_BUCKET_RAW,
                "file_key": out_row.file_key,
                "duration": out_row.duration,
                "asset_code": asset.code,
                "with_grid": False,
                "single": True,
                "output_id": str(out_row.id),
            },
            asset,
            str(out_row.id),
        ))
    return pending, decided


def _log_frames_summary(results: List[Dict[str, Any]]) -> None:
    """抽帧收尾把失败/跳过原因打成日志——此前这些路径只落 job.result JSON，界面上
    「没有预览图」却没人知道为什么（审计实锤的静默失败）。"""
    failed = [r for r in results if r.get("result") == "failed"]
    skipped = [r for r in results if r.get("result") == "skipped"]
    extracted = [r for r in results if r.get("result") == "extracted"]
    if failed:
        logger.warning(
            "抽帧失败 %d 条（成功 %d、跳过 %d）：%s",
            len(failed), len(extracted), len(skipped),
            "; ".join(f"{r.get('code', r.get('id'))}: {r.get('reason', '')[:120]}" for r in failed[:10]),
        )
    elif skipped:
        logger.info("抽帧跳过 %d 条（成功 %d）：%s",
                    len(skipped), len(extracted),
                    "; ".join(f"{r.get('code', r.get('id'))}: {r.get('reason', '')[:80]}" for r in skipped[:10]))


async def _run_frames_requests(
    db: AsyncSession, asset_ids: List[str], output_ids: List[str], *, force: bool
) -> List[Dict[str, Any]]:
    """抽帧的执行体：串行定名单 → 并发跑 I/O → 串行写库。"""
    asset_pending, results = await _plan_asset_frames(db, asset_ids, force=force)
    output_pending, output_decided = await _plan_output_frames(db, output_ids, force=force)
    results = results + output_decided
    pending = asset_pending + output_pending
    if not pending:
        _log_frames_summary(results)
        return results
    io_results = await asyncio.gather(
        *[_frames_io(t) for t, _a, _o in pending], return_exceptions=True
    )
    for (task, asset, oid), io in zip(pending, io_results):
        base = {"target": "asset" if oid is None else "output",
                "id": str(oid or asset.id), "code": task["asset_code"] if oid is None else asset.code}
        if isinstance(io, BaseException):
            logger.exception("抽帧 I/O 异常 %s", base["id"])
            results.append({**base, "result": "failed", "frames": 0,
                            "reason": f"{type(io).__name__}: {io}"[:300]})
            continue
        if not io["ok"]:
            results.append({**base, "result": "skipped" if io["skipped"] else "failed",
                            "frames": 0, "reason": io["reason"]})
            continue
        try:
            n = await _store_frames(db, asset, io["rows"], output_id=oid)
        except Exception as exc:  # noqa: BLE001 — 单条写库炸了不该把整批带走
            await db.rollback()
            logger.exception("抽帧写库失败 %s", base["id"])
            results.append({**base, "result": "failed", "frames": 0,
                            "reason": f"帧已传到桶但写库失败：{type(exc).__name__}: {exc}"[:280]})
            continue
        results.append({**base, "result": "extracted", "frames": n,
                        "cover": asset.cover_image_key if oid is None else None,
                        "reason": io["reason"]})
    _log_frames_summary(results)
    return results


@router.post("/assets/frames/extract")
async def extract_frames(
    data: FramesExtractRequest,
    current_user: Annotated[User, Depends(require_roles(*_PROD_ROLES))],
    db: AsyncSession = Depends(get_db),
):
    """手动抽帧 / 重抽（批 F）。`async_mode=true` 排后台任务、立即回任务号。

    这条口同时是**后台任务 `kind=frames` 的执行体**（`_job_endpoint(JOB_FRAMES)` 回到这里），
    和 D-1 那两条一个规矩：后台不另写一套逻辑，就是把本口原样再调一遍。

    为什么默认不 `force`：抽帧要**把整个原片从桶里拉回本地**再解码，重复抽一条已经有图的
    素材是白占 CPU（导入自动排的那次通常已经成功）。要看新图就带 `force=true`。
    """
    asset_ids = list(dict.fromkeys(str(x) for x in (data.asset_ids or []) if str(x)))
    output_ids = list(dict.fromkeys(str(x) for x in (data.output_ids or []) if str(x)))
    if not asset_ids and not output_ids:
        raise HTTPException(status_code=400, detail="要抽帧至少点名 asset_ids 或 output_ids")
    total = len(asset_ids) + len(output_ids)
    cap = _frames_cap()
    if total > cap:
        raise HTTPException(
            status_code=400,
            detail=(
                f"一次最多 {cap} 个对象（当前 {total} 个）：抽帧不花钱但每条都要下载原片＋跑 ffmpeg，"
                f"同步等 {total} 条必然挂到网关超时。要么分次点，要么带 async_mode=true 排后台"
            ),
        )
    for aid in asset_ids:
        _as_uuid(aid, "asset_ids")
    for oid in output_ids:
        _as_uuid(oid, "output_ids")

    if data.async_mode:
        job = await _start_asset_job(
            db,
            kind=JOB_FRAMES,
            data=data,
            operator=current_user,
            batch_id=None,
            planned_units=total,
        )
        return _job_accepted(job, "抽帧")

    results = await _run_frames_requests(db, asset_ids, output_ids, force=data.force)
    extracted = [r for r in results if r["result"] == "extracted"]
    skipped = [r for r in results if r["result"] == "skipped"]
    failed = [r for r in results if r["result"] == "failed"]
    frames_total = sum(int(r.get("frames") or 0) for r in extracted)
    await _write_audit(
        db,
        action="asset.frames.extract",
        operator=current_user,
        target_type="asset_item",
        target_id=None,
        after={
            "asset_ids": asset_ids,
            "output_ids": output_ids,
            "force": bool(data.force),
            "extracted": len(extracted),
            "skipped": len(skipped),
            "failed": len(failed),
            "frames": frames_total,
        },
    )
    await db.commit()
    return {
        "results": results,
        "extracted": len(extracted),
        "skipped": len(skipped),
        "failed": len(failed),
        "frames": frames_total,
        "note": (
            "抽帧只出卡片图和封面，抽不到不影响审核、投产、导出任何一步；"
            "skipped 每条都带人话原因（链接素材没原片／时长未知／超过抽帧上限／已经有帧）"
        ),
        "message": (
            f"抽出 {len(extracted)} 个对象共 {frames_total} 张图"
            + (f"，跳过 {len(skipped)} 个" if skipped else "")
            + (f"，失败 {len(failed)} 个（可以再点一次）" if failed else "")
        ),
    }


@router.get("/assets/frames")
async def list_asset_frames(
    asset_ids: Optional[str] = None,
    output_ids: Optional[str] = None,
    kind: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按素材/产物**批量**取卡片图（审核台一次拉一页，别逐行发请求）。

    ⚠️ 路由顺序：本口必须声明在 `GET /assets/{asset_id}` **之前**，否则 "frames"
    会被当成 asset_id 进详情口，返回的是 400「asset_id 不是合法 id」而不是 404。

    读权限＝`get_current_user`（和 `source-preview` 一个口径：素材内容对全员可见，
    看图不是写操作），所以审核人（operator/admin）与素材专员都能拉。
    直链 1 小时过期，不写 AuditLog（翻卡片看图不是交付动作）。
    """
    aids = _split_ids(asset_ids, "asset_ids")
    oids = _split_ids(output_ids, "output_ids")
    if not aids and not oids:
        raise HTTPException(status_code=400, detail="要取卡片图至少带 asset_ids 或 output_ids")
    if len(aids) + len(oids) > 50:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多 50 个对象（当前 {len(aids) + len(oids)}）：一页卡片用不完，翻页再拉",
        )
    kinds: Optional[Tuple[str, ...]] = None
    if kind:
        if kind not in ASSET_FRAME_KINDS:
            raise HTTPException(
                status_code=400, detail=f"kind 只支持 {'/'.join(ASSET_FRAME_KINDS)}"
            )
        kinds = (kind,)

    conds = []
    if aids:
        conds.append(AssetFrame.asset_id.in_([uuid.UUID(x) for x in aids]))
    if oids:
        conds.append(AssetFrame.output_id.in_([uuid.UUID(x) for x in oids]))
    if kinds:
        conds.append(AssetFrame.kind.in_(list(kinds)))
    rows = list(
        (
            await db.execute(
                select(AssetFrame).where(or_(*conds)).order_by(AssetFrame.kind, AssetFrame.seq)
            )
        ).scalars().all()
    )

    frames: List[Dict[str, Any]] = []
    by_asset: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        url = await get_presigned_url(
            r.bucket or settings.MINIO_BUCKET_RAW,
            r.file_key,
            expires_seconds=_FRAME_URL_TTL_SECONDS,
        )
        item = {
            "id": str(r.id),
            "asset_id": str(r.asset_id),
            "output_id": str(r.output_id) if r.output_id else None,
            "kind": r.kind,
            "kind_label": _FRAME_KIND_LABELS.get(r.kind, r.kind),
            "seq": r.seq,
            "t_offset": r.t_offset,
            "width": r.width,
            "height": r.height,
            "file_size": r.file_size,
            "url": url,
            "expires_in": _FRAME_URL_TTL_SECONDS if url else None,
        }
        frames.append(item)
        if r.output_id is None:
            slot = by_asset.setdefault(str(r.asset_id), {"thumbs": [], "grid": None})
            if r.kind == FRAME_GRID:
                slot["grid"] = item
            elif r.kind == FRAME_THUMB:
                slot["thumbs"].append(item)
    for slot in by_asset.values():
        slot["thumbs"].sort(key=lambda x: x["seq"])

    # 封面：认 `cover_image_key` 这一列（它和帧同一事务写，不会指向一个已被删掉的对象）
    covers: Dict[str, Optional[str]] = {}
    if aids:
        for a in (await db.execute(select(AssetItem).where(AssetItem.id.in_([uuid.UUID(x) for x in aids])))).scalars():
            url = None
            if a.cover_image_key:
                url = await get_presigned_url(
                    settings.MINIO_BUCKET_RAW, a.cover_image_key,
                    expires_seconds=_FRAME_URL_TTL_SECONDS,
                )
            covers[str(a.id)] = url
    missing = [a for a in aids if a not in by_asset]
    return {
        "frames": frames,
        "by_asset": by_asset,
        "cover_url": covers,
        "missing": missing,
        "note": (
            f"图由抽帧任务生成，{len(missing)} 条一张都没有（卡片显示「没有预览图」即可，"
            "不影响审核与投产）；直链 "
            f"{_FRAME_URL_TTL_SECONDS // 60} 分钟过期，过期重新拉本口"
        ),
    }


async def _enqueue_frames(
    db: AsyncSession,
    *,
    asset_ids: List[str],
    output_ids: List[str],
    operator: Optional[User],
    why: str,
) -> Dict[str, Any]:
    """系统自己排一份抽帧任务（导入/拼接成功后调用）。**绝不把主流程带崩**。

    抽帧没排上只是卡片没图，而导入已经真金白银落库了、拼接已经花掉 CPU 拼完了——
    所以整段包住，失败只回一条 note，让一线看得见"这次没排上"而不是以为在排。
    """
    if operator is None or (not asset_ids and not output_ids):
        return {"queued": False, "note": "没排抽帧（缺提交人或缺对象 id）"}
    try:
        # 按 cap 分片：手动口一次最多 _frames_cap() 个对象（超了整单 400），系统自排
        # 没人把关，批量下载 21+ 条成功时曾把整批抽帧任务在后台被 cap 拒掉（静默全丢）。
        cap = _frames_cap()
        pairs: List[tuple] = []
        a_list = list(asset_ids)
        for i in range(0, len(a_list), cap):
            pairs.append((a_list[i:i + cap], []))
        o_list = list(output_ids)
        for i in range(0, len(o_list), cap):
            pairs.append(([], o_list[i:i + cap]))
        total_units = 0
        first_job_id = None
        for aids, oids in pairs:
            if not aids and not oids:
                continue
            job = await _start_asset_job(
                db,
                kind=JOB_FRAMES,
                data=FramesExtractRequest(asset_ids=aids, output_ids=oids),
                operator=operator,
                batch_id=None,
                planned_units=len(aids) + len(oids),
            )
            total_units += len(aids) + len(oids)
            first_job_id = first_job_id or str(job.id)
        job_id_out = first_job_id
        return {
            "queued": True,
            "job_id": job_id_out,
            "note": (
                f"{why}：抽帧已排后台（{total_units} 个对象"
                + (f"，按上限 {cap} 分成了若干批" if total_units > cap else "")
                + "），几分钟后卡片就有图；"
                "这类任务不进任务横幅列表（kind=frames 默认不列），要看进度带 include_frames=true"
            ),
        }
    except HTTPException as exc:
        # 走到这里基本只有一种：同对象已经在抽（重复导入/连点重抽）——那是好事不是错误
        logger.info("抽帧任务没排上（%s）：%s", why, exc.detail)
        return {"queued": False, "note": f"抽帧没重排（{why}）：{str(exc.detail)[:160]}"}
    except Exception as exc:  # noqa: BLE001 — 排程失败不能连累导入/拼接的结果
        await db.rollback()
        logger.exception("抽帧任务排程异常（%s）", why)
        return {
            "queued": False,
            "note": (
                f"抽帧没排上（{type(exc).__name__}），不影响导入；卡片会一直显示「没有预览图」，"
                "可以带 asset_ids 走 POST /assets/frames/extract 手动补"
            ),
        }


async def _enqueue_download(
    db: AsyncSession,
    *,
    asset_ids: List[str],
    operator: Optional[User],
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """系统自己排一份「下载原片」任务（反推提交后调用，批 J）。**绝不把主流程带崩**。

    反推本身已经真金白银落库了，下载只是搭车的回看便利——所以整段包住，
    排不上只回一条 note，让一线看得见"这次没排上、可单独重试"，而不是反推整体报错。
    """
    if operator is None or not asset_ids:
        return {"queued": False, "job_id": None, "queued_count": 0, "note": "没排下载（缺提交人或缺素材 id）"}
    try:
        job = await _start_asset_job(
            db,
            kind=JOB_DOWNLOAD,
            data=AssetDownloadRequest(asset_ids=list(asset_ids)),
            operator=operator,
            batch_id=batch_id,
            planned_units=len(asset_ids),
        )
        return {
            "queued": True,
            "job_id": str(job.id),
            "queued_count": len(asset_ids),
            "note": None,
        }
    except HTTPException as exc:
        logger.info("下载原片任务没排上：%s", exc.detail)
        return {
            "queued": False, "job_id": None, "queued_count": 0,
            "note": f"原片下载没排上：{str(exc.detail)[:200]}；可在列表上对素材单独重试",
        }
    except Exception as exc:  # noqa: BLE001 — 排程失败不能连累反推的结果
        await db.rollback()
        logger.exception("下载原片任务排程异常")
        return {
            "queued": False, "job_id": None, "queued_count": 0,
            "note": f"原片下载没排上（{type(exc).__name__}），不影响反推；可稍后单独重试",
        }


async def _enqueue_preview(
    db: AsyncSession,
    *,
    summary_ids: List[str],
    operator: Optional[User],
) -> Dict[str, Any]:
    """系统自己排一份「备豆包提示词」任务（过审 commit 后调用，批 J）。**绝不把审核带崩**。

    审核结果已经落库生效，预览是搭车的——排不上（同批已有预览任务在跑的 409 也算）
    只回 note；口径与 `_enqueue_download`/`_enqueue_frames` 一致：搭车动作不倒打主流程。
    """
    if operator is None or not summary_ids:
        return {"queued": False, "job_id": None, "note": "没排预览（缺提交人或缺文案 id）"}
    try:
        job = await _start_asset_job(
            db,
            kind=JOB_PROMPT_PREVIEW,
            data=PromptPreviewRequest(summary_ids=list(summary_ids)),
            operator=operator,
            batch_id=None,
            planned_units=len(summary_ids),
        )
        return {
            "queued": True,
            "job_id": str(job.id),
            "note": None,
        }
    except HTTPException as exc:
        logger.info("提示词预览任务没排上：%s", exc.detail)
        return {
            "queued": False, "job_id": None,
            "note": f"提示词预览没排上：{str(exc.detail)[:200]}；过审本身已生效，可稍后重跑预览口",
        }
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("提示词预览任务排程异常")
        return {
            "queued": False, "job_id": None,
            "note": f"提示词预览没排上（{type(exc).__name__}），不影响审核；可稍后重跑预览口",
        }


def _split_ids(raw: Optional[str], field: str) -> List[str]:
    """`?asset_ids=a,b` → [a, b]：去空、去重、非法 UUID 当场 400 说清是哪一颗。"""
    out: List[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            uuid.UUID(part)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail=f"{field} 里有不是 id 的值：{part[:40]}（多个用英文逗号分隔）"
            )
        if part not in out:
            out.append(part)
    return out


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """素材详情：含全部文案候选与生产单（列表页点开一条看到全链路）。"""
    asset = await _get_asset_or_404(db, asset_id)
    summaries = (
        await db.execute(
            select(AssetSummary).where(AssetSummary.asset_id == asset.id).order_by(AssetSummary.seq)
        )
    ).scalars().all()
    prods = (
        await db.execute(
            select(AssetProduction).where(AssetProduction.asset_id == asset.id).order_by(AssetProduction.seq)
        )
    ).scalars().all()
    script = None
    prompt_task = None
    if asset.prompt_task_id:
        task = await get_prompt_task(db, asset.prompt_task_id)
        if task is not None:
            prompt_task = serialize_prompt_task(task)
            script = task.content
    return {
        # 详情也带同一套计数字段：前端列表行与详情抽屉用同一个 serializer，省得两边判 nil
        "asset": _serialize_item(asset, {
            "summary_count": len(summaries),
            "approved_count": sum(1 for s in summaries if s.audit_status in REVIEW_PASSED_STATES),
            "pending_review_count": sum(1 for s in summaries if s.audit_status == RV_PENDING),
            "production_count": len(prods),
            "category_name": (await _category_name_map(db)).get(
                str(asset.category_id)) if asset.category_id else None,
        }),
        "summaries": [_serialize_summary(s) for s in summaries],
        "productions": [_serialize_production(p) for p in prods],
        "prompt_task": prompt_task,
        "prompt_script": script,
    }


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: str,
    force: bool = Query(False, description="admin 连坐强删：连文案/生产单/产物一起带走，必须带 reason"),
    reason: str = Query("", description="force 删除的理由（进审计），不带理由的强删直接拒"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除一条素材（11-06 用户拍板：列表要有删除功能）。

    权限：**本人删自己的**（任何角色都行——素材是谁导的谁最有资格说它没用了），
    删别人的只有 admin。与「改后重提」的门槛同一口径。

    护栏（默认路径，不带 force）：
    - 挂着文案 / 生产单 / 产物 → 409 拒删。这三类是审核与投放的**交付台账**
      （A2-2 的同一条铁律：静默连坐删掉它们，对账就无从下手），删素材前必须先处理。
    - 有同一批 asset_jobs 还在跑（圈住了这条素材）→ 409 拒删，等跑完再说——
      否则下载/出文案跑一半底下的素材行没了，任务回填时必然报错。

    force（仅 admin + 必填 reason）：连坐删文案、生产单、产物、帧，桶里的对象尽力删
    （删不掉只留日志，不拦 DB 删除——桶不设过期，宁可多留一份孤儿对象也别让
    "删素材"卡死在 MinIO 抖动上）。force 走 strict 审计（拍板①：force 类动作
    审计失败即拒绝）。产物/文案/素材三张表对 asset_items 的 FK 都是
    ON DELETE CASCADE，但这里**显式逐表删**：SQLite 测试引擎不强制外键，
    靠 DB 级联在测试里就是"看起来删了"，换个库行为就分叉。
    """
    asset = await _get_asset_or_404(db, asset_id)

    is_admin = current_user.role == UserRole.admin
    is_owner = asset.created_by is not None and str(asset.created_by) == str(current_user.id)
    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=403,
            detail="只能删除自己导入的素材；删别人导入的要管理员",
        )

    # ── 护栏 1：还在跑的任务圈住了这条素材 ──
    str_id = str(asset.id)
    open_jobs = (
        await db.execute(select(AssetJob).where(AssetJob.status.in_(JOB_OPEN_STATES)))
    ).scalars().all()
    for job in open_jobs:
        if str_id in _job_scope_ids(job.kind, job.params or {}):
            raise HTTPException(
                status_code=409,
                detail=f"这条素材还有正在跑的后台任务（{job.kind}，任务 {job.id}），等任务跑完再删",
            )

    # ── 护栏 2：交付台账挂着就默认拒删 ──
    n_summaries = int(
        (await db.execute(
            select(func.count(AssetSummary.id)).where(AssetSummary.asset_id == asset.id)
        )).scalar_one()
    )
    n_prods = int(
        (await db.execute(
            select(func.count(AssetProduction.id)).where(AssetProduction.asset_id == asset.id)
        )).scalar_one()
    )
    n_outputs = int(
        (await db.execute(
            select(func.count(AssetOutput.id)).where(AssetOutput.asset_id == asset.id)
        )).scalar_one()
    )
    attached = [
        name for name, n in (("文案", n_summaries), ("生产单", n_prods), ("产物", n_outputs)) if n
    ]
    if attached and not force:
        tip = (
            "；确实要连历史一起删，让管理员用「强制删除」并留理由"
            if not is_admin else
            "；管理员可加 force=true 并带 reason 强制连坐删除"
        )
        raise HTTPException(
            status_code=409,
            detail=f"这条素材已挂 {'、'.join(attached)}，删除会把审核与投放历史一起带走" + tip,
        )
    if attached and force and not is_admin:
        raise HTTPException(status_code=403, detail="强制删除挂有文案/生产单/产物的素材只有管理员能做")
    if force and not reason.strip():
        raise HTTPException(status_code=400, detail="强制删除必须带理由（reason），进审计留痕")

    # ── 收集桶对象（尽力删）──
    frames = (
        await db.execute(select(AssetFrame).where(AssetFrame.asset_id == asset.id))
    ).scalars().all()
    outputs = (
        await db.execute(select(AssetOutput).where(AssetOutput.asset_id == asset.id))
    ).scalars().all()
    candidates: List[Tuple[str, str, str]] = []  # (bucket, key, 归属说明)
    if asset.file_key:
        candidates.append((asset.bucket or settings.MINIO_BUCKET_RAW, asset.file_key, "原片"))
    if asset.cover_image_key:
        candidates.append((asset.bucket or settings.MINIO_BUCKET_RAW, asset.cover_image_key, "封面图"))
    for f in frames:
        if f.file_key:
            candidates.append((f.bucket or settings.MINIO_BUCKET_RAW, f.file_key, "抽帧图"))
    for o in outputs:
        if o.file_key:
            candidates.append((o.bucket or settings.MINIO_BUCKET_SLICED, o.file_key, "产物"))

    # ── 删行（顺序：产物 → 帧 → 文案 → 生产单 → 素材；frames.output_id 的 FK 指产物）──
    for o in outputs:
        await db.delete(o)
    for f in frames:
        await db.delete(f)
    if n_summaries:
        await db.execute(delete(AssetSummary).where(AssetSummary.asset_id == asset.id))
    if n_prods:
        await db.execute(delete(AssetProduction).where(AssetProduction.asset_id == asset.id))
    await _write_audit(
        db,
        action="asset.asset.delete",
        operator=current_user,
        target_type="asset_item",
        target_id=asset.id,
        before={
            "code": asset.code,
            "title": asset.title,
            "platform": asset.platform,
            "source_kind": asset.source_kind,
            "media_kind": asset.media_kind,
            "status": asset.status,
            "file_key": asset.file_key,
            "cost_prompt": asset.cost_prompt,
            "cost_parse": asset.cost_parse,
            "cost_produce": asset.cost_produce,
            "batch_id": str(asset.batch_id) if asset.batch_id else None,
        },
        after={
            "deleted": True,
            "force": bool(force and attached),
            "reason": reason.strip() or None,
            "removed_outputs": len(outputs),
            "removed_frames": len(frames),
            "removed_summaries": n_summaries,
            "removed_productions": n_prods,
        },
        strict=bool(force and attached),
    )
    batch = None
    if asset.batch_id:
        batch = (
            await db.execute(select(AssetBatch).where(AssetBatch.id == asset.batch_id))
        ).scalar_one_or_none()
    await db.delete(asset)
    await db.flush()
    if batch is not None:
        batch.item_count = max(0, (batch.item_count or 0) - 1)
    await db.commit()

    # ── 桶对象最后删（DB 已落定，MinIO 抖动不影响删除结果）──
    removed_objects = 0
    for bucket, key, what in candidates:
        try:
            if await delete_file(bucket, key):
                removed_objects += 1
        except Exception:
            logger.warning("删除素材 %s 的%s对象失败 %s/%s", asset.code, what, bucket, key, exc_info=True)

    logger.info(
        "素材已删除 code=%s by=%s force=%s outputs=%s frames=%s objects=%s",
        asset.code, current_user.username, bool(force and attached),
        len(outputs), len(frames), removed_objects,
    )
    return {
        "deleted": asset.code,
        "force": bool(force and attached),
        "removed_outputs": len(outputs),
        "removed_frames": len(frames),
        "removed_objects": removed_objects,
        "message": (
            f"已删除素材 {asset.code}（连坐删除文案 {n_summaries} 条、生产单 {n_prods} 张、产物 {len(outputs)} 份；理由已进审计）"
            if (force and attached) else
            f"已删除素材 {asset.code}"
        ),
    }


@router.post("/assets/{asset_id}/prompt-refresh")
async def refresh_asset_prompt(
    asset_id: str,
    current_user: User = Depends(require_roles(*_PROD_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """轮询反推任务并把阶段收敛（前端「在跑」列表增量刷新用）。

    只在 processing 时才发外部查询（refresh_prompt_task 内部已保证），终态不重复请求。

    A4-4 的链接侧时长回写：反推成功是这条素材**唯一**能拿到时长的时机（智令只回提示词，
    不回 duration；我们也没为省钱去调 doc/107）。所以只在 `source_url` 本身就是可直连的
    视频地址时探一次；分享页链接（抖音/小红书那种 HTML）探不出来就留着 null，
    前端按「未知」渲染占位，绝不写 0。批量收敛口（/assets/analyze/refresh-batch）**不做**
    这件事——一条最多挂 8 秒，200 条就是十几分钟，那是异步 Job 的活。
    """
    asset = await _get_asset_or_404(db, asset_id)
    if not asset.prompt_task_id:
        raise HTTPException(status_code=400, detail="该素材还没有反推任务")
    task = await get_prompt_task(db, asset.prompt_task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="反推任务不存在")
    task = await refresh_prompt_task(db, task)
    if task.status == PT_SUCCESS:
        svc.apply_stage(asset, "prompt", STAGE_SUCCESS)
        _backfill_title_on_prompt_success(asset, task.content)
        if (
            asset.duration is None
            and asset.source_kind == SOURCE_LINK
            and svc.looks_like_direct_url(asset.source_url)
        ):
            probed = await _probe_url_duration(asset.source_url)
            if probed is not None:
                asset.duration = probed
                duration_probed = True
    elif task.status == PT_FAILED:
        svc.apply_stage(asset, "prompt", STAGE_FAILED)
        asset.note = ((asset.note or "") + f"\n反推失败：{task.error}")[:1000]
    await db.commit()
    # P1（评审定稿⑫）：手动刷新反推状态留痕（此前该口无审计）
    await _write_audit(
        db,
        action="asset.prompt_refresh",
        operator=current_user,
        target_type="asset_item",
        target_id=str(asset.id),
        after={"code": asset.code, "stage_prompt": asset.stage_prompt},
    )
    result = {"asset": _serialize_item(asset), "prompt_task": serialize_prompt_task(task)}
    if asset.source_kind == SOURCE_LINK and asset.duration is None:
        result["duration_note"] = (
            "分享页链接拿不到时长：库里不存原片，智令反推也只回提示词。"
            "要时长走 POST /assets/resolve 显式回源解析（doc/107 按次 0.01 元，计入批次成本）"
        )
    return result
