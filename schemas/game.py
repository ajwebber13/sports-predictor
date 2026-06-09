from pydantic import BaseModel

class GameRequest(BaseModel):
    home: str
    away: str
    neutral_site: bool = False