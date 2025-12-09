import os
import json
from dotenv import load_dotenv

# [수정됨] backend/core/config.py 위치에서 3단계 올라가야 루트(PO-SYSTEM)입니다.
# 1. core 폴더
# 2. backend 폴더
# 3. PO-SYSTEM (루트)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env 파일 로드
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Settings:
    PROJECT_NAME: str = "POReviewSystem"
    VERSION: str = "3.5.0"
    
    # 루트 경로 저장
    BASE_DIR = BASE_DIR
    
    # 키 파일 (루트에 있는 파일 참조)
    FIREBASE_CRED_PATH = os.path.join(BASE_DIR, os.getenv("FIREBASE_CRED_PATH", "serviceAccountKey.json"))
    
    # 나머지 폴더들 (루트 기준)
    TEMP_DIR = os.path.join(BASE_DIR, os.getenv("TEMP_DIR", "temp"))
    OUTPUT_DIR = os.path.join(BASE_DIR, os.getenv("OUTPUT_DIR", "outputs"))
    DATA_DIR = os.path.join(BASE_DIR, os.getenv("DATA_DIR", "data"))
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

    # 폴더 자동 생성
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def _load_system_config(self):
        """Load system configuration (e.g., safety stock) from data directory."""
        config_path = os.path.join(self.DATA_DIR, "system_config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    @property
    def SAFETY_STOCK(self) -> int:
        """Return configured safety stock with a safe default of 0."""
        config = self._load_system_config()
        try:
            return max(0, int(config.get("safety_stock", 0)))
        except (TypeError, ValueError):
            return 0

settings = Settings()
