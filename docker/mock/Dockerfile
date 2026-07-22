FROM python:3.12-slim
COPY mock_freeipapi.py /mock_freeipapi.py
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/json/1.1.1.1')" || exit 1
CMD ["python", "/mock_freeipapi.py"]
