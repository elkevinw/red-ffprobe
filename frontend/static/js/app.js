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

                // Guardar los canales en window.channels para acceso global
                window.channels = Array.isArray(channels) ? [...channels] : [channels];

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
            
            const isActive = channel.status && (channel.status.toLowerCase() === 'active' || channel.status.toLowerCase() === 'activo');
            const statusClass = isActive ? 'active' : getStatusClass(channel.status);
            const statusText = isActive ? 'Activo' : (channel.status || 'UNKNOWN').toUpperCase();
            
            const row = document.createElement('tr');
            row.id = `channel-${channel.id}`;
            row.classList.add('status-row', statusClass);
            
            row.innerHTML = `
                <td>${channel.name || 'Canal sin nombre'}</td>
                <td>
                    <span class="status-text">
                        <span class="status-indicator ${statusClass}"></span>
                        ${statusText}
                    </span>
                </td>
                <td>${channel.pid || 'N/A'}</td>
                <td class="action-buttons">
                    <button class="start-btn ${isActive ? 'active' : ''}" data-id="${channel.id}">
                        ${isActive ? 'Activo' : 'Reiniciar'}
                    </button>
                    <button class="restart-btn ${isActive ? 'active' : ''}" data-id="${channel.id}">
                        ${isActive ? 'Activo' : 'Stop'}
                    </button>
                    <button class="configure-btn" data-id="${channel.id}">
                        Configurar
                    </button>
                </td>
            `;
            
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

    function updateChannelStatus(channelId, status) {
        const row = document.getElementById(`channel-${channelId}`);
        if (!row) return;

        // Actualizar el texto del estado
        const statusCell = row.querySelector('.status-text');
        if (statusCell) {
            const statusText = status === "active" ? "Activo" : status.toUpperCase();
            statusCell.innerHTML = `
                <span class="status-indicator"></span>
                ${statusText}
            `;
        }

        // Actualizar la clase del estado
        const statusIndicator = row.querySelector('.status-indicator');
        if (statusIndicator) {
            statusIndicator.className = "status-indicator";
            statusIndicator.classList.add(status === "active" ? "active" : getStatusClass(status));
        }

        // Actualizar el botón
        const buttons = row.querySelectorAll('.action-buttons button');
        buttons.forEach(button => {
            // Eliminar clases anteriores
            button.classList.remove('inactive', 'listening', 'error', 'crashed');
            
            // Agregar clase y texto según el estado
            if (status === "active") {
                button.classList.add('active');
                button.textContent = "Activo";
            } else {
                button.classList.add(getStatusClass(status));
                button.textContent = status === "listening" ? "Escuchando" : status === "error" ? "Error" : "Stop";
            }
        });
    }

    // Manejador de eventos para los botones
    document.addEventListener('click', function(event) {
        if (event.target && event.target.classList.contains('restart-btn')) {
            const channelId = event.target.getAttribute('data-id');
            const row = event.target.closest('tr');
            console.log(`Reiniciando canal ${channelId}...`);
            
            // Mostrar indicador de carga
            const statusCell = row.querySelector('.status-cell');
            statusCell.innerHTML = '<span class="status-indicator loading"></span> Reiniciando...';
            
            // Enviar solicitud para reiniciar el canal
            fetch(`/api/channels/${channelId}/restart`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    console.log(`Canal ${channelId} reiniciado:`, data);
                    // La actualización vendrá a través de WebSocket
                })
                .catch(error => {
                    console.error(`Error al reiniciar el canal ${channelId}:`, error);
                    statusCell.innerHTML = '<span class="status-indicator error"></span> Error';
                });
        } else if (event.target && event.target.classList.contains('configure-btn')) {
            const channelId = event.target.getAttribute('data-id');
            const channel = window.channels.find(c => c.id === parseInt(channelId));
            
            if (channel) {
                // Llenar el formulario con los datos del canal
                document.getElementById('configChannelId').value = channel.id;
                document.getElementById('channelNameDisplay').textContent = channel.name || '';
                document.getElementById('channelName').value = channel.name || '';
                
                // Establecer el modo
                const mode = channel.mode || 'listener';
                document.querySelector(`input[name="mode"][value="${mode}"]`).checked = true;
                
                // Mostrar/ocultar configuración remota según el modo
                const remoteConfig = document.getElementById('remoteConfig');
                remoteConfig.classList.toggle('hidden', mode !== 'caller');
                
                // Si hay configuración remota, llenar los campos
                if (mode === 'caller' && channel.remote_ip && channel.remote_port) {
                    document.getElementById('remoteIp').value = channel.remote_ip;
                    document.getElementById('remotePort').value = channel.remote_port;
                }
                
                // Mostrar el modal
                document.getElementById('channelConfigModal').style.display = 'block';
            }
        }
    });

    // Manejar cambio de modo
    document.querySelectorAll('input[name="mode"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const remoteConfig = document.getElementById('remoteConfig');
            remoteConfig.classList.toggle('hidden', this.value !== 'caller');
        });
    });

    // Manejar envío del formulario
    document.getElementById('channelConfigForm').addEventListener('submit', function(e) {
        e.preventDefault();
        
        const channelId = document.getElementById('configChannelId').value;
        const channelName = document.getElementById('channelName').value;
        const mode = document.querySelector('input[name="mode"]:checked').value;
        
        const configData = {
            name: channelName,
            mode: mode
        };
        
        // Agregar configuración remota solo si el modo es caller
        if (mode === 'caller') {
            configData.remote_ip = document.getElementById('remoteIp').value;
            configData.remote_port = parseInt(document.getElementById('remotePort').value);
            
            // Validar campos requeridos
            if (!configData.remote_ip || !configData.remote_port) {
                alert('Por favor complete la dirección IP y puerto remoto para el modo Caller');
                return;
            }
        }
        
        // Enviar la configuración al servidor
        fetch(`/api/channels/${channelId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(configData)
        })
        .then(response => response.json())
        .then(data => {
            console.log('Configuración guardada:', data);
            // Cerrar el modal
            document.getElementById('channelConfigModal').style.display = 'none';
            // La actualización de la tabla vendrá a través de WebSocket
        })
        .catch(error => {
            console.error('Error al guardar la configuración:', error);
            alert('Error al guardar la configuración: ' + error.message);
        });
    });

    // Cerrar el modal al hacer clic en la X
    document.querySelector('.close').addEventListener('click', function() {
        document.getElementById('channelConfigModal').style.display = 'none';
    });

    // Cerrar el modal al hacer clic en Cancelar
    document.getElementById('cancelConfig').addEventListener('click', function() {
        document.getElementById('channelConfigModal').style.display = 'none';
    });

    // Cerrar el modal al hacer clic fuera del contenido
    window.addEventListener('click', function(event) {
        const modal = document.getElementById('channelConfigModal');
        if (event.target === modal) {
            modal.style.display = 'none';
        }
    });

    // Add event listener for the new channel button
    const addChannelBtn = document.getElementById('addChannelBtn');
    const addChannelModal = document.getElementById('addChannelModal');
    const addChannelForm = document.getElementById('addChannelForm');
    const closeAddChannelBtn = document.getElementById('closeAddChannel');
    const cancelAddChannelBtn = document.getElementById('cancelAddChannel');
    const newModeRadios = document.querySelectorAll('input[name="newMode"]');
    const newRemoteConfig = document.getElementById('newRemoteConfig');

    // Show add channel modal
    addChannelBtn.addEventListener('click', () => {
        addChannelForm.reset();
        addChannelModal.style.display = 'block';
        // Reset remote config visibility based on default selected mode
        newRemoteConfig.classList.add('hidden');
        document.getElementById('newRemoteIp').required = false;
        document.getElementById('newRemotePort').required = false;
    });

    // Close add channel modal
    closeAddChannelBtn.addEventListener('click', () => {
        addChannelModal.style.display = 'none';
    });

    cancelAddChannelBtn.addEventListener('click', () => {
        addChannelModal.style.display = 'none';
    });

    // Toggle remote config visibility based on mode selection
    newModeRadios.forEach(radio => {
        radio.addEventListener('change', function() {
            const isCaller = this.value === 'caller';
            newRemoteConfig.classList.toggle('hidden', !isCaller);
            document.getElementById('newRemoteIp').required = isCaller;
            document.getElementById('newRemotePort').required = isCaller;
        });
    });

    // Handle form submission for new channel
    addChannelForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const channelData = {
            name: document.getElementById('newChannelName').value,
            mode: document.querySelector('input[name="newMode"]:checked').value,
            local_port: parseInt(document.getElementById('localPort').value)
        };
        
        if (channelData.mode === 'caller') {
            channelData.remote_ip = document.getElementById('newRemoteIp').value;
            channelData.remote_port = parseInt(document.getElementById('newRemotePort').value);
        }
        
        // Send request to create new channel
        fetch('/api/channels', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(channelData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Close the modal
                addChannelModal.style.display = 'none';
                // The WebSocket will handle the update of the channels list
            } else {
                alert('Error al crear el canal: ' + (data.error || 'Error desconocido'));
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error al crear el canal: ' + error.message);
        });
    });

    // Close modal when clicking outside of it
    window.addEventListener('click', function(event) {
        if (event.target === addChannelModal) {
            addChannelModal.style.display = 'none';
        }
    });

    // Inicializar DataTable y conectar WebSocket
    initializeDataTable();
    connect();
});