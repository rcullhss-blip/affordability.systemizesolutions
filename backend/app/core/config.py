from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-key"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "eu-west-2"
    S3_BUCKET_RAW: str = "systemize-raw-reports"
    S3_BUCKET_OUTPUTS: str = "systemize-outputs"
    ANTHROPIC_API_KEY: str = ""
    ENVIRONMENT: str = "development"
    LOCAL_STORAGE_PATH: str = "/tmp/systemize-storage"

    @property
    def use_local_storage(self) -> bool:
        return not self.AWS_ACCESS_KEY_ID

    class Config:
        env_file = ".env"


settings = Settings()
