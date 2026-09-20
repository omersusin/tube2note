# Hugging Face Spaces (Docker) — free hosting for the tube2note web UI.
# Create a Space (Docker type), push this repo, set port 7860. No token needed (public demo).
FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir . yt-dlp "fpdf2" && mkdir -p /app/out
EXPOSE 7860
CMD ["tube2note", "serve", "--host", "0.0.0.0", "--port", "7860", "--public", "-d", "/app/out", "--no-open"]
