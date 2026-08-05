from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 必填：必须通过 .env / 环境变量注入，缺失时启动即报错
    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/0"
    CHROME_DEBUG_PORT: int = 9222
    RPA_REQUIRE_MANUAL_CONFIRM: bool = True
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minio_admin"
    # 必填：必须通过 .env / 环境变量注入
    MINIO_SECRET_KEY: str
    
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
