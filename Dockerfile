FROM python:3.11-slim

WORKDIR /app

RUN pip install fastapi uvicorn facebook-scraper requests lxml_html_clean --no-cache-dir

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
