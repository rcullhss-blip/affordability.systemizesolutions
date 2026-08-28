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
    PROCLAIM_WEBHOOK_API_KEY: str = ""  # Set in env to secure the /webhook/bureau endpoints

    # ── IRL case intake (PCP platform -> us) ──────────────────────────────────
    # Inbound: the PCP platform authenticates its case POSTs with this key.
    # Set to the IRL_API_KEY value the Hub sends (sk_irlcase_*). Empty = auth off (dev).
    IRL_CASE_API_KEY: str = ""
    # Outbound: where we POST the assessment outcome back, and the key we send.
    PCP_OUTCOME_URL: str = ""       # e.g. https://api-production-ae9a.up.railway.app/api/v1/webhook/irl-outcome
    PCP_OUTCOME_API_KEY: str = ""   # X-API-Key we send (the Hub's IRL_INBOUND_API_KEY / sk_irlout_*)

    # ── Dashboard / portal sign-in (see app.core.auth) ────────────────────────
    # First-run bootstrap: creates this admin if the users table is empty.
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # ── Worker self-scaling on Render (see app.workers.autoscale) ────────────
    RENDER_API_KEY: str = ""                 # ops key; also used by scale_worker.py locally
    RENDER_WORKER_SERVICE_ID: str = ""       # defaults to Render's own RENDER_SERVICE_ID
    WORKER_AUTOSCALE: bool = False           # set "1" on the worker service to enable
    WORKER_AUTOSCALE_MAX: int = 6            # Postgres (100 conns) makes 8 the hard ceiling
    WORKER_AUTOSCALE_PER_INSTANCE: int = 1000  # queued tasks per instance before adding another
    WORKER_AUTOSCALE_IDLE_TICKS: int = 5     # consecutive empty-queue ticks (2 min each) before scaling to 1

    @property
    def use_local_storage(self) -> bool:
        return not self.AWS_ACCESS_KEY_ID

    class Config:
        env_file = ".env"
        extra = "ignore"   # ops-only keys in .env (e.g. RENDER_API_KEY) must not break startup


settings = Settings()
