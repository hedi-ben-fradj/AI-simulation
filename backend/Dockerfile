FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY aisim ./aisim


RUN pip install .

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 aisim
USER aisim

ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["python", "-m", "aisim"]
