FROM python:3.15-alpine

RUN apk add --no-cache lftp

COPY *.py /app/
WORKDIR /app

ENTRYPOINT ["python", "/app/entrypoint.py"]
