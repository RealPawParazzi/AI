import json
import os
from typing import Dict, Any, Optional
import logging

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 작업 데이터 저장 디렉토리
JOBS_DIR = "./temp/jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

def create_job(job_data: Dict[str, Any]) -> None:
    """새로운 작업을 생성하고 파일 시스템에 저장"""
    job_id = job_data["job_id"]
    file_path = os.path.join(JOBS_DIR, f"{job_id}.json")
    
    try:
        with open(file_path, "w") as f:
            json.dump(job_data, f)
        logger.info(f"Created job file: {file_path}")
    except Exception as e:
        logger.error(f"Error creating job file: {str(e)}")
        raise

def update_job_status(job_id: str, status: str, result_url: Optional[str] = None, error_message: Optional[str] = None) -> bool:
    """작업 상태 업데이트"""
    file_path = os.path.join(JOBS_DIR, f"{job_id}.json")
    
    if not os.path.exists(file_path):
        return False
    
    try:
        with open(file_path, "r") as f:
            job_data = json.load(f)
        
        job_data["status"] = status
        
        if result_url:
            job_data["result_url"] = result_url
        
        if error_message:
            job_data["error"] = error_message
        
        with open(file_path, "w") as f:
            json.dump(job_data, f)
            
        logger.info(f"Updated job status: {job_id} -> {status}")
        return True
    except Exception as e:
        logger.error(f"Error updating job status: {str(e)}")
        return False

def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """작업 상태 조회"""
    file_path = os.path.join(JOBS_DIR, f"{job_id}.json")
    
    if not os.path.exists(file_path):
        return None
    
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading job status: {str(e)}")
        return None