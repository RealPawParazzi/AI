import os
import requests
import uuid
import aiohttp
import aiofiles
import boto3
import base64
import time
from typing import Dict, Any, Optional, List
import logging
from runwayml import RunwayML
import openai
from PIL import Image
import io

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API 클라이언트 초기화
runway_client = RunwayML(api_key=os.getenv("RUNWAY_API_KEY"))
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def download_image(image_url: str) -> str:
    """URL에서 이미지 다운로드"""
    if not image_url:
        return None
        
    # 임시 디렉토리 확인
    os.makedirs("./temp", exist_ok=True)
    
    # 고유한 파일 이름 생성
    file_extension = os.path.splitext(image_url)[1] or ".jpg"
    temp_file_path = f"./temp/{uuid.uuid4()}{file_extension}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download image from {image_url}: {response.status}")
                    return None
                    
                async with aiofiles.open(temp_file_path, 'wb') as f:
                    await f.write(await response.read())
                    
        logger.info(f"Downloaded image to {temp_file_path}")
        return temp_file_path
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {str(e)}")
        return None

async def download_multiple_images(image_urls: List[str]) -> List[str]:
    """여러 URL에서 이미지 다운로드"""
    if not image_urls:
        return []
        
    local_image_paths = []
    
    for image_url in image_urls:
        local_path = await download_image(image_url)
        if local_path:
            local_image_paths.append(local_path)
    
    logger.info(f"Downloaded {len(local_image_paths)} images from {len(image_urls)} URLs")
    return local_image_paths

def merge_images(image_paths: List[str], layout: str = 'horizontal') -> str:
    """여러 이미지를 하나로 병합"""
    if not image_paths:
        return None
    
    # 단일 이미지인 경우 병합 불필요
    if len(image_paths) == 1:
        return image_paths[0]
    
    try:
        # 이미지 로드
        images = [Image.open(path) for path in image_paths]
        
        # 이미지 리사이즈 (선택적)
        # - 모든 이미지의 높이가 같도록 조정 (가로 레이아웃의 경우)
        # - 모든 이미지의 너비가 같도록 조정 (세로 레이아웃의 경우)
        max_width = max(img.width for img in images)
        max_height = max(img.height for img in images)
        
        if layout == 'horizontal':
            # 가로 배치: 모든 이미지의 높이를 동일하게 조정
            target_height = min(max_height, 768)  # 최대 높이 제한
            resized_images = []
            total_width = 0
            
            for img in images:
                aspect_ratio = img.width / img.height
                new_width = int(target_height * aspect_ratio)
                resized_img = img.resize((new_width, target_height), Image.LANCZOS)
                resized_images.append(resized_img)
                total_width += new_width
                
            # 병합된 이미지 생성
            merged_image = Image.new('RGB', (total_width, target_height))
            x_offset = 0
            
            for img in resized_images:
                merged_image.paste(img, (x_offset, 0))
                x_offset += img.width
                
        else:  # 'vertical'
            # 세로 배치: 모든 이미지의 너비를 동일하게 조정
            target_width = min(max_width, 1024)  # 최대 너비 제한
            resized_images = []
            total_height = 0
            
            for img in images:
                aspect_ratio = img.width / img.height
                new_height = int(target_width / aspect_ratio)
                resized_img = img.resize((target_width, new_height), Image.LANCZOS)
                resized_images.append(resized_img)
                total_height += new_height
                
            # 병합된 이미지 생성
            merged_image = Image.new('RGB', (target_width, total_height))
            y_offset = 0
            
            for img in resized_images:
                merged_image.paste(img, (0, y_offset))
                y_offset += img.height
        
        # 병합된 이미지 저장
        os.makedirs("./temp/merged", exist_ok=True)
        output_path = f"./temp/merged/{uuid.uuid4()}.jpg"
        merged_image.save(output_path, format='JPEG', quality=95)
        
        logger.info(f"Merged {len(image_paths)} images to {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error merging images: {str(e)}")
        # 실패 시 첫 번째 이미지 반환
        return image_paths[0] if image_paths else None

