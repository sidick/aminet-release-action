FROM python:3.12-alpine

RUN apk add --no-cache lftp

COPY *.py /app/
WORKDIR /app

ENTRYPOINT ["python", "/app/entrypoint.py"]
