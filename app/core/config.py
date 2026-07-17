"""
Central configuration. Every external dependency (DB, storage, notifications,
payments) is read from environment variables here — nothing else in the
codebase should read os.environ directly. This is what makes the whole app
swappable between Render/Supabase/Cloudinary today and AWS tomorrow: only
these values change, never the business logic that consumes them.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "EazyDoctor"
    environment: str = "development"
    port: int = 8000
    # Local timezone appointments are booked/expected in (IANA name — must
    # stay configurable since a future all-India rollout may need per-region
    # handling; never assume the server's own clock/timezone).
    app_timezone: str = "Asia/Kolkata"

    # Auth
    jwt_secret: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Database — provider-agnostic. Only this string changes on migration
    # (Supabase -> AWS RDS). No code elsewhere should know or care.
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/eazydoctor"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting (see app/core/rate_limit.py for the per-route rules)
    rate_limit_enabled: bool = True

    # Cache TTLs (seconds) — see app/services/cache_service.py
    cache_ttl_facility_search: int = 120
    cache_ttl_facility_profile: int = 300

    # Storage
    storage_provider: str = "cloudinary"  # cloudinary | s3 | r2 | local
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # Notifications
    firebase_credentials_json: str = ""
    firebase_database_url: str = ""

    # Email (Brevo) — used for OTP delivery (signup/login/forgot-password)
    # and all transactional notification emails. No SMS provider is used.
    brevo_api_key: str = ""
    brevo_sender_email: str = "no-reply@eazydoctor.app"
    brevo_sender_name: str = "EazyDoctor"

    # OTP
    otp_length: int = 6
    otp_expire_minutes: int = 10
    otp_resend_cooldown_seconds: int = 60

    # Payments
    payment_provider: str = "cash_only"  # cash_only | paytm
    paytm_merchant_id: str = ""
    paytm_merchant_key: str = ""
    paytm_website: str = "WEBSTAGING"
    paytm_callback_url: str = ""

    # Payouts
    paytm_payout_merchant_id: str = ""
    paytm_payout_key: str = ""

    # Business defaults (admin can override per-facility in DB; these are
    # just the fallback/global defaults used to seed new facilities)
    default_booking_fee: float = 10.0
    default_platform_commission_percent: float = 35.0
    default_cancellation_deduction_percent: float = 20.0
    cancellation_lock_hours: int = 5
    queue_stall_minutes: int = 15
    min_withdrawal_amount: float = 200.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
