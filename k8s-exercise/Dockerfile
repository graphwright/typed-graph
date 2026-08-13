# Build context is the repo root (see docker-compose.yml) so we can copy the
# handful of tg-core modules this exercise actually needs.
FROM python:3.12-slim

WORKDIR /app

COPY base.py graph.py serialize.py example.py ./
COPY k8s-exercise/requirements.txt k8s-exercise/app.py ./
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
