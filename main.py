import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
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
        self.mode = channel_config.get('mode', 'listener')
        self.remote_ip = channel_config.get('remote_ip')
        self.remote_port = channel_config.get('remote_port')
        self.local_port = channel_config.get('local_port', config['srt_base_port'] + channel_config['id'])
        self.process = None
        self.status = "inactive"
        self.log_path = Path(config['log_directory']) / f"channel_{self.id}_{self.name}.log"
        self.log_file = None
        self.last_active_timestamp = None
        self.channel_manager = channel_manager
        self.log_path.parent.mkdir(exist_ok=True)

    def build_command(self) -> List[str]:
        # Get channel config
        channel_config = next((ch for ch in self.channel_manager.config.get("channels", []) 
                            if ch['id'] == self.id), {})
        
        # Get mode and validate
        mode = channel_config.get('mode', 'listener')
        port = config['srt_base_port'] + self.id
        
        # Get SRT options and replace placeholders
        srt_options = config.get('srt_options', '')
        srt_options = srt_options.replace('{srt_mode}', mode)
        
        # Build SRT URL based on mode
        if mode == 'caller':
            # Validate required fields for Caller mode
            remote_ip = channel_config.get('remote_ip')
            remote_port = channel_config.get('remote_port')
            
            if not remote_ip or not remote_port:
                raise ValueError(f"Channel {self.name}: remote_ip and remote_port are required for Caller mode")
                
            srt_url = f"srt://{remote_ip}:{remote_port}{srt_options}"
            # Add local port binding for caller mode
            if 'localaddr' not in srt_url:
                srt_url = f"srt://{remote_ip}:{remote_port}{srt_options}&localaddr=0.0.0.0:{self.local_port}"
        else:  # Default to Listener mode
            srt_url = f"srt://0.0.0.0:{port}{srt_options}"

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
        logging.info(f"Comando para canal {self.name} (modo {mode}): {' '.join(command)}")
        return command

    async def start(self):
        if self.process and self.process.poll() is None:
            logging.info(f"El proceso para el canal {self.name} ya está activo.")
            return

        command = self.build_command()
        try:
            # Asegurarse de que el directorio de logs existe
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Abrir archivo de log para escritura
            self.log_file = open(self.log_path, 'w', buffering=1)  # Line buffering
            
            logging.info(f"Iniciando proceso para canal {self.name} con comando: {' '.join(command)}")
            
            # Iniciar el proceso con buffer de línea
            self.process = subprocess.Popen(
                command,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffering
                universal_newlines=True
            )
            
            if not self.process:
                raise Exception("No se pudo crear el proceso")
                
            self.status = "listening"
            logging.info(f"Proceso para canal {self.name} iniciado con PID: {self.process.pid}")
            
            # Iniciar tarea para leer la salida del proceso
            asyncio.create_task(self.read_output())
            
            # Notificar a los clientes WebSocket sobre el cambio de estado
            await self.channel_manager.broadcast_status()
            
        except Exception as e:
            logging.exception(f"Error al iniciar el proceso para el canal {self.name}: {str(e)}")
            self.status = "error"
            await self.channel_manager.broadcast_status()
            if self.log_file and not self.log_file.closed:
                self.log_file.close()
                self.log_file = None

    async def read_output(self):
        """Lee y registra la salida del proceso ffmpeg"""
        try:
            # Leer el archivo desde el principio para no perder líneas
            last_position = 0
            
            while True:
                if self.process is None or self.process.poll() is not None:
                    break
                    
                try:
                    with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        # Ir a la última posición leída
                        f.seek(last_position)
                        
                        # Leer nuevas líneas
                        lines = f.readlines()
                        
                        # Actualizar la última posición
                        last_position = f.tell()
                        
                        # Procesar cada línea
                        for line in lines:
                            line = line.strip()
                            if line:
                                logging.debug(f"[{self.name}] {line}")
                                
                                # Detectar si hay video activo (frame= y (fps= o bitrate=))
                                if "frame=" in line and ("fps=" in line or "bitrate=" in line):
                                    prev_status = self.status
                                    self.status = "active"
                                    self.last_active_timestamp = time.time()
                                    
                                    # Notificar a los clientes WebSocket solo si el estado cambió
                                    if prev_status != "active":
                                        await self.channel_manager.broadcast_status()
                                        logging.info(f"Canal {self.name} detectado como ACTIVO (video recibido)")
                                
                except FileNotFoundError:
                    # El archivo de log aún no existe, esperar un momento
                    pass
                except Exception as e:
                    logging.error(f"Error al leer el archivo de log para {self.name}: {str(e)}")
                
                # Pequeña pausa para no saturar la CPU
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logging.error(f"Error en read_output para {self.name}: {str(e)}")
            
        finally:
            # Si el proceso terminó inesperadamente, actualizar el estado
            if self.process and self.process.poll() is not None:
                self.status = "error"
                await self.channel_manager.broadcast_status()

    async def stop(self):
        if self.process and self.process.poll() is None:
            try:
                # Primero actualizamos el estado a "stopping" para el feedback visual
                prev_status = self.status
                self.status = "stopping"
                await self.channel_manager.broadcast_status()
                
                logging.info(f"Deteniendo proceso del canal {self.name}")
                self.process.terminate()
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logging.warning(f"Forzando terminación del proceso para el canal {self.name}")
                    self.process.kill()
                    self.process.wait()
            except Exception as e:
                logging.error(f"Error al detener el proceso del canal {self.name}: {e}")
            finally:
                if self.log_file:
                    self.log_file.close()
                    self.log_file = None
                self.process = None
                self.status = "inactive"
                logging.info(f"Canal {self.name} detenido exitosamente")

    async def restart(self):
        await self.stop()
        await self.start()

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
        self.config = config  # Añadir referencia a la configuración global

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_websockets.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_websockets.remove(websocket)

    async def broadcast_status(self):
        if not self.active_websockets:
            return
            
        # Obtener el estado actual de todos los canales
        message = self.get_all_statuses()
        
        # Crear una lista para almacenar las tareas de envío
        tasks = []
        
        # Crear una tarea de envío para cada websocket activo
        for ws in self.active_websockets:
            try:
                # Crear una copia del mensaje para cada websocket
                task = asyncio.create_task(ws.send_json(message))
                tasks.append(task)
            except Exception as e:
                logging.error(f"Error al enviar mensaje a WebSocket: {e}")
                continue
        
        # Esperar a que todas las tareas de envío terminen
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=5.0,  # Tiempo máximo de espera
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Manejar excepciones de las tareas completadas
            for task in done:
                try:
                    await task  # Esto lanzará cualquier excepción que haya ocurrido
                except Exception as e:
                    logging.error(f"Error en tarea de envío WebSocket: {e}")
            
            # Cancelar cualquier tarea pendiente
            for task in pending:
                task.cancel()

    async def start_all(self):
        tasks = [channel.start() for channel in self.channels.values()]
        await asyncio.gather(*tasks)

    async def monitor_processes(self):
        while True:
            status_changed = False
            for channel in self.channels.values():
                # 1. Comprobar si el proceso se ha caído (código de retorno no nulo)
                if channel.process is None or channel.process.poll() is not None:
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

    def get_next_channel_id(self):
        if not self.channels:
            return 1
        return max(channel.id for channel in self.channels.values()) + 1
        
    async def add_channel(self, channel_data: dict):
        # Generate new channel ID
        new_id = self.get_next_channel_id()
        
        # Prepare channel config
        channel_config = {
            'id': new_id,
            'name': channel_data['name'],
            'mode': channel_data['mode'],
            'enabled': True,
            'local_port': int(channel_data['local_port'])
        }
        
        # Add remote config if in caller mode
        if channel_data['mode'] == 'caller':
            channel_config.update({
                'remote_ip': channel_data['remote_ip'],
                'remote_port': int(channel_data['remote_port'])
            })
        
        # Add to config file
        self.save_channel_to_config(channel_config)
        
        # Reload configuration to ensure we have the latest data
        global config
        config = load_config()
        self.config = config  # keep internal reference in sync
        
        # Create and start channel
        channel = ChannelManager(channel_config, self)
        self.channels[new_id] = channel
        
        # Start the channel
        await channel.start()
        
        # Broadcast the update to all connected clients
        await self.broadcast_status()
        
        return new_id
        
    def save_channel_to_config(self, new_channel):
        # Load current config
        with open("config.json", "r") as f:
            config_data = json.load(f)
        
        # Add new channel
        if 'channels' not in config_data:
            config_data['channels'] = []
            
        # Remove if channel with same ID exists (shouldn't happen with auto-increment)
        config_data['channels'] = [ch for ch in config_data['channels'] if ch['id'] != new_channel['id']]
        config_data['channels'].append(new_channel)
        
        # Save back to file
        with open("config.json", "w") as f:
            json.dump(config_data, f, indent=4)
        
        # Update global config
        global config
        config = config_data

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
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} no encontrado")

    try:
        await channel.restart()
        return {"status": "success", "message": f"Canal {channel_id} reiniciado"}
    except Exception as e:
        logging.error(f"Error al reiniciar el canal {channel_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/start/{channel_id}")
