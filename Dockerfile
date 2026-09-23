FROM python:3.13-slim
WORKDIR /app
COPY requirements-remote.txt .
RUN pip install --no-cache-dir -r requirements-remote.txt
ADD https://raw.githubusercontent.com/verswu/samsara-mcp-server/8118c9267a79cf764be88bf342601b725846f993/server.py ./server.py
ADD https://raw.githubusercontent.com/verswu/samsara-mcp-server/8118c9267a79cf764be88bf342601b725846f993/samsara_client.py ./samsara_client.py
COPY http_server.py ./
ENV PORT=8080
EXPOSE 8080
CMD ["python", "http_server.py"]
