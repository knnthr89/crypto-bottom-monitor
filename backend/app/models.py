from pydantic import BaseModel
from typing import Optional, Dict, List

class Indicator(BaseModel):
    key: str
    label: str
    score: Optional[float] = None
    maximum: float
    status: str
    detail: str

class AssetSnapshot(BaseModel):
    asset: str
    symbol: str
    price_usd: Optional[float]
    score: Optional[float]
    label: str
    confirmed_bottom: bool
    data_mode: str
    as_of: str
    indicators: List[Indicator]
    caveats: List[str]