def generate_prompt(prompt: str) -> str:
    """GPT-4를 사용하여 프롬프트를 최적화하고 1000자 미만으로 제한"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": f"""
                You are an expert cinematic storyteller specializing in AI-generated video prompts.
                Transform the following prompt into a highly dynamic, cinematic description:
                - Include camera movements (slow zoom, dolly, tracking shots)
                - Add cinematic composition (close-ups, wide shots)
                - Set vivid atmosphere with lighting
                - Keep the tone immersive and engaging
                
                IMPORTANT: Your entire response MUST be under 500 characters total. Be concise.
                
                Original prompt: {prompt}
                
                Return ONLY the optimized prompt. No explanations.
                """
            }]
        )
        
        optimized_prompt = response.choices[0].message.content.strip()
        
        # 1000자 제한 추가 (여유 있게 900자로 제한)
        if len(optimized_prompt) > 900:
            optimized_prompt = optimized_prompt[:897] + "..."
        
        logger.info(f"Optimized prompt: {optimized_prompt}")
        return optimized_prompt
        
    except Exception as e:
        logger.error(f"Error optimizing prompt: {str(e)}")
        return prompt  # 실패 시 원본 프롬프트 반환

def generate_video(
    prompt: str,
    image_path: Optional[str],
    duration: Optional[int] = None,
    additional_options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Runway API를 사용하여 비디오/GIF 생성"""
    logger.info(f"Generating with Runway: {prompt}")
    
    try:
        # 프롬프트 최적화
        # optimized_prompt = generate_prompt(prompt)
        
        # 이미지가 있는 경우 Base64로 인코딩
        prompt_image = None
        if image_path:
            with open(image_path, "rb") as f:
                base64_image = base64.b64encode(f.read()).decode("utf-8")
                prompt_image = f"data:image/png;base64,{base64_image}"
        
        # Runway API 호출
        task = runway_client.image_to_video.create(
            model='gen3a_turbo',
            prompt_image=prompt_image,
            prompt_text=prompt,
            duration=min(10, max(5, duration or 5)),  # 5초 또는 10초
            ratio="1280:768",  # 16:9 비율
            **(additional_options or {})
        )
        
        # 작업 ID 로깅
        task_id = task.id
        logger.info(f"Runway task created: {task_id}")
        
        # 작업 완료 대기
        logger.info("Waiting for video generation...")
        while True:
            task_status = runway_client.tasks.retrieve(task_id)
            logger.info(f"Current status: {task_status.status}")
            
            if task_status.status in ['SUCCEEDED', 'FAILED']:
                break
                
            time.sleep(10)  # 10초 대기
        
        # 결과 처리
        if task_status.status == 'SUCCEEDED':
            video_url = task_status.output[0]
            logger.info(f"Video generated successfully: {video_url}")
            
            # 비디오 다운로드
            os.makedirs("./temp/outputs", exist_ok=True)
            output_path = f"./temp/outputs/{uuid.uuid4()}"
            
            response = requests.get(video_url, stream=True)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        f.write(chunk)
                logger.info(f"Video downloaded to: {output_path}")
            else:
                raise ValueError(f"Failed to download video: {response.status_code}")
            
            return {
                "local_path": output_path,
                "width": 1024,
                "height": 576,
                "duration": duration or 5
            }
        else:
            error_msg = getattr(task_status, "status_reason", "Unknown error")
            logger.error(f"Runway task failed: {error_msg}")
            raise ValueError(f"Runway task failed: {error_msg}")
            
    except Exception as e:
        logger.error(f"Error in Runway API call: {str(e)}")
        raise

