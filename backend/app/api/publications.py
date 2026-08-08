import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.models import SliceOutput, SliceTask, Episode, Publication, User
from app.services.data_scope import check_project_access_by_episode

router = APIRouter()


class PublicationCreate(BaseModel):
    platform: str
    publish_url: Optional[str] = None
    publish_time: Optional[str] = None
    status: str = "pending"
    reject_reason: Optional[str] = None
    operator: Optional[str] = None


class PublicationUpdate(BaseModel):
    platform: Optional[str] = None
    publish_url: Optional[str] = None
    publish_time: Optional[str] = None
    status: Optional[str] = None
    reject_reason: Optional[str] = None
    operator: Optional[str] = None


class PublicationResponse(BaseModel):
    id: str
    output_id: str
    platform: Optional[str] = None
    publish_url: Optional[str] = None
    publish_time: Optional[str] = None
    status: Optional[str] = None
    reject_reason: Optional[str] = None
    operator: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


def _serialize_publication(pub: Publication) -> dict:
    return {
        "id": str(pub.id),
        "output_id": str(pub.output_id),
        "platform": pub.platform,
        "publish_url": pub.publish_url,
        "publish_time": pub.publish_time.isoformat() if pub.publish_time else None,
        "status": pub.status,
        "reject_reason": pub.reject_reason,
        "operator": pub.operator,
        "created_at": pub.created_at.isoformat() if pub.created_at else "",
    }


async def _check_output_scope(db: AsyncSession, output: SliceOutput, current_user: User):
    """数据隔离：根据输出文件所属切片任务 → 剧集 → 项目校验访问权限."""
    if current_user is None:
        raise HTTPException(status_code=404, detail="Output not found")
    task = (
        await db.execute(select(SliceTask).where(SliceTask.id == output.task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Output not found")
    episode = (
        await db.execute(select(Episode).where(Episode.id == task.episode_id))
    ).scalar_one_or_none()
    if episode:
        await check_project_access_by_episode(db, episode, current_user)


@router.get("/outputs/{output_id}/publications", response_model=List[PublicationResponse])
async def list_publications(
    output_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get all publication records for a slice output（数据隔离）. """
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    # Verify output exists
    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    # 数据隔离
    await _check_output_scope(db, output, current_user)

    pubs_result = await db.execute(
        select(Publication)
        .where(Publication.output_id == oid)
        .order_by(Publication.created_at.desc())
    )
    publications = pubs_result.scalars().all()
    return [_serialize_publication(p) for p in publications]


@router.post("/outputs/{output_id}/publications", response_model=PublicationResponse, status_code=201)
async def create_publication(
    output_id: str,
    data: PublicationCreate,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Add a publication record for a slice output（数据隔离）. """
    try:
        oid = uuid.UUID(output_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid output ID format")

    # Verify output exists
    result = await db.execute(select(SliceOutput).where(SliceOutput.id == oid))
    output = result.scalar_one_or_none()
    if not output:
        raise HTTPException(status_code=404, detail="Output not found")

    # 数据隔离
    await _check_output_scope(db, output, current_user)

    pub = Publication(
        output_id=oid,
        platform=data.platform,
        publish_url=data.publish_url,
        status=data.status,
        reject_reason=data.reject_reason,
        operator=data.operator,
    )
    if data.publish_time:
        try:
            pub.publish_time = datetime.fromisoformat(data.publish_time)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid publish_time format. Use ISO 8601 (e.g., 2026-08-04T10:00:00)",
            )

    db.add(pub)
    await db.flush()
    await db.refresh(pub)
    return _serialize_publication(pub)


@router.put("/publications/{publication_id}", response_model=PublicationResponse)
async def update_publication(
    publication_id: str,
    data: PublicationUpdate,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update a publication record（数据隔离）. """
    try:
        pid = uuid.UUID(publication_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid publication ID format")

    result = await db.execute(select(Publication).where(Publication.id == pid))
    pub = result.scalar_one_or_none()
    if not pub:
        raise HTTPException(status_code=404, detail="Publication not found")

    # 数据隔离
    output = (
        await db.execute(select(SliceOutput).where(SliceOutput.id == pub.output_id))
    ).scalar_one_or_none()
    if output:
        await _check_output_scope(db, output, current_user)

    if data.platform is not None:
        pub.platform = data.platform
    if data.publish_url is not None:
        pub.publish_url = data.publish_url
    if data.publish_time is not None:
        try:
            pub.publish_time = datetime.fromisoformat(data.publish_time)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid publish_time format. Use ISO 8601",
            )
    if data.status is not None:
        if data.status not in ("published", "rejected", "pending"):
            raise HTTPException(
                status_code=400,
                detail="Status must be one of: published, rejected, pending",
            )
        pub.status = data.status
    if data.reject_reason is not None:
        pub.reject_reason = data.reject_reason
    if data.operator is not None:
        pub.operator = data.operator

    await db.flush()
    await db.refresh(pub)
    return _serialize_publication(pub)