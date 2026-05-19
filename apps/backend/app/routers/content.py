"""Content module — YouTube/blog/Reddit ingestion + curated feed."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/feed")
def feed(topic: str = "food", db: Session = Depends(get_db)):
    """Personalized feed of curated + AI-generated content for the household."""
    return {"items": [], "topic": topic, "todo": "Wire to ContentItem ranked by relevance"}


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return {"sources": [], "todo": "Wire to ContentSource"}


@router.post("/sources")
def add_source(db: Session = Depends(get_db)):
    return {"source": None, "todo": "Persist new YouTube channel / RSS feed / subreddit"}


@router.post("/ingest/run")
def run_ingestion(db: Session = Depends(get_db)):
    """Manual trigger for an ingestion job. Production: run on a schedule."""
    return {"job_id": None, "todo": "Dispatch to services.youtube/reddit/blog_importer"}


@router.post("/bookmark/{item_id}")
def bookmark(item_id: str, db: Session = Depends(get_db)):
    return {"bookmarked": True, "item_id": item_id, "todo": "Persist ContentBookmark"}
