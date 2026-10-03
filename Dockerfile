FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    CONFIG=/data/config.yml \
    DOSSIER_UNIVERS=/data/univers \
    PORT_WEB=8099

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY jellyfin_univers.py .
COPY web/ ./web/

EXPOSE 8099
VOLUME ["/data"]
HEALTHCHECK --interval=1m --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/sante')" || exit 1
ENTRYPOINT ["python", "/app/jellyfin_univers.py"]
CMD ["--boucle"]
