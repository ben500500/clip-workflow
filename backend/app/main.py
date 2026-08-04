import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, close_db
from app.api import projects, upload, autoclip, intervals, slice, preview, publications, config as config_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for progress updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, task_id: str, websocket: WebSocket):
        if task_id in self.active_connections:
            self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_progress(self, task_id: str, progress: float, message: str = ""):
        if task_id not in self.active_connections:
            return
        data = json.dumps({"progress": progress, "message": message})
        for ws in self.active_connections[task_id]:
            try:
                await ws.send_text(data)
            except Exception:
                pass


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    logger.info("Starting up...")
    await init_db()
    logger.info("Database initialized.")
    yield
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database connections closed.")


app = FastAPI(
    title="Clip Workflow API",
    description="Short drama clip workflow backend service",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/progress/{task_id}")
async def websocket_progress(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task progress updates."""
    await manager.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)
    except Exception:
        manager.disconnect(task_id, websocket)


# Mount all API routers
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(autoclip.router, prefix="/api", tags=["AutoClip"])
app.include_router(intervals.router, prefix="/api", tags=["Intervals"])
app.include_router(slice.router, prefix="/api", tags=["Slice"])
app.include_router(preview.router, prefix="/api", tags=["Preview"])
app.include_router(publications.router, prefix="/api", tags=["Publications"])
app.include_router(config_api.router, prefix="/api", tags=["Config"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "clip-workflow-backend"}