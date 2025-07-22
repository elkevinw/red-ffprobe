document.addEventListener('DOMContentLoaded', () => {
    const channelsBody = document.getElementById('channels-body');
    const statusMessage = document.getElementById('status-message');
    let socket;
    let dataTable;

    // Inicializar DataTable
    function initializeDataTable() {
        dataTable = $('#channels-table').DataTable({
            responsive: true,
            pageLength: 25,
            order: [[0, 'asc']],
            language: {
                search: "Buscar:",
                lengthMenu: "Mostrar _MENU_ canales por página",
                zeroRecords: "No se encontraron canales",
                info: "Mostrando _PAGE_ de _PAGES_",
                infoEmpty: "No hay canales disponibles",
                infoFiltered: "(filtrado de _MAX_ canales en total)",
                paginate: {
                    first: "Primero",
                    last: "Último",
                    next: "Siguiente",
                    previous: "Anterior"
                }
            }
        });
    }

    function connect() {
        const wsUrl = `ws://${window.location.host}/ws`;
        socket = new WebSocket(wsUrl);

        socket.onopen = function() {
            console.log("WebSocket connection established.");
            if (statusMessage) {
                statusMessage.textContent = 'Conectado al servidor';
                statusMessage.className = 'status-connected';
            }
        };

        socket.onmessage = function(event) {
            try {
                const channels = JSON.parse(event.data);
                console.log("Datos recibidos:", channels);

                if (Array.isArray(channels)) {
                    updateChannelsTable(channels);
                } else {
                    updateChannelsTable([channels]);
                }
            } catch (error) {
                console.error("Error al procesar el mensaje:", error);
            }
        };

        socket.onclose = function(event) {
            console.log('Conexión WebSocket cerrada. Reconectando en 3 segundos...', event.reason);
            if (statusMessage) {
                statusMessage.textContent = 'Conexión perdida. Reconectando...';
                statusMessage.className = 'status-disconnected';
            }
            setTimeout(connect, 3000);
        };

        socket.onerror = function(error) {
            console.error('Error en WebSocket:', error);
            socket.close();
        };
    }

    function updateChannelsTable(channels) {
        // Limpiar la tabla actual
        if (dataTable) {
            dataTable.clear().destroy();
        }
        
        // Ordenar canales por nombre
        channels.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
        
        // Llenar la tabla con los datos actualizados
        const tableBody = document.getElementById('channels-body');
        tableBody.innerHTML = ''; // Limpiar el cuerpo de la tabla
        
        channels.forEach(channel => {
            if (!channel || typeof channel.id === 'undefined') {
                console.error("Datos de canal no válidos:", channel);
                return;
            }
            
            const statusClass = getStatusClass(channel.status);
            const statusText = (channel.status || 'UNKNOWN').toUpperCase();
            
            const row = document.createElement('tr');
            row.id = `channel-${channel.id}`;
            row.classList.add('status-row', statusClass);
            
            row.innerHTML = `
                <td>${channel.name || 'Canal sin nombre'}</td>
                <td>
                    <span class="status-text">
                        <span class="status-indicator"></span>
                        ${statusText}
                    </span>
                </td>
                <td>${channel.pid || 'N/A'}</td>
                <td class="action-buttons">
                    <button class="start-btn" data-id="${channel.id}">Reiniciar</button>
                    <button class="restart-btn" data-id="${channel.id}">Stop</button>
                    
                </td>
            `;
            
            // Aplicar la clase al indicador después de crear el elemento
            const indicator = row.querySelector('.status-indicator');
            if (indicator) {
                indicator.classList.add(statusClass);
            }
            
            tableBody.appendChild(row);
        });
        
        // Re-inicializar DataTable
        initializeDataTable();
    }
    
    function getStatusClass(status) {
        if (!status) return 'inactive';
        
        const statusLower = status.toLowerCase();
        if (statusLower === 'activo' || statusLower === 'active') return 'active';
        if (statusLower === 'listening' || statusLower === 'escuchando') return 'listening';
        if (statusLower.includes('error') || statusLower.includes('fail') || statusLower.includes('caído')) return 'crashed';
        return 'inactive';
    }

    // Manejador de eventos para los botones
    document.addEventListener('click', function(event) {
        if (event.target && event.target.classList.contains('restart-btn')) {
            const channelId = event.target.getAttribute('data-id');
            const row = event.target.closest('tr');
            console.log(`Deteniendo canal ${channelId}...`);
            
            // Deshabilitar el botón para evitar múltiples clics
            const stopButton = event.target;
            stopButton.disabled = true;
            stopButton.textContent = 'Deteniendo...';
            
            // Actualizar el estado visualmente de inmediato
            const statusCell = row.querySelector('.status-text');
            if (statusCell) {
                statusCell.innerHTML = `
                    <span class="status-indicator inactive"></span>
                    DETENIENDO...
                `;
            }
            
            fetch(`/api/stop/${channelId}`, { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw new Error(err.error || 'Error al detener el canal');
                    });
                }
                return response.json();
            })
            .then(data => {
                console.log('Respuesta del servidor:', data);
                showNotification(`Canal ${channelId} detenido correctamente`, 'success');
                
                // Forzar una actualización del estado
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ action: 'update_status' }));
                }
            })
            .catch(error => {
                console.error('Error al detener el canal:', error);
                if (statusCell) {
                    statusCell.innerHTML = `
                        <span class="status-indicator crashed"></span>
                        ERROR
                    `;
                }
                showNotification(`Error al detener el canal: ${error.message}`, 'error');
            })
            .finally(() => {
                // Restaurar el botón después de un tiempo
                setTimeout(() => {
                    stopButton.disabled = false;
                    stopButton.textContent = 'Stop';
                }, 2000);
            });
        }
        
        if (event.target && event.target.classList.contains('start-btn')) {
            const channelId = event.target.getAttribute('data-id');
            const row = event.target.closest('tr');
            console.log(`Reiniciando canal ${channelId}...`);
            
            // Deshabilitar el botón para evitar múltiples clics
            const restartButton = event.target;
            restartButton.disabled = true;
            restartButton.textContent = 'Reiniciando...';
            
            // Actualizar el estado visualmente de inmediato
            const statusCell = row.querySelector('.status-text');
            if (statusCell) {
                statusCell.innerHTML = `
                    <span class="status-indicator listening"></span>
                    REINICIANDO...
                `;
            }
            
            fetch(`/api/start/${channelId}`, { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => {
                        throw new Error(err.error || 'Error al reiniciar el canal');
                    });
                }
                return response.json();
            })
            .then(data => {
                console.log(data.message);
                // Forzar una actualización del estado después de reiniciar
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ action: 'update_status' }));
                }
            })
            .catch(error => {
                console.error('Error al reiniciar el canal:', error);
                // Mostrar mensaje de error
                if (statusCell) {
                    statusCell.innerHTML = `
                        <span class="status-indicator crashed"></span>
                        ERROR
                    `;
                }
                // Mostrar notificación de error
                showNotification(`Error al reiniciar el canal: ${error.message}`, 'error');
            })
            .finally(() => {
                // Restaurar el botón
                restartButton.disabled = false;
                restartButton.textContent = 'Reiniciar';
            });
        }
    });

    // Inicializar la tabla y la conexión WebSocket
    initializeDataTable();
    connect();
});