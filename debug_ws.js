const ws = new WebSocket('ws://localhost:8000');
const seen = new Set();

ws.addEventListener('open', () => {
  console.log('Connected to ws://localhost:8000');
});

ws.addEventListener('message', (event) => {
  try {
    const msg = JSON.parse(event.data);
    if (!seen.has(msg.type)) {
      seen.add(msg.type);
      console.log(`NEW type: ${msg.type}`);
      if (msg.type === 'trades') {
        console.log(`  Trades count: ${Array.isArray(msg.payload) ? msg.payload.length : 'NOT AN ARRAY'}`);
        if (Array.isArray(msg.payload) && msg.payload.length > 0) {
          console.log('  First trade:', JSON.stringify(msg.payload[0]).substring(0, 300));
        }
      }
    }
  } catch(e) {}
});

ws.addEventListener('error', (err) => {
  console.error('WS Error:', err.message || err);
});

// Wait 10 seconds
setTimeout(() => {
  console.log('\nAll message types seen:', [...seen].join(', '));
  console.log('Has trades:', seen.has('trades'));
  ws.close();
  process.exit(0);
}, 10000);
