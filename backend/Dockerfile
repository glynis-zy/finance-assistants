FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]" "sqlalchemy>=2.0" "pydantic>=2.5" \
    "pydantic-settings>=2.0" "alembic>=1.13" "pymysql" "cryptography" \
    "celery[redis]>=5.3" "redis>=5.0" "pyjwt" "bcrypt" "python-multipart"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
