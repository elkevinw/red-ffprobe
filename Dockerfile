# Usa una imagen base ligera de Python
FROM python:3.9-slim-bullseye

# Instala las dependencias del sistema necesarias, incluyendo ffmpeg y srt-tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    srt-tools \
    && rm -rf /var/lib/apt/lists/*

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requisitos y los instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia los archivos de tu aplicación al contenedor
COPY .env .
COPY main.py .
COPY tu_video.mp4 .
COPY frontend/ ./frontend/
COPY config.json .

# Expone el puerto en el que la API FastAPI escuchará
EXPOSE 8000

# Comando por defecto que se ejecuta al iniciar el contenedor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]