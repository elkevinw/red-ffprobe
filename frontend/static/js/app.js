document.addEventListener('DOMContentLoaded', () => {
    const API_URL = '/api/srt/status'; // Corregido: esta es la ruta correcta
    const POLLING_INTERVAL = 5000; // 5 segundos

    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const lastUpdated = document.getElementById('last-updated');
    const ffprobeData = document.getElementById('ffprobe-data');
    const errorCard = document.getElementById('error-card');
    const errorMessage = document.getElementById('error-message');

    // Función para obtener y actualizar el estado
    async function fetchStatus() {
        try {
            const response = await fetch(API_URL);
            if (!response.ok) {
                throw new Error(`Error en la API: ${response.statusText}`);
            }
            const data = await response.json();

            updateUI(data);

        } catch (error) {
            console.error('Error al obtener el estado:', error);
            showError('No se pudo conectar con el backend. Revisa que esté en ejecución.');
        }
    }

    // Función para actualizar la interfaz de usuario
    function updateUI(data) {
        // Actualizar estado (activo/inactivo)
        statusIndicator.classList.remove('active', 'inactive');
        if (data.is_active) {
            statusText.textContent = 'Activo';
            statusIndicator.classList.add('active');
            errorCard.style.display = 'none';
        } else {
            statusText.textContent = 'Inactivo';
            statusIndicator.classList.add('inactive');
            showError(data.error_message || 'La señal no está activa.');
        }

        // Actualizar fecha de última actualización
        lastUpdated.textContent = data.last_updated || 'N/A';

        // Actualizar datos de ffprobe
        if (data.ffprobe_data) {
            ffprobeData.textContent = JSON.stringify(data.ffprobe_data, null, 2);
        } else {
            ffprobeData.textContent = 'No hay datos disponibles.';
        }
    }

    // Función para mostrar errores
    function showError(message) {
        errorMessage.textContent = message;
        errorCard.style.display = 'block';
    }

    // Iniciar el polling
    fetchStatus(); // Primera llamada inmediata
    setInterval(fetchStatus, POLLING_INTERVAL);
});
