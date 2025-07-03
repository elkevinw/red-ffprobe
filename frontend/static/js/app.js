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
        dataTable.clear().destroy();
        
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
            row.className = statusClass;
            
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
                    <button class="start-btn" data-id="${channel.id}">Iniciar</button>
                    <button class="restart-btn" data-id="${channel.id}">Detener</button>
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
        if (statusLower === 'activo') return 'active';
        if (statusLower === 'listening') return 'listening';
        if (statusLower.includes('error') || statusLower.includes('fail')) return 'crashed';
        return 'inactive';
    }

    // Manejador de eventos para los botones
    document.addEventListener('click', function(event) {
        if (event.target && event.target.classList.contains('restart-btn')) {
            const channelId = event.target.getAttribute('data-id');
            console.log(`Deteniendo canal ${channelId}...`);
            fetch(`/api/restart/${channelId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => console.log(data.message))
                .catch(error => console.error('Error al detener el canal:', error));
        }
        
        if (event.target && event.target.classList.contains('start-btn')) {
            const channelId = event.target.getAttribute('data-id');
            console.log(`Iniciando canal ${channelId}...`);
            fetch(`/api/start/${channelId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => console.log(data.message))
                .catch(error => console.error('Error al iniciar el canal:', error));
        }
    });

    // Inicializar la tabla y la conexión WebSocket
    initializeDataTable();
    connect();
});
