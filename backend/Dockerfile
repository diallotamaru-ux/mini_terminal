FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MT_DB_PATH=/app/data/mini_terminal.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY terminal ./terminal
COPY backend ./backend
COPY examples ./examples

RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
