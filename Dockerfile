FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y pip setuptools wheel || true
COPY --chown=root:root . .
RUN useradd --system --uid 10001 --no-create-home tse && mkdir -p var/uploads var/private var/log && chown -R tse var && chmod 750 var/private
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)"
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "--bind", "0.0.0.0:8000", "wsgi:app"]
