FROM python:3.10-slim

WORKDIR /app

# Copiar requirements e instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação e módulos
COPY main.py .
COPY handler /app/handler
COPY router /app/router
COPY common_logic /app/common_logic

# Expor porta (Cloud Run usa a variável PORT)
ENV PORT=8080
EXPOSE 8080

# Comando para executar a aplicação
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1

