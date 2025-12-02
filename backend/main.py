import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Config & Services
from core.config import settings
from routers import mmd, emd, admin
from services.data_loader import data_loader

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

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

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 CSV 데이터를 메모리에 로드 (Fallback용)"""
    data_loader.load_csv_to_memory()

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(settings.OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

# Static Files
if os.path.exists(os.path.join(settings.FRONTEND_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(settings.FRONTEND_DIR, "assets")), name="assets")
if os.path.exists(settings.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=settings.FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)