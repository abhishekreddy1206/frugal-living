"""Tier A — food routes. Stubs; flesh out as MVP features land."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


# ---------- Pantry ----------

@router.get("/pantry")
def list_pantry(db: Session = Depends(get_db)):
    # TODO: filter by household_id from auth context
    return {"items": [], "todo": "Wire to PantryItem model"}


@router.post("/pantry/capture")
def capture_pantry(db: Session = Depends(get_db)):
    """Photo-to-pantry: takes an image, returns extracted items.
    Will call Claude vision with a structured-output prompt.
    """
    return {"items": [], "todo": "Wire to services.llm.extract_pantry_from_image"}


@router.post("/pantry/receipt")
def capture_receipt(db: Session = Depends(get_db)):
    """Receipt-to-pantry: parse a grocery receipt photo into pantry items + spend entry."""
    return {"receipt": None, "items": [], "todo": "Wire to services.llm.extract_receipt"}


@router.post("/pantry/barcode")
def capture_barcode(db: Session = Depends(get_db)):
    """Barcode scan: UPC -> ingredient lookup (Open Food Facts), then add to pantry."""
    return {"item": None, "todo": "Wire to Open Food Facts lookup"}


# ---------- Recipes ----------

@router.get("/recipes/stretch")
def stretch_recipes(db: Session = Depends(get_db)):
    """Given current pantry, suggest meals using what's about to expire."""
    return {"suggestions": [], "todo": "Wire to services.llm.stretch_recipes_for_pantry"}


# ---------- Meal planning ----------

@router.post("/meal-plans/generate")
def generate_meal_plan(db: Session = Depends(get_db)):
    """Generate a weekly meal plan optimized for pantry, budget, preferences."""
    return {"meal_plan": None, "todo": "Wire to services.llm.generate_weekly_plan"}


# ---------- Shopping ----------

@router.get("/shopping-list")
def get_shopping_list(db: Session = Depends(get_db)):
    return {"items": [], "todo": "Derive from active meal plan minus pantry"}


# ---------- Preservation ----------

@router.get("/preservation/methods")
def preservation_methods():
    """Static catalog of safe preservation methods per ingredient."""
    return {"methods": [], "todo": "Seed from USDA-aligned catalog"}


# ---------- Waste ----------

@router.post("/waste")
def log_waste(db: Session = Depends(get_db)):
    return {"event": None, "todo": "Wire to FoodWasteEvent + emit savings/streak update"}
