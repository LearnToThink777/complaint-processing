FROM python:3.12-slim

WORKDIR /app/complaint_processing

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# 정적 폴백용 frames.json 을 미리 만들어 두고(실패해도 무시), FastAPI(uvicorn)로
# API(/api/*, /docs)와 정적 프론트(viewer.html 등)를 한 서버에서 동시에 서빙한다.
# --app-dir /app 로 부모 디렉터리를 sys.path 에 넣어 complaint_processing 패키지를 임포트.
CMD ["sh", "-c", "python run.py --json frames.json || true; uvicorn --app-dir /app complaint_processing.api:app --host 0.0.0.0 --port 8000"]
