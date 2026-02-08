const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = parseInt(process.env.PORT, 10) || 8080;
const HOST = '0.0.0.0'; // Railway requires binding to 0.0.0.0
const DIST = path.join(__dirname, 'dist', 'skf-site', 'browser');
const INDEX = path.join(DIST, 'index.html');

// ── Startup checks ──
console.log(`[startup] Node ${process.version}`);
console.log(`[startup] PORT=${PORT}  HOST=${HOST}`);
console.log(`[startup] DIST=${DIST}`);
console.log(`[startup] DIST exists: ${fs.existsSync(DIST)}`);
console.log(`[startup] index.html exists: ${fs.existsSync(INDEX)}`);

if (!fs.existsSync(INDEX)) {
  console.error('[FATAL] index.html not found — build may have failed');
  process.exit(1);
}

// Enable gzip compression
try {
  const compression = require('compression');
  app.use(compression());
  console.log('[startup] compression enabled');
} catch {
  console.log('[startup] compression not available, skipping');
}

// Health check endpoint (Railway uses this to verify the app is alive)
app.get('/healthz', (req, res) => res.status(200).send('ok'));

// Serve static files with long-term caching for hashed assets
app.use(
  express.static(DIST, {
    maxAge: '1y',
    index: 'index.html',
    setHeaders(res, filePath) {
      if (filePath.endsWith('index.html')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
    },
  })
);

// SPA fallback — any non-file route serves index.html
app.use(async (req, res) => {
  res.setHeader('Cache-Control', 'no-cache');
  try {
    await res.sendFile(INDEX);
  } catch (err) {
    console.error('[error] sendFile failed:', err.message);
    if (!res.headersSent) {
      res.status(500).send('Server error');
    }
  }
});

// ── Start listening ──
const server = app.listen(PORT, HOST, () => {
  console.log(`[ready] SKF Racing Hub listening on http://${HOST}:${PORT}`);
});

server.on('error', (err) => {
  console.error('[FATAL] Server failed to start:', err.message);
  process.exit(1);
});
