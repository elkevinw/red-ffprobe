import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Cargar Configuración ---
def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

config = load_config()

# --- Gestor de Canales FFMPEG ---
class ChannelManager:
    def __init__(self, channel_config, channel_manager):
        self.id = channel_config['id']
        self.name = channel_config['name']
        self.process = None
        self.status = "inactive"
        self.log_path = Path(config['log_directory']) / f"channel_{self.id}_{self.name}.log"
        self.log_file = None
        self.last_active_timestamp = None
        self.channel_manager = channel_manager

        # Crear directorio de logs si no existe
        self.log_path.parent.mkdir(exist_ok=True)

    def build_command(self) -> List[str]:
        # Construye la URL SRT
        port = config['srt_base_port'] + self.id
        srt_url = f"srt://0.0.0.0:{port}{config['srt_options'].format(srt_mode=config['srt_mode'])}"

        # Construye la URL Multicast
        multicast_ip_parts = config['multicast_base_ip'].split('.')
        multicast_ip_parts[-1] = str(int(multicast_ip_parts[-1]) + self.id - 1)
        multicast_ip = ".".join(multicast_ip_parts)
        multicast_port = config['multicast_base_port'] + (self.id - 1) * 2
        multicast_interface = config['multicast_interface']
        multicast_options = config['multicast_options']
        multicast_url = f"udp://{multicast_ip}:{multicast_port}?localaddr={multicast_interface}&{multicast_options}"

        # Calcula el Service ID
        service_id = config['service_id_base'] + self.id

        # Reemplaza placeholders en la plantilla del comando
        command_template = config['ffmpeg_command_template']
        command = [
            str(arg).format(
                srt_url=srt_url,
                multicast_url=multicast_url,
                channel_name=self.name,
                service_id=service_id
            )
            for arg in command_template
        ]
        logging.info(f"Comando para canal {self.name}: {' '.join(command)}")
        return command

    async def start(self):
        if self.process and self.process.returncode is None:
            logging.info(f"El proceso para el canal {self.name} ya está activo.")
            return

        command = self.build_command()
        try:
            # Abrir archivo de log para stdout y stderr
            self.log_file = open(self.log_path, 'w')
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self.status = "listening"
            logging.info(f"Proceso para canal {self.name} iniciado (escuchando) con PID: {self.process.pid}")
            # Iniciar tarea para leer la salida del proceso
            asyncio.create_task(self.read_output())

        except Exception as e:
            self.status = "crashed"
            logging.error(f"Error al iniciar el proceso para el canal {self.name}: {e}")
            if self.log_file:
                self.log_file.close()

    async def read_output(self):
        buffer = ''
        while self.process.stdout and not self.process.stdout.at_eof():
            data = await self.process.stdout.read(1024)
            if not data:
                break

            decoded_data = data.decode('utf-8', errors='ignore')
            buffer += decoded_data

            # Procesar el buffer buscando líneas terminadas en \n o \r
            while '\n' in buffer or '\r' in buffer:
                # Encontrar la primera ocurrencia de cualquiera de los dos separadores
                end_of_line_n = buffer.find('\n')
                end_of_line_r = buffer.find('\r')

                if end_of_line_n == -1:
                    split_pos = end_of_line_r
                elif end_of_line_r == -1:
                    split_pos = end_of_line_n
                else:
                    split_pos = min(end_of_line_n, end_of_line_r)

                line_to_process = buffer[:split_pos].strip()
                buffer = buffer[split_pos + 1:]

                if not line_to_process:
                    continue

                if self.log_file and not self.log_file.closed:
                    self.log_file.write(line_to_process + '\n')
                    self.log_file.flush()

                # Lógica de estado robusta
                status_changed = False
                if "speed=" in line_to_process:
                    if self.status == "listening":
                        self.status = "active"
                        logging.info(f"Stream STARTED for channel {self.name}. Status: ACTIVE")
                        status_changed = True
                    # Actualizar timestamp mientras esté activo
                    self.last_active_timestamp = time.time()

                if status_changed:
                    await self.channel_manager.broadcast_status()

    async def stop(self):
        if self.process and self.process.returncode is None:
            logging.info(f"Deteniendo proceso para el canal {self.name} (PID: {self.process.pid})")
            self.process.terminate()
            await self.process.wait()
            logging.info(f"Proceso para el canal {self.name} detenido.")
        self.status = "inactive"
        if self.log_file and not self.log_file.closed:
            self.log_file.close()

    async def restart(self):
        await self.stop()
        self.status = "inactive"
        self.last_active_timestamp = None # Resetear timestamp en reinicio
        await self.start()
        # Notificar a los clientes después de reiniciar
        await self.channel_manager.broadcast_status()

    def get_state(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "pid": self.process.pid if self.process else None
        }