def upload_to_storage(local_path: str, job_id: str, file_type: str) -> str:
    """생성된 파일을 클라우드 스토리지(S3)에 업로드"""
    logger.info(f"Uploading file to storage: {local_path}")
    
    # AWS S3 설정
    aws_access_key = os.getenv("AWS_ACCESS_KEY")
    aws_secret_key = os.getenv("AWS_SECRET_KEY")
    aws_region = os.getenv("AWS_REGION", "ap-northeast-2")
    s3_bucket = os.getenv("AWS_S3_BUCKET")
    
    # S3 미설정 시 로컬 경로 반환 (개발용)
    if not all([aws_access_key, aws_secret_key, s3_bucket]):
        logger.warning("AWS credentials not set, returning local file path for development")
        return f"http://localhost:8000/files/{os.path.basename(local_path)}"
    
    try:
        # S3 클라이언트 초기화
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
        
        # 업로드할 파일 경로 구성
        file_name = f"{job_id}.{file_type}"
        s3_key = f"generated/{file_type}/{file_name}"
        
        # S3에 업로드
        s3_client.upload_file(
            local_path, 
            s3_bucket, 
            s3_key,
            ExtraArgs={'ContentType': f'{"image" if file_type == "gif" else "mp4"}/{file_type}'}
        )
        
        # 업로드된 파일 URL 생성
        file_url = f"https://{s3_bucket}.s3.{aws_region}.amazonaws.com/{s3_key}"
        
        logger.info(f"File uploaded to S3: {file_url}")
        return file_url
        
    except Exception as e:
        logger.error(f"Error uploading file to S3: {str(e)}")
        return f"http://localhost:8000/files/{os.path.basename(local_path)}"

def generate_battle_result(my_pet_name: str, target_pet_name: str, my_pet_detail: str, target_pet_detail: str) -> dict:
    """OpenAI GPT 모델을 사용하여, 두 반려동물 간의 배틀 결과를 생성하고 승자를 판단합니다."""
    start_time = time.time()
    logger.info(f"[PERF] 펫 배틀 생성 요청 시작: {my_pet_name} vs {target_pet_name}")
    
    try:
        # 배틀 프롬프트 구성
        prompt_start_time = time.time()
        battle_prompt = f"""
        당신은 두 반려동물 간의 배틀을 흥미진진하게 묘사하는 스토리텔러입니다.
        
        다음 두 반려동물이 포켓몬 배틀처럼 대결을 벌입니다:
        
        반려동물 1 이름: {my_pet_name}

        반려동물 1 특성: {my_pet_detail}

        반려동물 2 이름: {target_pet_name}
        
        반려동물 2 특성: {target_pet_detail}
        
        각 반려동물의 특성을 분석하여 능력, 약점, 전략 등을 고려한 배틀 결과를 생성하세요.
        최종적으로 누가 승리했는지 명확히 표시해야 합니다.
        
        배틀 과정과 결과를 포함하여 다음 형식으로 작성해주세요:
        
        [배틀 과정] 5줄 이내로 요약
        
        [승자]
        {my_pet_name} 또는 {target_pet_name} 중 승자의 이름만 정확히 작성
        """
        logger.info(f"[PERF] 프롬프트 구성 완료: {time.time() - prompt_start_time:.3f}초")
        
        # OpenAI API 호출
        api_call_start_time = time.time()
        logger.info("[PERF] OpenAI API 호출 시작")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": battle_prompt
            }]
        )
        
        api_call_time = time.time() - api_call_start_time
        logger.info(f"[PERF] OpenAI API 호출 완료: {api_call_time:.3f}초")
        
        battle_text = response.choices[0].message.content.strip()
        
        # 배틀 결과에서 승자 추출
        extract_start_time = time.time()
        logger.info("[PERF] 승자 추출 시작")
        winner = extract_winner_from_battle(battle_text, my_pet_name, target_pet_name)
        logger.info(f"[PERF] 승자 추출 완료: {time.time() - extract_start_time:.3f}초")
        
        total_time = time.time() - start_time
        logger.info(f"[PERF] 배틀 결과 생성 완료, 총 소요 시간: {total_time:.3f}초 (API 호출: {api_call_time:.3f}초, {(api_call_time/total_time*100):.1f}%)")
        
        # 배틀 결과와 승자 정보 반환
        return {
            "result": battle_text,
            "winner": winner
        }
        
    except Exception as e:
        logger.error(f"[ERROR] 배틀 결과 생성 중 오류 발생: {str(e)}, 소요 시간: {time.time() - start_time:.3f}초")
        raise ValueError(f"배틀 결과 생성 실패: {str(e)}")

