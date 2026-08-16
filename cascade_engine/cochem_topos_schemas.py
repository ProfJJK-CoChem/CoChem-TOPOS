from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any

class GradientPayload(BaseModel):
    energy: float
    gradient: List[List[float]] = Field(default_factory=list)
    hessian: Optional[List[List[float]]] = None
    geom_block: Optional[str] = None
    scf_tole: Optional[float] = None
    mpqc_blocks: Optional[List[str]] = None

    @validator("gradient")
    def validate_gradient(cls, v):
        if not v:
            return v
        import numpy as np
        arr = np.array(v)
        if np.all(arr == 0.0):
            raise ValueError("Spoofing detected: Fake 0.0 gradients are strictly prohibited.")
        return v

class ToposState(BaseModel):
    geom_id: str
    final_status: str
    highest_tier: int
    final_geometry: str
