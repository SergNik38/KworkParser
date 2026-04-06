FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY kwork_parser ./kwork_parser
COPY README.md ./
COPY .env.example ./

RUN mkdir -p /app/data

ENTRYPOINT ["python", "-m", "kwork_parser"]
