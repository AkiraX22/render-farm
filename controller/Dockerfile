FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controller.py .
USER 65532
ENTRYPOINT ["python", "-u", "controller.py"]
