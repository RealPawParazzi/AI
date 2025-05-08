from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class GenerationRequest(BaseModel):
    prompt: str
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None  # 여러 이미지 URL을 위한 필드 추가
    output_type: str  # "video" or "gif"
    duration: Optional[int] = None
    additional_options: Optional[Dict[str, Any]] = None

class GenerationResponse(BaseModel):
    jobId: str
    status: str
    error: Optional[str] = None

class StatusResponse(BaseModel):
    jobId: str
    status: str
    resultUrl: Optional[str] = None
    error: Optional[str] = None

class BattleRequest(BaseModel):
    myPetName: str
    targetPetName: str
    myPetDetail: str
    targetPetDetail: str

class BattleResponse(BaseModel):
    result: str
    winner: str  # 승자의 이름 (myPetName 또는 targetPetName)

