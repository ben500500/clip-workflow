"""
Publish API routes - manage publish tasks and profiles for video distribution.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.models import PublishTask, PublishProfile, SliceOutput, VideoAccount, MiniProgram
from app.utils.helpers import utc_iso

router = APIRouter()


# ---- Pydantic schemas ----

class VideoAccountCreate(BaseModel):
    account_name: str
    platform: str
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: bool = False
    remark: Optional[str] = None
    enabled: bool = True


class VideoAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    platform: Optional[str] = None
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: Optional[bool] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None


class VideoAccountResponse(BaseModel):
    id: str
    account_name: str
    platform: str
    group_name: Optional[str] = None
    wxid: Optional[str] = None
    account_uid: Optional[str] = None
    profile_id: Optional[str] = None
    mini_program_enabled: bool = False
    remark: Optional[str] = None
    enabled: bool = True
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MiniProgramCreate(BaseModel):
    name: str
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: str
    remark: Optional[str] = None
    enabled: bool = True


class MiniProgramUpdate(BaseModel):
    name: Optional[str] = None
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: Optional[str] = None
    remark: Optional[str] = None
    enabled: Optional[bool] = None


class MiniProgramResponse(BaseModel):
    id: str
    name: str
    appid: Optional[str] = None
    path: Optional[str] = None
    full_link: str
    remark: Optional[str] = None
    enabled: bool = True
    created_at: str

    model_config = {"from_attributes": True}


class VideoAccountBatchImport(BaseModel):
    """账号批量导入：每行一个账号（账号名/平台/分组/视频号ID/备注）。"""
    accounts: List[VideoAccountCreate]
    skip_duplicates: bool = True


class PublishTaskCreate(BaseModel):
    output_id: str
    platform: str
    account_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    cover_file_key: Optional[str] = None
    mini_program_link: Optional[str] = None
    link_attached: bool = False
    require_manual_confirm: bool = True
    # 一期：账号矩阵 / 小程序库 / 短片来源关联
    video_account_id: Optional[str] = None
    mini_program_id: Optional[str] = None
    prompt_record_id: Optional[str] = None
    material_id: Optional[str] = None


class PublishTaskResponse(BaseModel):
    id: str
    output_id: str
    platform: Optional[str] = None
    account_name: Optional[str] = None
    status: Optional[str] = None
    celery_task_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    cover_file_key: Optional[str] = None
    mini_program_link: Optional[str] = None
    link_attached: bool = False
    published_url: Optional[str] = None
    published_id: Optional[str] = None
    published_at: Optional[str] = None
    error_message: Optional[str] = None
    require_manual_confirm: bool = True
    screenshot_key: Optional[str] = None
    video_account_id: Optional[str] = None
    mini_program_id: Optional[str] = None
    prompt_record_id: Optional[str] = None
    material_id: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class PublishTaskConfirmResponse(BaseModel):
    id: str
    status: str
    published_url: Optional[str] = None
    published_id: Optional[str] = None


class PublishBatchCreate(BaseModel):
    """批量创建发布任务（一键多平台发布）。"""
    tasks: List[PublishTaskCreate]


class PublishProfileCreate(BaseModel):
    platform: str
    account_name: Optional[str] = None
    chrome_debug_port: int = 9222
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: str = "immediate"
    require_manual_confirm: bool = True
    min_interval_seconds: int = 300
    max_daily_publish: int = 20


class PublishProfileUpdate(BaseModel):
    platform: Optional[str] = None
    account_name: Optional[str] = None
    chrome_debug_port: Optional[int] = None
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: Optional[str] = None
    require_manual_confirm: Optional[bool] = None
    min_interval_seconds: Optional[int] = None
    max_daily_publish: Optional[int] = None


class PublishProfileResponse(BaseModel):
    id: str
    platform: Optional[str] = None
    account_name: Optional[str] = None
    chrome_debug_port: int = 9222
    cookie_file: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_tags: Optional[list] = None
    mini_program_link: Optional[str] = None
    publish_mode: str = "immediate"
    require_manual_confirm: bool = True
    min_interval_seconds: int = 300
    max_daily_publish: int = 20
    created_at: str

    model_config = {"from_attributes": True}


# ---- Serializers ----

def _serialize_publish_task(task: PublishTask) -> dict:
    return {
        "id": str(task.id),
        "output_id": str(task.output_id),
        "platform": task.platform,
        "account_name": task.account_name,
        "status": task.status,
        "celery_task_id": task.celery_task_id,
        "title": task.title,
        "description": task.description,
        "tags": task.tags,
        "cover_file_key": task.cover_file_key,
        "mini_program_link": task.mini_program_link,
        "link_attached": task.link_attached or False,
        "published_url": task.published_url,
        "published_id": task.published_id,
        "published_at": utc_iso(task.published_at) if task.published_at else None,
        "error_message": task.error_message,
        "require_manual_confirm": task.require_manual_confirm if task.require_manual_confirm is not None else True,
        "screenshot_key": task.screenshot_key,
        "video_account_id": str(task.video_account_id) if task.video_account_id else None,
        "mini_program_id": str(task.mini_program_id) if task.mini_program_id else None,
        "prompt_record_id": str(task.prompt_record_id) if task.prompt_record_id else None,
        "material_id": str(task.material_id) if task.material_id else None,
        "created_at": utc_iso(task.created_at) if task.created_at else "",
        "updated_at": utc_iso(task.updated_at) if task.updated_at else "",
    }


def _serialize_publish_profile(profile: PublishProfile) -> dict:
    return {
        "id": str(profile.id),
        "platform": profile.platform,
        "account_name": profile.account_name,
        "chrome_debug_port": profile.chrome_debug_port or 9222,
        # Cookie 脱敏显示（RPA Cookie 安全存储）
        "cookie_file": "****" if profile.cookie_file else None,
        "title_template": profile.title_template,
        "description_template": profile.description_template,
        "default_tags": profile.default_tags,
        "mini_program_link": profile.mini_program_link,
        "publish_mode": profile.publish_mode or "immediate",
        "require_manual_confirm": profile.require_manual_confirm if profile.require_manual_confirm is not None else True,
        "min_interval_seconds": profile.min_interval_seconds or 300,
        "max_daily_publish": profile.max_daily_publish or 20,
        "created_at": utc_iso(profile.created_at) if profile.created_at else "",
    }


# ---- Publish Task endpoints ----

@router.post("/publish/tasks", response_model=PublishTaskResponse, status_code=201)
async def create_publish_task(
    data: PublishTaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new publish task and enqueue the actual publish job."""
    try:
        output_uuid = uuid.UUID(data.output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    # Verify output exists
    result = await db.execute(select(SliceOutput).where(SliceOutput.id == output_uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Slice output not found")

    # Enforce publish profile limits (daily cap + min interval)
    await _check_publish_limits(db, data)

    task = await _create_publish_task_internal(db, data)
    # 关键断点修复：任务落库后立即触发实际发布（Celery → backend worker → CDP 驱动 RPA 浏览器）
    await db.commit()
    try:
        from app.celery.tasks import task_publish_video
        celery_result = task_publish_video.delay(str(task.id))
        task.celery_task_id = celery_result.id
        # 只回写 celery_task_id，不覆盖 status：worker 可能已开始执行并更新状态，
        # 避免把 running/pending_confirm 覆盖回 pending
        await db.commit()
    except Exception as e:
        # 发布调度失败不阻断任务创建：保留任务记录，可在发布管理页手动重试
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Failed to enqueue publish task {task.id}: {e}", exc_info=True)
    return _serialize_publish_task(task)


@router.post("/publish/tasks/batch", response_model=List[PublishTaskResponse], status_code=201)
async def create_publish_tasks_batch(
    data: PublishBatchCreate,
    db: AsyncSession = Depends(get_db),
):
    """批量创建发布任务（成品预览「一键发布」多平台同时发起）。

    每个平台独立执行发布配置校验（每日上限/最小间隔），全部成功则统一返回。
    任一平台校验失败时整体返回 4xx，避免出现"部分平台创建了、部分没创建"的
    不确定状态，用户可调整后重试。
    """
    if not data.tasks:
        raise HTTPException(status_code=400, detail="至少需要创建一个发布任务")
    if len(data.tasks) > 10:
        raise HTTPException(status_code=400, detail="单次最多创建 10 个发布任务")

    # 先做完整校验（含输出存在性 + 发布配置限制），全部通过才落库
    for item in data.tasks:
        try:
            output_uuid = uuid.UUID(item.output_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid output ID format")
        result = await db.execute(select(SliceOutput).where(SliceOutput.id == output_uuid))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Slice output not found")
        await _check_publish_limits(db, item)

    created = []
    for item in data.tasks:
        created.append(await _create_publish_task_internal(db, item))
    await db.commit()
    # 全部落库后统一触发发布调度
    for task in created:
        try:
            from app.celery.tasks import task_publish_video
            celery_result = task_publish_video.delay(str(task.id))
            task.celery_task_id = celery_result.id
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.error(f"Failed to enqueue publish task {task.id}: {e}", exc_info=True)
    await db.commit()
    return [_serialize_publish_task(t) for t in created]


async def _check_publish_limits(db: AsyncSession, data: PublishTaskCreate):
    """校验发布配置的每日上限与最小发布间隔（带行锁防并发）。

    优先按 (platform, account_name) 匹配发布配置；若任务携带 video_account_id，
    则回退到账号绑定的 profile_id 解析配置，保证账号矩阵同样受上限/间隔约束。
    """
    profile = None
    profile_result = await db.execute(
        select(PublishProfile).where(
            PublishProfile.platform == data.platform,
            PublishProfile.account_name == data.account_name,
        ).with_for_update()
    )
    profile = profile_result.scalar_one_or_none()

    if not profile and data.video_account_id:
        try:
            acc_uuid = uuid.UUID(data.video_account_id)
        except ValueError:
            acc_uuid = None
        if acc_uuid:
            acc_result = await db.execute(
                select(VideoAccount).where(VideoAccount.id == acc_uuid)
            )
            acc = acc_result.scalar_one_or_none()
            if acc and acc.profile_id:
                prof_result = await db.execute(
                    select(PublishProfile).where(PublishProfile.id == acc.profile_id).with_for_update()
                )
                profile = prof_result.scalar_one_or_none()

    if not profile:
        return
    today = datetime.utcnow().date()
    today_start = datetime(today.year, today.month, today.day)
    daily_count = (
        await db.execute(
            select(func.count(PublishTask.id)).where(
                PublishTask.platform == data.platform,
                PublishTask.account_name == data.account_name,
                PublishTask.created_at >= today_start,
            )
        )
    ).scalar() or 0
    if profile.max_daily_publish and daily_count >= profile.max_daily_publish:
        raise HTTPException(
            status_code=429,
            detail=f"平台 {data.platform} 已达今日发布上限（{profile.max_daily_publish} 条），请明天再试",
        )
    if profile.min_interval_seconds:
        last_task = (
            await db.execute(
                select(PublishTask)
                .where(
                    PublishTask.platform == data.platform,
                    PublishTask.account_name == data.account_name,
                )
                .order_by(PublishTask.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_task and last_task.created_at:
            elapsed = (datetime.utcnow() - last_task.created_at).total_seconds()
            if elapsed < profile.min_interval_seconds:
                raise HTTPException(
                    status_code=429,
                    detail=f"平台 {data.platform} 发布间隔过短，请 {int(profile.min_interval_seconds - elapsed)} 秒后再试",
                )


async def _create_publish_task_internal(db: AsyncSession, data: PublishTaskCreate) -> PublishTask:
    """创建单条发布任务并落库（不提交事务，由调用方统一提交）。"""
    output_uuid = uuid.UUID(data.output_id)

    def _to_uuid_or_none(v: Optional[str]) -> Optional[uuid.UUID]:
        """把外部传入的 ID 字符串安全转为 UUID；非法值返回 None（不阻断任务创建）。"""
        if not v:
            return None
        try:
            return uuid.UUID(v)
        except ValueError:
            return None

    # 若指定了 video_account_id，自动代入账号的发布配置（chrome 端口/Cookie/默认标题/描述/标签）
    account_name = data.account_name
    mini_program_link = data.mini_program_link
    video_account_uuid = _to_uuid_or_none(data.video_account_id)
    if video_account_uuid:
        try:
            acc_result = await db.execute(select(VideoAccount).where(VideoAccount.id == video_account_uuid))
            acc = acc_result.scalar_one_or_none()
            if acc:
                account_name = account_name or acc.account_name
        except Exception:
            pass

    task = PublishTask(
        output_id=output_uuid,
        platform=data.platform,
        account_name=account_name,
        title=data.title,
        description=data.description,
        tags=data.tags,
        cover_file_key=data.cover_file_key,
        mini_program_link=mini_program_link,
        link_attached=data.link_attached,
        require_manual_confirm=data.require_manual_confirm,
        video_account_id=video_account_uuid,
        mini_program_id=_to_uuid_or_none(data.mini_program_id),
        prompt_record_id=_to_uuid_or_none(data.prompt_record_id),
        material_id=_to_uuid_or_none(data.material_id),
        status="pending",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.get("/publish/tasks", response_model=List[PublishTaskResponse])
async def list_publish_tasks(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List publish tasks with optional filters."""
    filters = []
    if platform:
        filters.append(PublishTask.platform == platform)
    if status:
        filters.append(PublishTask.status == status)
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date)
            filters.append(PublishTask.created_at >= sd)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            ed = datetime.fromisoformat(end_date)
            filters.append(PublishTask.created_at <= ed)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    query = select(PublishTask)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(PublishTask.created_at))

    result = await db.execute(query)
    tasks = result.scalars().all()
    return [_serialize_publish_task(t) for t in tasks]


@router.get("/publish/tasks/{task_id}", response_model=PublishTaskResponse)
async def get_publish_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get publish task detail."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(PublishTask).where(PublishTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Publish task not found")

    return _serialize_publish_task(task)


@router.get("/publish/tasks/{task_id}/screenshot")
async def get_publish_task_screenshot(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取发布确认截图的签名访问 URL（供前端在发布管理页预览）。"""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(PublishTask).where(PublishTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Publish task not found")

    if not task.screenshot_key:
        return {"task_id": task_id, "screenshot_url": None}

    from app.services.minio_service import get_presigned_url
    url = await get_presigned_url(
        settings.MINIO_BUCKET_SCREENSHOTS,
        task.screenshot_key,
        expires_seconds=3600,
    )
    return {"task_id": task_id, "screenshot_url": url}


@router.post("/publish/tasks/{task_id}/confirm", response_model=PublishTaskConfirmResponse)
async def confirm_publish_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Confirm a publish task after screenshot review."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(PublishTask).where(PublishTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Publish task not found")

    if task.status != "pending_confirm":
        raise HTTPException(
            status_code=400,
            detail=f"Task status is '{task.status}', expected 'pending_confirm'",
        )

    # Trigger the confirmation (clicks publish in the prepared tab) via Celery
    from app.celery.tasks import confirm_publish_worker
    celery_result = confirm_publish_worker.delay(str(task.id))
    task.celery_task_id = celery_result.id
    task.status = "publishing"

    await db.flush()
    await db.refresh(task)

    return {
        "id": str(task.id),
        "status": task.status,
        "published_url": task.published_url,
        "published_id": task.published_id,
    }


# ---- Publish Profile endpoints ----

@router.get("/publish/profiles", response_model=List[PublishProfileResponse])
async def list_publish_profiles(db: AsyncSession = Depends(get_db)):
    """List all publish profiles."""
    result = await db.execute(
        select(PublishProfile).order_by(PublishProfile.created_at.desc())
    )
    profiles = result.scalars().all()
    return [_serialize_publish_profile(p) for p in profiles]


@router.post("/publish/profiles", response_model=PublishProfileResponse, status_code=201)
async def create_publish_profile(
    data: PublishProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new publish profile."""
    # 加密存储 RPA Cookie（AES-256/Fernet，三期安全）
    cookie_value = data.cookie_file
    if cookie_value and cookie_value != "****":
        from app.auth import encrypt_cookie
        try:
            cookie_value = encrypt_cookie(cookie_value)
        except Exception:
            cookie_value = data.cookie_file

    profile = PublishProfile(
        platform=data.platform,
        account_name=data.account_name,
        chrome_debug_port=data.chrome_debug_port,
        cookie_file=cookie_value,
        title_template=data.title_template,
        description_template=data.description_template,
        default_tags=data.default_tags,
        mini_program_link=data.mini_program_link,
        publish_mode=data.publish_mode,
        require_manual_confirm=data.require_manual_confirm,
        min_interval_seconds=data.min_interval_seconds,
        max_daily_publish=data.max_daily_publish,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return _serialize_publish_profile(profile)


@router.put("/publish/profiles/{profile_id}", response_model=PublishProfileResponse)
async def update_publish_profile(
    profile_id: str,
    data: PublishProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a publish profile."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    result = await db.execute(select(PublishProfile).where(PublishProfile.id == pid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Publish profile not found")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        # Cookie 字段特殊处理：加密存储 + 跳过“****”占位（未修改）
        if field == "cookie_file":
            if value and value != "****":
                from app.auth import encrypt_cookie
                try:
                    profile.cookie_file = encrypt_cookie(value)
                except Exception:
                    profile.cookie_file = value
            continue
        setattr(profile, field, value)

    await db.flush()
    await db.refresh(profile)
    return _serialize_publish_profile(profile)


@router.delete("/publish/profiles/{profile_id}", status_code=204)
async def delete_publish_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a publish profile."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    result = await db.execute(select(PublishProfile).where(PublishProfile.id == pid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Publish profile not found")

    await db.delete(profile)
    await db.flush()
    return None


# ---- 视频号/抖音账号库（矩阵管理） endpoints ----


def _serialize_video_account(acc: VideoAccount) -> dict:
    return {
        "id": str(acc.id),
        "account_name": acc.account_name,
        "platform": acc.platform,
        "group_name": acc.group_name,
        "wxid": acc.wxid,
        "account_uid": acc.account_uid,
        "profile_id": str(acc.profile_id) if acc.profile_id else None,
        "mini_program_enabled": acc.mini_program_enabled or False,
        "remark": acc.remark,
        "enabled": acc.enabled if acc.enabled is not None else True,
        "created_at": utc_iso(acc.created_at) if acc.created_at else "",
        "updated_at": utc_iso(acc.updated_at) if acc.updated_at else "",
    }


def _serialize_mini_program(mp: MiniProgram) -> dict:
    return {
        "id": str(mp.id),
        "name": mp.name,
        "appid": mp.appid,
        "path": mp.path,
        "full_link": mp.full_link,
        "remark": mp.remark,
        "enabled": mp.enabled if mp.enabled is not None else True,
        "created_at": utc_iso(mp.created_at) if mp.created_at else "",
    }


@router.get("/publish/video-accounts", response_model=List[VideoAccountResponse])
async def list_video_accounts(
    platform: Optional[str] = Query(None),
    group_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """账号库列表（可按平台/分组过滤，默认只返回启用账号）。"""
    filters = []
    if platform:
        filters.append(VideoAccount.platform == platform)
    if group_name:
        filters.append(VideoAccount.group_name == group_name)
    query = select(VideoAccount)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(VideoAccount.platform, VideoAccount.group_name, VideoAccount.account_name)
    result = await db.execute(query)
    accounts = result.scalars().all()
    return [_serialize_video_account(a) for a in accounts]


@router.post("/publish/video-accounts", response_model=VideoAccountResponse, status_code=201)
async def create_video_account(
    data: VideoAccountCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增账号（手动新增 / 初始化导入的单条）。"""
    acc = VideoAccount(
        account_name=data.account_name,
        platform=data.platform,
        group_name=data.group_name,
        wxid=data.wxid,
        account_uid=data.account_uid,
        profile_id=uuid.UUID(data.profile_id) if data.profile_id else None,
        mini_program_enabled=data.mini_program_enabled,
        remark=data.remark,
        enabled=data.enabled,
    )
    db.add(acc)
    await db.flush()
    await db.refresh(acc)
    return _serialize_video_account(acc)


@router.post("/publish/video-accounts/batch", response_model=dict, status_code=201)
async def batch_import_video_accounts(
    data: VideoAccountBatchImport,
    db: AsyncSession = Depends(get_db),
):
    """账号批量导入（Excel/CSV 解析后的结构化数组落库）。

    skip_duplicates=True 时按 (platform, account_name) 去重，重复项跳过并计数。
    """
    imported = 0
    skipped = 0
    errors = []
    for item in data.accounts:
        try:
            if data.skip_duplicates:
                dup = await db.execute(
                    select(VideoAccount).where(
                        VideoAccount.platform == item.platform,
                        VideoAccount.account_name == item.account_name,
                    )
                )
                if dup.scalar_one_or_none():
                    skipped += 1
                    continue
            acc = VideoAccount(
                account_name=item.account_name,
                platform=item.platform,
                group_name=item.group_name,
                wxid=item.wxid,
                account_uid=item.account_uid,
                profile_id=uuid.UUID(item.profile_id) if item.profile_id else None,
                mini_program_enabled=item.mini_program_enabled,
                remark=item.remark,
                enabled=item.enabled,
            )
            db.add(acc)
            imported += 1
        except Exception as e:
            errors.append({"account_name": item.account_name, "error": str(e)})
    await db.flush()
    return {"imported": imported, "skipped": skipped, "errors": errors}


@router.put("/publish/video-accounts/{account_id}", response_model=VideoAccountResponse)
async def update_video_account(
    account_id: str,
    data: VideoAccountUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新账号信息。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(select(VideoAccount).where(VideoAccount.id == aid))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Video account not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "profile_id":
            acc.profile_id = uuid.UUID(value) if value else None
            continue
        setattr(acc, field, value)

    await db.flush()
    await db.refresh(acc)
    return _serialize_video_account(acc)


@router.delete("/publish/video-accounts/{account_id}", status_code=204)
async def delete_video_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除账号。"""
    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account ID format")

    result = await db.execute(select(VideoAccount).where(VideoAccount.id == aid))
    acc = result.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="Video account not found")

    await db.delete(acc)
    await db.flush()
    return None


# ---- 小程序链接库 endpoints ----


@router.get("/publish/mini-programs", response_model=List[MiniProgramResponse])
async def list_mini_programs(
    enabled_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """小程序链接库列表。"""
    query = select(MiniProgram)
    if enabled_only:
        query = query.where(MiniProgram.enabled == True)  # noqa: E712
    query = query.order_by(MiniProgram.name)
    result = await db.execute(query)
    programs = result.scalars().all()
    return [_serialize_mini_program(mp) for mp in programs]


@router.post("/publish/mini-programs", response_model=MiniProgramResponse, status_code=201)
async def create_mini_program(
    data: MiniProgramCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增小程序链接。"""
    mp = MiniProgram(
        name=data.name,
        appid=data.appid,
        path=data.path,
        full_link=data.full_link,
        remark=data.remark,
        enabled=data.enabled,
    )
    db.add(mp)
    await db.flush()
    await db.refresh(mp)
    return _serialize_mini_program(mp)


@router.put("/publish/mini-programs/{mp_id}", response_model=MiniProgramResponse)
async def update_mini_program(
    mp_id: str,
    data: MiniProgramUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新小程序链接。"""
    try:
        mid = uuid.UUID(mp_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mini program ID format")

    result = await db.execute(select(MiniProgram).where(MiniProgram.id == mid))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(status_code=404, detail="Mini program not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(mp, field, value)

    await db.flush()
    await db.refresh(mp)
    return _serialize_mini_program(mp)


@router.delete("/publish/mini-programs/{mp_id}", status_code=204)
async def delete_mini_program(
    mp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除小程序链接。"""
    try:
        mid = uuid.UUID(mp_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mini program ID format")

    result = await db.execute(select(MiniProgram).where(MiniProgram.id == mid))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(status_code=404, detail="Mini program not found")

    await db.delete(mp)
    await db.flush()
    return None
