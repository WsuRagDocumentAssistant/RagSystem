FROM 117.16.166.23:80/wsu/rag-model-base:v2
WORKDIR /app

# 1) 의존성 레이어
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2) 코드 레이어
COPY . .

# 3) 실행
CMD ["python", "main.py"]
