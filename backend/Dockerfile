FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
# Local Docker Compose passes EXTRAS=demo for scripts.local_demo; Vercel does not use this file
ARG EXTRAS=""
RUN pip install --no-cache-dir ".${EXTRAS:+[$EXTRAS]}"

COPY . .

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Apply migrations, then serve. Fine for one instance; with several instances,
# run migrations as a separate release step instead.
CMD ["sh", "-c", "alembic upgrade heads && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
