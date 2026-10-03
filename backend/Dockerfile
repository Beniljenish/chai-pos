FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Apply migrations, then serve. Fine for one instance; with several instances,
# run migrations as a separate release step instead.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
