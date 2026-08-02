FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY web/frontend/package*.json ./
RUN npm install
COPY web/frontend/ ./
RUN npm run build

FROM python:3.11-slim AS backend
WORKDIR /app
COPY web/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY coding_agent/ ./coding_agent/
COPY web/backend/ ./web/backend/
COPY --from=frontend-build /app/frontend/dist ./web/frontend/dist

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "web.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
