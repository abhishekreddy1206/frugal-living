from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import ai, content, food, health, tracking

app = FastAPI(title="Frugal Living API", version="0.1.0")

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

# Future tiers:
# app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])
# app.include_router(community.router, prefix="/api/v1/community", tags=["community"])


@app.get("/")
def root():
    return {
        "name": "frugal-living",
        "version": "0.1.0",
        "tier_a": True,
        "modules": ["food", "content", "ai", "tracking"],
    }