class GlobalChannelManager:
    def __init__(self, channels_config):
        self.channels: Dict[int, ChannelManager] = {
            ch_conf['id']: ChannelManager(ch_conf, self) for ch_conf in channels_config if ch_conf['enabled']
        }
        self.active_websockets: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_websockets.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_websockets.remove(websocket)

    async def broadcast_status(self):
        if not self.active_websockets:
            return
        message = self.get_all_statuses()
        # Prepara una tarea de envío para cada websocket activo
        results = await asyncio.gather(*[ws.send_json(message) for ws in self.active_websockets], return_exceptions=True)

        # Limpiar conexiones de websockets que fallaron (desconectados)
        for i in range(len(self.active_websockets) - 1, -1, -1):
            if isinstance(results[i], Exception):
                logging.info(f"Eliminando websocket desconectado: {self.active_websockets[i].client}")
                self.active_websockets.pop(i)

    async def start_all(self):
        tasks = [channel.start() for channel in self.channels.values()]
        await asyncio.gather(*tasks)

    async def monitor_processes(self):
        while True:
            status_changed = False
            for channel in self.channels.values():
                # 1. Comprobar si el proceso se ha caído (código de retorno no nulo)
                if channel.process is None or channel.process.returncode is not None:
                    if channel.status not in ["inactive", "crashed"]:
                        logging.warning(f"Process for {channel.name} has CRASHED.")
                        channel.status = "crashed"
                        channel.last_active_timestamp = None
                        if channel.log_file and not channel.log_file.closed:
                            channel.log_file.close()
                        
                        logging.info(f"Restarting crashed channel {channel.name} in 5s...")
                        await asyncio.sleep(5)
                        await channel.restart() # El reinicio notificará el nuevo estado
                        status_changed = True
                
                # 2. Comprobar si un stream activo se ha quedado sin señal (timeout)
                elif channel.status == "active" and channel.last_active_timestamp:
                    if (time.time() - channel.last_active_timestamp) > 15: # 15 segundos de timeout
                        logging.warning(f"Stream TIMEOUT for channel {channel.name}. Reverting to LISTENING.")
                        channel.status = "listening"
                        channel.last_active_timestamp = None
                        status_changed = True

            # Si cualquier estado cambió, notificar a todos los clientes
            if status_changed:
                await self.broadcast_status()

            await asyncio.sleep(5) # Intervalo de chequeo

    def get_all_statuses(self) -> List[Dict]:
        return [
            channel.get_state() for channel in self.channels.values()
        ]

# --- Almacén de Estado Global ---
channel_manager = GlobalChannelManager(config.get("channels", []))

# --- Tarea de Monitoreo en Segundo Plano ---
async def monitor_channels():
    await channel_manager.start_all()
    # Da un momento para que los procesos se inicien antes de empezar a monitorear
    await asyncio.sleep(1)
    await channel_manager.monitor_processes()

# --- Aplicación FastAPI ---
app = FastAPI()

# Gestionar ciclo de vida de la aplicación
@app.on_event("startup")
async def startup_event():
    # Iniciar la tarea de monitoreo
    asyncio.create_task(monitor_channels())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await channel_manager.connect(websocket)
    try:
        # Enviar el estado actual SOLO a este cliente
        await websocket.send_json(channel_manager.get_all_statuses())

        # Mantener la conexión viva para que el servidor pueda enviar actualizaciones.
        # El cliente no envía datos, solo recibe, así que no usamos receive_text().
        while True:
            await asyncio.sleep(1) # Previene que la función termine y cierre la conexión.
    except WebSocketDisconnect:
        logging.info(f"Cliente {websocket.client} desconectado.")
        channel_manager.disconnect(websocket)

@app.post("/api/restart/{channel_id}")
async def restart_channel(channel_id: int):
    channel = channel_manager.channels.get(channel_id)
    if not channel:
        return {"error": "Canal no encontrado"}
    
    asyncio.create_task(channel.restart())
    return {"message": f"El reinicio del canal {channel.name} ha sido iniciado."}

# --- Servir Frontend ---
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse('frontend/index.html')