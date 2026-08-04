from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://clip_user:clip_secret_2026@localhost:5432/clip_workflow"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio_admin"
    MINIO_SECRET_KEY: str = "minio_secret_2026"
    MINIO_BUCKET_RAW: str = "raw-footage"
    MINIO_BUCKET_SLICED: str = "sliced"
    MINIO_BUCKET_PREVIEWS: str = "previews"
    MINIO_BUCKET_EXPORTS: str = "exports"
    MINIO_USE_SSL: bool = False

    # AutoClip
    AUTOCLIP_URL: str = "http://autoclip:8000/api/v1"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Upload
    UPLOAD_CHUNK_SIZE: int = 5 * 1024 * 1024  # 5MB
    UPLOAD_TEMP_DIR: str = "/tmp/uploads"

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8080
    DEBUG: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()