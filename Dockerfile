FROM python:slim

RUN --mount=type=bind,source=requirements.txt,target=/requirements.txt \
    \
    apt update -q \
 && apt install -qy ffmpeg libgl1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r /requirements.txt

WORKDIR /app

CMD ["python", "-u", "main.py"]
