from fastapi import APIRouter

router = APIRouter()

@router.post("/")
def predict(home: str, away: str, neutral_site: bool = False):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from services.model_connector import get_model_edges
    return {"message": "Use /edges?sport=ncaaf for predictions", "home": home, "away": away}