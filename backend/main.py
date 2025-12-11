import uvicorn
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Config & Services
from core.config import settings
from routers import mmd, emd, admin
from services.data_loader import data_loader

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 수명주기 관리 - 시작 시 CSV 데이터를 메모리에 로드"""
    logger.info("Server starting up...")
    data_loader.load_csv_to_memory()
    yield
    logger.info("Server shutting down...")


app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mmd.router)
app.include_router(emd.router)
app.include_router(admin.router)

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(settings.OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

# Static Files
if os.path.exists(os.path.join(settings.FRONTEND_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(settings.FRONTEND_DIR, "assets")), name="assets")
if os.path.exists(settings.DATA_DIR):
    app.mount("/data", StaticFiles(directory=settings.DATA_DIR), name="data")
if os.path.exists(settings.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=settings.FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)