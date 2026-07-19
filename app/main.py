import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import model_registry  # noqa: F401  (populates Base.metadata)
from app.core.config import settings
from app.core.database import Base, engine
from app.core.rate_limit import RateLimitMiddleware
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.banners.router import router as banners_router
from app.modules.bookings.router import router as bookings_router
from app.modules.facilities.router import router as facilities_router
from app.modules.favorites.router import router as favorites_router
from app.modules.notifications.router import router as notifications_router
from app.modules.queue.router import router as queue_router
from app.modules.rewards.router import router as rewards_router
from app.modules.reviews.router import router as reviews_router
from app.modules.settlements.router import router as settlements_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.app_name,
    description="Doctor/pharmacy appointment booking platform — API backend",
    version="0.1.0",
)

# CORS: wide open for now (mobile apps + admin web dashboard during dev).
# Tighten allow_origins to the real admin panel domain before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)

app.include_router(auth_router)
app.include_router(facilities_router)
app.include_router(bookings_router)
app.include_router(queue_router)
app.include_router(rewards_router)
app.include_router(settlements_router)
app.include_router(admin_router)
app.include_router(banners_router)
app.include_router(reviews_router)
app.include_router(favorites_router)
app.include_router(notifications_router)


@app.on_event("startup")
async def on_startup():
    # Dev convenience only — creates tables if they don't exist. In
    # staging/production, use Alembic migrations (see /alembic) instead so
    # schema changes are tracked and reversible.
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


@app.get("/")
async def root():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@app.get("/health")
async def health():
    return {"status": "healthy"}