async def start_channel(channel_id: int):
    channel = channel_manager.channels.get(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} no encontrado")

    try:
        await channel.start()
        return {"status": "success", "message": f"Canal {channel_id} iniciado"}
    except Exception as e:
        logging.error(f"Error al iniciar el canal {channel_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stop/{channel_id}")
async def stop_channel(channel_id: int):
    # Verificar si el canal existe en el administrador de canales
    if channel_id not in channel_manager.channels:
        # Verificar si el canal existe en la configuración pero no está cargado
        channel_config = next((c for c in config['channels'] if c.get('id') == channel_id), None)
        if channel_config:
            detail = f"El canal {channel_id} está en la configuración pero no está actualmente cargado. Intente reiniciar la aplicación."
        else:
            detail = f"No se encontró ningún canal con ID {channel_id} en la configuración actual."
        
        # Registrar el error para depuración
        logging.warning(detail)
        logging.warning(f"Canales cargados: {list(channel_manager.channels.keys())}")
        
        raise HTTPException(
            status_code=404, 
            detail=detail
        )

    channel = channel_manager.channels[channel_id]
    
    try:
        # Verificar si el canal ya está detenido
        if not channel.process or channel.process.returncode is not None:
            return {
                "status": "success", 
                "message": f"El canal {channel_id} ya estaba detenido",
                "already_stopped": True
            }
            
        # Detener el canal
        await channel.stop()
        
        return {
            "status": "success", 
            "message": f"Canal {channel_id} detenido correctamente",
            "already_stopped": False
        }
        
    except Exception as e:
        error_msg = f"Error inesperado al detener el canal {channel_id}: {str(e)}"
        logging.error(error_msg, exc_info=True)
        
        # Intentar forzar la detención si hay un error
        try:
            if channel and hasattr(channel, 'process') and channel.process:
                channel.process.terminate()
                channel.process.wait(timeout=5)
                return {
                    "status": "success",
                    "message": f"Canal {channel_id} detenido forzosamente",
                    "forced_stop": True
                }
        except Exception as force_error:
            logging.error(f"Error al forzar la detención del canal {channel_id}: {force_error}")
        
        raise HTTPException(
            status_code=500, 
            detail=error_msg
        )

