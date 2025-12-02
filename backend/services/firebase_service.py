import firebase_admin
from firebase_admin import credentials, firestore
import os
import logging
from core.config import settings

# 로깅 설정
logger = logging.getLogger(__name__)

class FirebaseService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseService, cls).__new__(cls)
            cls._instance.db = None
            cls._instance.is_connected = False
            cls._instance.error_msg = None
            cls._instance.initialize()
        return cls._instance

    def initialize(self):
        try:
            if not os.path.exists(settings.FIREBASE_CRED_PATH):
                raise FileNotFoundError(f"Key file not found at: {settings.FIREBASE_CRED_PATH}")

            if not firebase_admin._apps:
                cred = credentials.Certificate(settings.FIREBASE_CRED_PATH)
                firebase_admin.initialize_app(cred)
            
            self.db = firestore.client()
            # 연결 테스트 (가벼운 쿼리)
            # self.db.collection('test').limit(1).get() 
            self.is_connected = True
            logger.info("Firebase Connected Successfully")
            
        except Exception as e:
            self.is_connected = False
            self.error_msg = str(e)
            logger.warning(f"Firebase Init Failed: {e}")

    def get_db(self):
        if not self.is_connected:
            # 재시도 로직
            self.initialize()
        return self.db

    def check_health(self):
        return {
            "status": "ok" if self.is_connected else "error",
            "message": "Connected" if self.is_connected else self.error_msg
        }

firebase_manager = FirebaseService()