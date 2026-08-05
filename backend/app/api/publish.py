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
from app.models.models import PublishTask, PublishProfile, SliceOutput

router = APIRouter()


# ---- Pydantic schemas ----

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
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class PublishTaskConfirmResponse(BaseModel):
    id: str
    status: str
    published_url: Optional[str] = None
    published_id: Optional[str] = None


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
        "published_at": task.published_at.isoformat() if task.published_at else None,
        "error_message": task.error_message,
        "require_manual_confirm": task.require_manual_confirm if task.require_manual_confirm is not None else True,
        "screenshot_key": task.screenshot_key,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }


def _serialize_publish_profile(profile: PublishProfile) -> dict:
    return {
        "id": str(profile.id),
        "platform": profile.platform,
        "account_name": profile.account_name,
        "chrome_debug_port": profile.chrome_debug_port or 9222,
        "cookie_file": profile.cookie_file,
        "title_template": profile.title_template,
        "description_template": profile.description_template,
        "default_tags": profile.default_tags,
        "mini_program_link": profile.mini_program_link,
        "publish_mode": profile.publish_mode or "immediate",
        "require_manual_confirm": profile.require_manual_confirm if profile.require_manual_confirm is not None else True,
        "min_interval_seconds": profile.min_interval_seconds or 300,
        "max_daily_publish": profile.max_daily_publish or 20,
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
    }


# ---- Publish Task endpoints ----

@router.post("/publish/tasks", response_model=PublishTaskResponse, status_code=201)
async def create_publish_task(
    data: PublishTaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new publish task."""
    try:
        output_uuid = uuid.UUID(data.output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    # Verify output exists
    result = await db.execute(select(SliceOutput).where(SliceOutput.id == output_uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Slice output not found")

    # Enforce publish profile limits (daily cap + min interval)
    profile_result = await db.execute(
        select(PublishProfile).where(
            PublishProfile.platform == data.platform,
            PublishProfile.account_name == data.account_name,
        )
    )
    profile = profile_result.scalar_one_or_none()
    if profile:
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
                detail=f"已达今日发布上限（{profile.max_daily_publish} 条），请明天再试",
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
                        detail=f"发布间隔过短，请 {int(profile.min_interval_seconds - elapsed)} 秒后再试",
                    )

    task = PublishTask(
        output_id=output_uuid,
        platform=data.platform,
        account_name=data.account_name,
        title=data.title,
        description=data.description,
        tags=data.tags,
        cover_file_key=data.cover_file_key,
        mini_program_link=data.mini_program_link,
        link_attached=data.link_attached,
        require_manual_confirm=data.require_manual_confirm,
        status="pending",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return _serialize_publish_task(task)


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
    profile = PublishProfile(
        platform=data.platform,
        account_name=data.account_name,
        chrome_debug_port=data.chrome_debug_port,
        cookie_file=data.cookie_file,
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
