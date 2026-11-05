# v5: PaddleOCR 런타임·시스템 라이브러리(libGL 등)·OCR 모델(/app/models/paddlex)까지 들어 있다
FROM 117.16.166.23:80/wsu/rag-model-base:v5
WORKDIR /app

# 1) 의존성 레이어
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) 코드 레이어
COPY . .

# 3) 실행
CMD ["python", "main.py"]