@app.post("/api/channels")
async def create_channel(request: Request):
    try:
        data = await request.json()
        
        # Validate required fields
        required_fields = ['name', 'mode', 'local_port']
        for field in required_fields:
            if field not in data:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        # Validate mode
        if data['mode'] not in ['listener', 'caller']:
            raise HTTPException(status_code=400, detail="Invalid mode. Must be 'listener' or 'caller'")
            
        # Validate remote config for caller mode
        if data['mode'] == 'caller':
            if 'remote_ip' not in data or 'remote_ip' not in data:
                raise HTTPException(status_code=400, detail="remote_ip and remote_port are required for Caller mode")
        
        # Add the new channel
        try:
            channel_id = await channel_manager.add_channel(data)
            return {"success": True, "channel_id": channel_id}
            
        except Exception as e:
            logging.exception("Error adding channel")
            raise HTTPException(status_code=500, detail=f"Error adding channel: {str(e)}")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON data")
    except Exception as e:
        logging.exception("Unexpected error in create_channel")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: int):
    # Buscar el canal
    channel = channel_manager.channels.get(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    
    try:
        # Detener el canal si está activo
        await channel.stop()
        
        # Cerrar el archivo de log si está abierto
        if hasattr(channel, 'log_file') and channel.log_file and not channel.log_file.closed:
            try:
                channel.log_file.close()
            except Exception as e:
                logging.warning(f"Error cerrando archivo de log: {e}")
        
        # Eliminar el archivo de log si existe
        log_dir = Path(config.get('log_directory', 'logs'))
        log_path = log_dir / f"channel_{channel_id}_{channel.name}.log"
        
        if log_path.exists():
            try:
                log_path.unlink()
                logging.info(f"Archivo de log eliminado: {log_path}")
            except Exception as e:
                logging.error(f"No se pudo eliminar el archivo de log {log_path}: {e}")
        
        # Eliminar el canal del config.json
        with open("config.json", "r") as f:
            config_data = json.load(f)
        
        # Filtrar el canal a eliminar
        config_data["channels"] = [ch for ch in config_data["channels"] if ch["id"] != channel_id]
        
        # Guardar los cambios
        with open("config.json", "w") as f:
            json.dump(config_data, f, indent=4)
        
        # Eliminar el canal del manager
        if channel_id in channel_manager.channels:
            del channel_manager.channels[channel_id]
        
        # Notificar a los clientes WebSocket
        await channel_manager.broadcast_status()
        
        return {"status": "success", "message": f"Canal {channel_id} eliminado correctamente"}
        
    except Exception as e:
        logging.error(f"Error al eliminar el canal {channel_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al eliminar el canal: {str(e)}")

@app.put("/api/channels/{channel_id}")
async def update_channel(channel_id: int, request: Request):
    # Get the channel
    channel = channel_manager.channels.get(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} no encontrado")
    
    try:
        data = await request.json()
        
        # Validate required fields
        if 'mode' not in data:
            raise HTTPException(status_code=400, detail="El campo 'mode' es requerido")
            
        # Validate mode
        if data['mode'] not in ['listener', 'caller']:
            raise HTTPException(status_code=400, detail="Modo inválido. Debe ser 'listener' o 'caller'")
            
        # Validate remote config for caller mode
        if data['mode'] == 'caller':
            if 'remote_ip' not in data or not data['remote_ip']:
                raise HTTPException(status_code=400, detail="remote_ip es requerido para el modo Caller")
            if 'remote_port' not in data or not data['remote_port']:
                raise HTTPException(status_code=400, detail="remote_port es requerido para el modo Caller")
            try:
                port = int(data['remote_port'])
                if port < 1 or port > 65535:
                    raise ValueError("Puerto fuera de rango")
            except ValueError:
                raise HTTPException(status_code=400, detail="Puerto remoto inválido. Debe ser un número entre 1 y 65535")
        
        # Load current config
        with open("config.json", "r") as f:
            config_data = json.load(f)
            
        # Find and update the channel config
        channel_updated = False
        for ch in config_data["channels"]:
            if ch["id"] == channel_id:
                # Update mode and name
                ch["mode"] = data['mode']
                
                # Update name if provided
                if 'name' in data and data['name']:
                    ch["name"] = data['name']
                    
                # Update remote config for caller mode
                if data['mode'] == 'caller':
                    ch["remote_ip"] = data['remote_ip']
                    ch["remote_port"] = int(data['remote_port'])
                else:
                    # Remove remote_ip and remote_port for listener mode
                    ch.pop("remote_ip", None)
                    ch.pop("remote_port", None)
                    
                channel_updated = True
                break
                
        if not channel_updated:
            raise HTTPException(status_code=404, detail=f"Canal {channel_id} no encontrado en la configuración")
            
        # Save updated config
        with open("config.json", "w") as f:
            json.dump(config_data, f, indent=4)
            
        # Update channel in memory
        channel.mode = data['mode']
        if 'name' in data and data['name']:
            channel.name = data['name']
        if data['mode'] == 'caller':
            channel.remote_ip = data['remote_ip']
            channel.remote_port = int(data['remote_port'])
        else:
            channel.remote_ip = None
            channel.remote_port = None
            
        # Restart channel with new config
        await channel.restart()
        
        # Broadcast status update to all connected clients
        await channel_manager.broadcast_status()
        
        return {"status": "success", "message": f"Configuración del canal {channel_id} actualizada correctamente"}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Datos JSON inválidos")
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error al actualizar el canal {channel_id}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# --- Servir Frontend ---
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse('frontend/index.html')