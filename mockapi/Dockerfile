FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.3
COPY app.py .
ENV BIND=0.0.0.0 PORT=5000 FLAKY_EVERY=3
EXPOSE 5000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2).status == 200 else 1)"
RUN useradd -r -u 10001 app
USER app
CMD ["python", "app.py"]
