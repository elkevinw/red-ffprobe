# Usa una imagen base con Python (ajusta la versión según necesites, ej. python:3.9-slim-buster)
FROM python:3.9-slim-bullseye

# Instala las dependencias del sistema necesarias, incluyendo ffmpeg y srt-tools
# RUN apt-get update: Actualiza la lista de paquetes.
# RUN apt-get install -y --no-install-recommends: Instala los paquetes de forma no interactiva.
#   ffmpeg: Necesario para el comando ffmpeg y ffprobe.
#   srt-tools: Proporciona srt-live-transmit.
# && rm -rf /var/lib/apt/lists/*: Limpia el caché de paquetes para reducir el tamaño de la imagen.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    srt-tools \
    && rm -rf /var/lib/apt/lists/*

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requisitos y los instala
# Esto se hace antes de copiar el resto del código para aprovechar el cache de Docker layers
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia los archivos de tu aplicación al contenedor
COPY .env .
COPY main.py .
COPY tu_video.mp4 .
COPY frontend/ ./frontend/

# Expone el puerto en el que la API FastAPI escuchará
EXPOSE 8000

# Comando por defecto que se ejecuta al iniciar el contenedor
# Esto inicia tu API FastAPI. La API se encargará de ejecutar ffprobe.
# Para iniciar srt-live-transmit y ffmpeg dentro del mismo contenedor, usaremos `docker exec`.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]