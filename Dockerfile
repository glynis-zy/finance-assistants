# 财务智能助手平台镜像（build context = 仓库根，含 backend + frontend）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
WORKDIR /app

# 依赖层（利用 Docker 层缓存）
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]" "sqlalchemy>=2.0" "pydantic>=2.5" \
    "pydantic-settings>=2.0" "alembic>=1.13" "pymysql" "cryptography" \
    "celery[redis]>=5.3" "redis>=5.0" "pyjwt" "bcrypt" "python-multipart"

# 代码（backend 全部 + frontend 静态资源，FastAPI 托管，不引 nginx）
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/scripts ./scripts
COPY backend/tests ./tests
COPY frontend ./frontend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
