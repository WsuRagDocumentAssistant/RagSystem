FROM 117.16.166.23:80/wsu/rag-model-base:v4
WORKDIR /app

# 0) 스캔 PDF OCR(PaddleOCR)이 쓰는 OpenCV·Paddle 의 시스템 라이브러리.
#    베이스 이미지에 없으면 OCR 할 때 "libGL.so.1: cannot open shared object file" 로 실패한다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 1) 의존성 레이어
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) 코드 레이어
COPY . .

# 3) 실행
CMD ["python", "main.py"]