def extract_winner_from_battle(battle_text: str, my_pet_name: str, target_pet_name: str) -> str:
    """배틀 결과 텍스트에서 승자를 추출합니다."""
    start_time = time.time()
    logger.info(f"[PERF] 승자 추출 시작: {my_pet_name} vs {target_pet_name}")
    
    # LLM의 응답에서 [승자] 섹션 찾기
    if "[승자]" in battle_text:
        winner_section = battle_text.split("[승자]")[1].strip()
        # 첫 줄만 가져오기
        winner_name = winner_section.split("\n")[0].strip()
        logger.info(f"[PERF] [승자] 섹션에서 승자 추출: {time.time() - start_time:.3f}초")
        return winner_name
    else:
        # 승자 섹션이 없는 경우, 텍스트에서 승자 찾기 시도
        keyword_start = time.time()
        logger.info("[PERF] 키워드 기반 승자 검색 시작")
        
        battle_lower = battle_text.lower()
        my_pet_lower = my_pet_name.lower()
        target_pet_lower = target_pet_name.lower()
        
        # 승리, 이겼다, 승자 등의 키워드 근처에서 펫 이름 찾기
        victory_keywords = ["승리", "이겼", "이김", "승자", "우승", "win", "winner", "victory"]
        
        for keyword in victory_keywords:
            if keyword in battle_lower:
                # 키워드 주변 문장 분석
                sentences = battle_lower.split('.')
                for sentence in sentences:
                    if keyword in sentence:
                        if my_pet_lower in sentence and target_pet_lower not in sentence:
                            logger.info(f"[PERF] 키워드 검색으로 승자 결정: {time.time() - keyword_start:.3f}초")
                            return my_pet_name
                        elif target_pet_lower in sentence and my_pet_lower not in sentence:
                            logger.info(f"[PERF] 키워드 검색으로 승자 결정: {time.time() - keyword_start:.3f}초")
                            return target_pet_name
        
        logger.info(f"[PERF] 키워드 검색 완료 (승자 미발견): {time.time() - keyword_start:.3f}초")
        
        # 여전히 승자를 찾지 못한 경우, GPT에게 다시 물어보기
        try:
            gpt_start = time.time()
            logger.info("[PERF] 승자 판단을 위한 2차 OpenAI API 호출 시작")
            
            clarification = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": f"""
                    다음 배틀 결과에서 승자가 누구인지만 알려주세요.
                    '{my_pet_name}'와 '{target_pet_name}' 중에서 승자의 이름만 답변하세요.
                    
                    배틀 결과:
                    {battle_text}
                    """
                }]
            )
            winner_text = clarification.choices[0].message.content.strip()
            
            gpt_time = time.time() - gpt_start
            logger.info(f"[PERF] 2차 OpenAI API 호출 완료: {gpt_time:.3f}초")
            
            # 명확한 이름 매칭
            if my_pet_name.lower() in winner_text.lower():
                return my_pet_name
            elif target_pet_name.lower() in winner_text.lower():
                return target_pet_name
                
            logger.info("[PERF] 2차 API 호출 결과에서도 승자를 명확하게 결정할 수 없음")
        except Exception as e:
            logger.error(f"[ERROR] 2차 OpenAI API 호출 실패: {str(e)}, {time.time() - gpt_start:.3f}초")
    
        # 기본값으로 무승부 또는 랜덤 선택 (여기서는 내 펫 선택)
        logger.info(f"[PERF] 승자 추출 실패, 기본값 사용: {time.time() - start_time:.3f}초")
        return my_pet_name