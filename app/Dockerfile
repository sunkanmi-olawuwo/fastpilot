# FastPilot backend image. Refined in Phase 5 (deployment); valid + buildable now.
FROM python:3.12-slim

WORKDIR /srv

# System deps kept minimal; slim base is enough for the pure-Python stack.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend package as `app/` so `import app.config` resolves.
COPY . ./app/

EXPOSE 8000

# Railway injects $PORT; default to 8000 locally. Bind 0.0.0.0 for the container.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
