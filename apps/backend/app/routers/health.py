from fastapi import APIRouter
from sqlalchemy import text

from app.db import engine

router = APIRouter()


@router.get("/healthz")
def healthz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": "error", "error": str(e)}
