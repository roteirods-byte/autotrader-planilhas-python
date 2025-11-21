FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# Entry point oficial deste repositório
CMD ["python", "worker_entrada.py"]
