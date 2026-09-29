FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --system --uid 10001 --create-home monitor
COPY --chown=monitor:monitor . .
RUN chmod +x /app/start.sh
USER monitor
EXPOSE 8000
CMD ["/app/start.sh"]
