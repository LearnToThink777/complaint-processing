FROM python:3.12-slim

WORKDIR /app/complaint_processing

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python run.py --json frames.json && python -m http.server 8000"]
