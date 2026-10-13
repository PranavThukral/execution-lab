FROM node:24-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN pip install --no-cache-dir uv && cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend/app ./backend/app
COPY backend/fixtures ./backend/fixtures
RUN cd backend && uv sync --frozen --no-dev
COPY docs ./docs
COPY --from=frontend-build /src/frontend/dist ./frontend/dist
COPY docker-entrypoint.py ./docker-entrypoint.py
RUN chown -R appuser:appuser /app
USER appuser
ENV PORT=8000 APP_ENV=production PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
CMD ["python", "docker-entrypoint.py"]
