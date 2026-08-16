"""publish API 子域：发布任务（Phase 1 上帝类拆分）。

从原「上帝类」api/publish.py 按子域拆分而来，URL 保持 `/publish/tasks...` 不变。
本模块负责发布任务 CRUD / 批量创建 / 截图 / 确认 / 死信重发。
"""
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import (
    PublishTask,
    PublishProfile,
    SliceOutput,
    VideoAccount,
    User,
)
from app.api.publish_common import _serialize_publish_task

router = APIRouter()


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
    batch_id: Optional[str] = None
    operator_id: Optional[str] = None
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


@router.post("/publish/tasks/{task_id}/requeue", response_model=dict)
async def requeue_publish_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """死信任务手动重发（方向② 批量发布体验：失败不再静默丢失，可回溯重发）。

    仅允许对 dead_letter=True 的失败任务重发；重发前清除死信标记与错误信息，
    置回 pending 并重新投递 publish 队列。
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID format")

    result = await db.execute(select(PublishTask).where(PublishTask.id == tid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Publish task not found")
    if not task.dead_letter:
        raise HTTPException(status_code=400, detail="仅死信任务可重发（该任务非死信状态）")

    # 重置死信标记与错误，置回 pending
    task.dead_letter = False
    task.dead_letter_reason = None
    task.error_message = None
    task.status = "pending"

    from app.celery.tasks import task_publish_video
    celery_result = task_publish_video.delay(str(task.id))
    task.celery_task_id = celery_result.id

    await db.flush()
    await db.refresh(task)

    return {
        "id": str(task.id),
        "status": task.status,
        "celery_task_id": task.celery_task_id,
        "message": "已清除死信标记并重新投递发布队列",
    }
