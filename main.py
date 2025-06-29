import asyncio
import json
import os
import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
from datetime import datetime # ¡Importante: Añadimos datetime!

# Carga las variables de entorno desde un archivo .env
load_dotenv()

# --- Configuración ---
# URL de la señal SRT a monitorear (se obtiene de las variables de entorno)
SRT_URL = os.getenv("SRT_URL", "srt://127.0.0.1:1234?mode=listener")
# Intervalo de monitoreo en segundos
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", 5))

# --- Estado Global de la Señal SRT ---
# Usamos un diccionario para mantener el estado de la señal SRT
# y un asyncio.Lock para asegurar el acceso seguro desde diferentes tareas
global_srt_status = {
    "is_active": False,
    "last_updated": None, # Aquí guardaremos la última vez que se actualizó el estado
    "ffprobe_data": None, # Aquí se guardarán los datos de ffprobe si la señal está activa
    "error_message": "Not yet checked or initial error." # Mensaje de error si la señal no está activa
}
status_lock = asyncio.Lock()

# --- Modelos Pydantic para la API ---
class SRTStatus(BaseModel):
    is_active: bool
    last_updated: Optional[str]
    ffprobe_data: Optional[dict]
    error_message: Optional[str]

# --- Instancia de FastAPI ---
app = FastAPI(
    title="SRT Monitor API",
    description="API para monitorear el estado de una señal SRT usando ffprobe."
)

# --- Middleware de CORS ---
# Permite que el frontend (que se ejecutará en un origen diferente)
# se comunique con esta API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, deberías restringir esto a dominios específicos
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# --- Montar archivos estáticos para el frontend ---
# Esto servirá los archivos CSS y JS
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# --- Funciones Auxiliares ---
async def run_ffprobe(url: str) -> dict:
    """
    Ejecuta ffprobe para obtener información sobre la URL SRT.
    Lanza un RuntimeError si ffprobe falla.
    """
    print(f"DEBUG: Running ffprobe for URL: {url}")
    # Comando ffprobe para obtener la información del stream en formato JSON
    command = ["ffprobe", "-v", "error", "-show_streams", "-select_streams", "v:0", "-of", "json", url]
    
    # Ejecuta el comando en un subproceso
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        print(f"ERROR: ffprobe failed with code {process.returncode}: {error_msg}")
        raise RuntimeError(f"FFprobe command failed: {error_msg}")
    
    try:
        ffprobe_output = stdout.decode().strip()
        data = json.loads(ffprobe_output)
        return data
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse ffprobe JSON output: {e}")
        print(f"FFprobe Raw Output: {ffprobe_output}")
        raise ValueError(f"Failed to parse ffprobe output: {e}")

async def monitor_srt_signal():
    """
    Tarea en segundo plano que ejecuta ffprobe periódicamente
    y actualiza el estado global de la señal SRT.
    """
    while True:
        print(f"INFO: Checking SRT signal status for {SRT_URL}...")
        
        try:
            ffprobe_data = await run_ffprobe(SRT_URL)
            async with status_lock:
                global_srt_status["is_active"] = True
                # ¡Corrección aquí! Usamos datetime.now()
                global_srt_status["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                global_srt_status["ffprobe_data"] = ffprobe_data
                global_srt_status["error_message"] = None
            print(f"INFO: SRT status updated successfully for {SRT_URL}.")

        except (RuntimeError, ValueError) as e:
            async with status_lock:
                global_srt_status["is_active"] = False
                # ¡Corrección aquí! Usamos datetime.now()
                global_srt_status["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                global_srt_status["ffprobe_data"] = None
                global_srt_status["error_message"] = str(e)
            print(f"ERROR: Could not get SRT status for {SRT_URL}: {e}")
        except Exception as e:
            async with status_lock:
                global_srt_status["is_active"] = False
                # ¡Corrección aquí! Usamos datetime.now()
                global_srt_status["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                global_srt_status["ffprobe_data"] = None
                global_srt_status["error_message"] = f"An unexpected error occurred: {e}"
            print(f"FATAL ERROR: Unexpected issue in monitoring task: {e}")

        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

# --- Eventos de Ciclo de Vida de la Aplicación ---
@app.on_event("startup")
async def startup_event():
    """Se ejecuta cuando la aplicación se inicia."""
    print("INFO: FastAPI application startup. Starting background monitoring task...")
    asyncio.create_task(monitor_srt_signal())

@app.on_event("shutdown")
async def shutdown_event():
    """Se ejecuta cuando la aplicación se apaga."""
    print("INFO: FastAPI application shutdown.")
    # Si tienes tareas que necesiten limpieza, hazla aquí.
    # Uvicorn gestiona el cierre de tareas asyncio en su mayoría.

# --- Endpoints de la API ---
@app.get("/api/srt/status", response_model=SRTStatus)
async def get_srt_status():
    """
    Devuelve el estado actual de la señal SRT.
    """
    async with status_lock:
        return global_srt_status

@app.get("/health")
async def health_check():
    """
    Endpoint para verificar el estado de salud de la API.
    """
    return {"status": "ok", "message": "SRT Monitor API is running"}

# --- Servir el Frontend ---
@app.get("/", include_in_schema=False)
async def read_index():
    """Sirve el archivo index.html del frontend."""
    # Construye una ruta absoluta al archivo para evitar problemas
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    index_path = os.path.join(frontend_dir, "index.html")
    
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="index.html not found")

    return FileResponse(index_path)


# --- Ejecución (solo para desarrollo local) ---
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)