# app/tasks.py - 비디오 생성 작업 처리
import os
import time
import requests
from typing import Dict, Any, Optional
import logging

from .db import update_job_status
from .services import (
    generate_video,
    upload_to_storage
)

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_video_generation(
    job_id: str,
    prompt: str,
    image_path: Optional[str],
    output_type: str,
    duration: Optional[int] = None,
    additional_options: Optional[Dict[str, Any]] = None
):
    """비디오 생성 작업 처리"""
    try:
        logger.info(f"Starting video generation for job {job_id}")
        update_job_status(job_id, "PROCESSING")
        
        # Runway API로 비디오 생성
        result = generate_video(
            prompt=prompt,
            image_path=image_path,
            duration=duration,
            additional_options=additional_options
        )
        
        # 임시 파일 저장 처리
        temp_output_path = result["local_path"]
        
        # 결과물 클라우드 스토리지 업로드
        storage_url = upload_to_storage(temp_output_path, job_id, file_type=output_type)
        
        # 작업 상태 업데이트
        update_job_status(job_id, "COMPLETED", result_url=storage_url)
        
        # 웹훅으로 백엔드 서버에 알림
        notify_backend(job_id, "COMPLETED", storage_url)
        
        logger.info(f"Video generation completed for job {job_id}")
        
        # 임시 파일 정리
        if os.path.exists(temp_output_path):
            os.remove(temp_output_path)
        
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
            
    except Exception as e:
        logger.error(f"Error in video generation for job {job_id}: {str(e)}")
        update_job_status(job_id, "FAILED", error_message=str(e))
        
        # 웹훅으로 백엔드 서버에 알림
        notify_backend(job_id, "FAILED", error=str(e))
        
        # 임시 파일 정리
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

def notify_backend(job_id: str, status: str, result_url: Optional[str] = None, error: Optional[str] = None):
    """백엔드 서버에 작업 상태 업데이트 알림"""
    backend_webhook_url = os.getenv("BACKEND_WEBHOOK_URL", "http://localhost:8080/api/webhooks/video-result")
    
    payload = { 
        "jobId": job_id,
        "status": status
    }
    
    if result_url:
        payload["resultUrl"] = result_url
    
    if error:
        payload["error"] = error
    
    try:
        response = requests.post(
            backend_webhook_url, 
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code >= 400:
            logger.error(f"Failed to notify backend: {response.status_code} {response.text}")
        else:
            logger.info(f"Successfully notified backend about job {job_id} status: {status}")
    except Exception as e:
        logger.error(f"Error notifying backend: {str(e)}")
