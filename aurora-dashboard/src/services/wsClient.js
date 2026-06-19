class WSClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.callbacks = {};
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 10;
    this.reconnectDelay = 1000;
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    console.log('Connecting to WebSocket:', this.url);
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket connected successfully');
      this.reconnectAttempts = 0;
      this._trigger('open', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      this._trigger('close', {});
      this.tryReconnect();
    };
  }

  tryReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), 30000);
      console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
      setTimeout(() => this.connect(), delay);
    } else {
      console.error('Max reconnection attempts reached');
    }
  }

  handleMessage(data) {
    if (data.type && this.callbacks[data.type]) {
      this.callbacks[data.type].forEach(cb => {
        try {
          cb(data.payload);
        } catch (e) {
          console.error('Callback error:', e);
        }
      });
    }
  }

  _trigger(type, data) {
    if (this.callbacks[type]) {
      this.callbacks[type].forEach(cb => {
        try {
          cb(data);
        } catch (e) {
          console.error('Callback error:', e);
        }
      });
    }
  }

  on(type, callback) {
    if (!this.callbacks[type]) {
      this.callbacks[type] = [];
    }
    this.callbacks[type].push(callback);
  }

  off(type, callback) {
    if (!this.callbacks[type]) return;
    this.callbacks[type] = this.callbacks[type].filter(cb => cb !== callback);
  }

  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

const WS_URL = 'ws://localhost:8000';

export const wsClient = new WSClient(WS_URL);

export default wsClient;