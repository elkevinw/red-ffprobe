document.addEventListener('DOMContentLoaded', () => {
    const channelsContainer = document.getElementById('channels-container');
    const statusMessage = document.getElementById('status-message');
    let socket;

    function connect() {
        // Asegura que la URL del WebSocket sea correcta para tu entorno
        const wsUrl = `ws://${window.location.host}/ws`;
        socket = new WebSocket(wsUrl);

        socket.onopen = function() {
            console.log("WebSocket connection established.");
            if (statusMessage) {
                statusMessage.textContent = 'Connected to server...';
                statusMessage.className = 'status-connected';
            }
        };

        socket.onmessage = function(event) {
            try {
                const channels = JSON.parse(event.data);
                console.log("Received data:", channels);

                if (Array.isArray(channels)) {
                    channels.forEach(updateOrCreateChannelCard);
                } else {
                    updateOrCreateChannelCard(channels);
                }
            } catch (error) {
                console.error("Error processing message:", error);
            }
        };

        socket.onclose = function(event) {
            console.log('WebSocket connection closed. Reconnecting in 3 seconds...', event.reason);
            if (statusMessage) {
                statusMessage.textContent = 'Connection lost. Reconnecting...';
                statusMessage.className = 'status-disconnected';
            }
            setTimeout(connect, 3000);
        };

        socket.onerror = function(error) {
            console.error('WebSocket error:', error);
            socket.close();
        };
    }

    function updateOrCreateChannelCard(channel) {
        if (!channel || typeof channel.id === 'undefined') {
            console.error("Invalid channel data received:", channel);
            return;
        }

        let card = document.getElementById(`channel-${channel.id}`);

        if (!card) {
            card = document.createElement('div');
            card.id = `channel-${channel.id}`;
            channelsContainer.appendChild(card);
        }

        // Map backend status to CSS classes
        let statusClass = '';
        if (channel.status === 'activo') {
            statusClass = 'active';
        } else if (channel.status === 'listening') {
            statusClass = 'listening';
        } else if (channel.status) {
            statusClass = channel.status.toLowerCase();
        }

        // Set classes for the main card for border colors and reset previous ones
        card.className = 'channel-card';
        if (statusClass) {
            card.classList.add(statusClass);
        }

        card.innerHTML = `
            <div class="card-header">
                <h2 class="channel-name">${channel.name || 'Unnamed Channel'}</h2>
                <div class="status-indicator ${statusClass}"></div>
            </div>
            <div class="card-body">
                <p><strong>Status:</strong> <span class="status-text">${(channel.status || 'UNKNOWN').toUpperCase()}</span></p>
                <p><strong>PID:</strong> ${channel.pid || 'N/A'}</p>
            </div>
            <div class="card-footer">
                <button class="start-btn" data-id="${channel.id}">start</button>
                <button class="restart-btn" data-id="${channel.id}">stop</button>
            </div>
        `;
    }

    channelsContainer.addEventListener('click', function(event) {
        if (event.target && event.target.classList.contains('restart-btn')) {
            const channelId = event.target.getAttribute('data-id');
            console.log(`Restarting channel ${channelId}...`);
            fetch(`/api/restart/${channelId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => console.log(data.message))
                .catch(error => console.error('Error restarting channel:', error));
        }
        if (event.target && event.target.classList.contains('start-btn')) {
            const channelId = event.target.getAttribute('data-id');
            console.log(`Starting channel ${channelId}...`);
            fetch(`/api/start/${channelId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => console.log(data.message))
                .catch(error => console.error('Error starting channel:', error));
        }
    });

    connect();
});
