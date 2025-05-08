from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import uvicorn
import os
from dotenv import load_dotenv
import time

from app.models import GenerationResponse, StatusResponse, BattleRequest, BattleResponse
from app.tasks import process_video_generation
from app.db import update_job_status, get_job_status, create_job
from app.services import download_image, generate_battle_result

# 환경 변수 로드
load_dotenv()

app = FastAPI(title="AI Video Generation API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 환경에서는 구체적인 origin 설정 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 모델 정의
class GenerationRequestAPI(BaseModel):
    jobId: str
    prompt: str
    imageUrl: Optional[str] = None
    imageUrls: Optional[List[str]] = None  # 여러 이미지 URL 필드 추가
    duration: Optional[int] = 5
    additionalOptions: Optional[Dict[str, Any]] = None

# API 엔드포인트
@app.post("/api/generate", response_model=GenerationResponse)
async def generate_video(request: GenerationRequestAPI, background_tasks: BackgroundTasks):
    try:
        print(f"Received request: {request}")
        
        # DB에 작업 생성
        job_data = {
            "job_id": request.jobId,
            "prompt": request.prompt,
            "image_url": request.imageUrl,
            "image_urls": request.imageUrls,  # 여러 이미지 URL 저장
            "duration": request.duration,
            "additional_options": request.additionalOptions,
            "output_type": "mp4",  # 확장자 명시적으로 추가
            "status": "PENDING"
        }
        
        create_job(job_data)
        
        # 이미지 처리
        local_image_path = None
        
        # 여러 이미지가 제공된 경우
        if request.imageUrls and len(request.imageUrls) > 0:
            from app.services import download_multiple_images, merge_images
            
            print(f"Processing multiple images: {len(request.imageUrls)} URLs provided")
            
            # 모든 이미지 다운로드
            local_image_paths = await download_multiple_images(request.imageUrls)
            
            if local_image_paths:
                # 이미지 병합 (기본값: 수평 레이아웃)
                layout = request.additionalOptions.get("mergeLayout", "horizontal") if request.additionalOptions else "horizontal"
                local_image_path = merge_images(local_image_paths, layout)
                print(f"Images merged into: {local_image_path}")
                
                # 원본 이미지 파일 정리 (병합 후에는 필요 없음)
                for path in local_image_paths:
                    if os.path.exists(path) and path != local_image_path:  # 병합된 이미지는 삭제하지 않음
                        os.remove(path)
        
        # 단일 이미지 URL이 제공된 경우
        elif request.imageUrl:
            local_image_path = await download_image(request.imageUrl)
        
        # 백그라운드 작업으로 처리
        background_tasks.add_task(
            process_video_generation,
            job_id=request.jobId,
            prompt=request.prompt,
            image_path=local_image_path,
            output_type="mp4",  # 출력 타입 추가
            duration=request.duration,
            additional_options=request.additionalOptions
        )
        
        return {"jobId": request.jobId, "status": "PROCESSING"}
    
    except Exception as e:
        # 에러 로깅
        print(f"Error in generate_video: {str(e)}")
        
        # 작업 상태 업데이트
        update_job_status(request.jobId, "FAILED", error_message=str(e))
        
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def check_status(job_id: str):
    job = get_job_status(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job with ID {job_id} not found")
    
    return {
        "jobId": job_id,
        "status": job["status"],
        "resultUrl": job.get("result_url"),
        "error": job.get("error")
    }

@app.post("/api/battle", response_model=BattleResponse)
async def generate_battle(request: BattleRequest):
    """
    두 반려동물 간의 배틀 결과를 생성하는 엔드포인트
    """
    start_time = time.time()
    print(f"[PERF] Battle API 호출 시작: {start_time}")
    
    try:
        # 요청 데이터 검증
        if not request.myPetDetail or not request.targetPetDetail:
            raise HTTPException(status_code=400, detail="반려동물 상세 정보가 누락되었습니다.")
        
        print(f"[PERF] Battle 요청 검증 완료: {time.time() - start_time:.3f}초")    
            
        # 배틀 결과 생성
        battle_result = generate_battle_result(
            my_pet_name=request.myPetName,
            target_pet_name=request.targetPetName,
            my_pet_detail=request.myPetDetail,
            target_pet_detail=request.targetPetDetail
        )
        
        print(f"[PERF] Battle 결과 생성 완료: {time.time() - start_time:.3f}초")
        
        # 결과에서 승자와 패자 ID 설정
        winner_name = battle_result["winner"]
        
        # 응답 반환
        response = BattleResponse(
            result=battle_result["result"],
            winner=winner_name
        )
        
        print(f"[PERF] Battle API 총 처리 시간: {time.time() - start_time:.3f}초")
        return response
        
    except Exception as e:
        # 에러 로깅
        print(f"[ERROR] 배틀 생성 중 오류 발생: {str(e)}, 소요 시간: {time.time() - start_time:.3f}초")
        raise HTTPException(status_code=500, detail=f"배틀 생성 실패: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)