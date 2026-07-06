from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.connection import Connection
from app.db.models.pipeline import Pipeline
from app.db.models.user import User

router = APIRouter(tags=["pipelines"])


class PipelineCreate(BaseModel):
    source_connection_id: UUID
    dest_connection_id: UUID
    name: str
    enabled: bool = True


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    source_connection_id: Optional[UUID] = None
    dest_connection_id: Optional[UUID] = None


def _serialize(p: Pipeline) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "source_connection_id": str(p.source_connection_id),
        "dest_connection_id": str(p.dest_connection_id),
        "name": p.name,
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


async def _get_own_connection(db: AsyncSession, user_id: UUID, conn_id: UUID) -> Connection:
    result = await db.execute(
        select(Connection).where(Connection.id == conn_id, Connection.user_id == user_id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection {conn_id} not found",
        )
    return conn


@router.get("")
async def list_pipelines(
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> list[dict]:
    result = await db.execute(select(Pipeline).where(Pipeline.user_id == user.id))
    return [_serialize(p) for p in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    body: PipelineCreate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    await _get_own_connection(db, user.id, body.source_connection_id)
    await _get_own_connection(db, user.id, body.dest_connection_id)

    pipeline = Pipeline(
        user_id=user.id,
        source_connection_id=body.source_connection_id,
        dest_connection_id=body.dest_connection_id,
        name=body.name,
        enabled=body.enabled,
    )
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return _serialize(pipeline)


@router.get("/{pipeline_id}")
async def get_pipeline(
    pipeline_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.user_id == user.id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return _serialize(pipeline)


@router.patch("/{pipeline_id}")
async def update_pipeline(
    pipeline_id: UUID,
    body: PipelineUpdate,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.user_id == user.id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")

    if body.source_connection_id is not None:
        await _get_own_connection(db, user.id, body.source_connection_id)
        pipeline.source_connection_id = body.source_connection_id
    if body.dest_connection_id is not None:
        await _get_own_connection(db, user.id, body.dest_connection_id)
        pipeline.dest_connection_id = body.dest_connection_id
    if body.name is not None:
        pipeline.name = body.name
    if body.enabled is not None:
        pipeline.enabled = body.enabled

    await db.commit()
    await db.refresh(pipeline)
    return _serialize(pipeline)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    pipeline_id: UUID,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> None:
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.user_id == user.id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    await db.delete(pipeline)
    await db.commit()


@router.post("/{pipeline_id}/sync")
async def trigger_pipeline_sync(
    pipeline_id: UUID,
    request: Request,
    user: User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.user_id == user.id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    if not pipeline.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pipeline is disabled")

    arq_pool = request.app.state.arq_pool
    if not arq_pool:
        return {"status": "error", "message": "Worker pool not available"}

    await arq_pool.enqueue_job("run_pipeline", str(pipeline_id), str(user.id))
    return {"status": "queued", "pipeline_id": str(pipeline_id)}
