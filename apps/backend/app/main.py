from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import seed_reference_data
from app.db import SessionLocal
from app.routers import ai, community, content, food, health, tracking


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        seed_reference_data(db)
        db.commit()
    yield


app = FastAPI(title="Frugal Living API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health
app.include_router(health.router)

# Tier A — food
app.include_router(food.router, prefix="/api/v1/food", tags=["food"])

# Cross-cutting modules (all tiers can use)
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
app.include_router(tracking.router, prefix="/api/v1/tracking", tags=["tracking"])

# Tier B — community
app.include_router(community.router, prefix="/api/v1/community", tags=["community"])

# Future tiers:
# app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])


@app.get("/")
def root():
    return {
        "name": "frugal-living",
        "version": "0.1.0",
        "tier_a": True,
        "modules": ["food", "community", "content", "ai", "tracking"],
    }
