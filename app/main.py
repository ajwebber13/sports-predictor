from fastapi import FastAPI
from app.api.routes_predict import router as predict_router
from app.api.routes_slate import router as slate_router
from app.api.routes_edges import router as edges_router
from app.api.routes_wnba import router as wnba_router

app = FastAPI(
    title="Sports Betting Model API",
    version="1.0"
)

app.include_router(predict_router, prefix="/predict", tags=["Predict"])
app.include_router(slate_router, prefix="/slate", tags=["Slate"])
app.include_router(edges_router, prefix="/edges", tags=["Edges"])
app.include_router(wnba_router, tags=["WNBA"])

@app.get("/")
def root():
    return {"status": "running"}