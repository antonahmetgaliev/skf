const express = require('express');
const path = require('path');
const fs = require('fs');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = parseInt(process.env.PORT, 10) || 8080;
const HOST = '0.0.0.0'; // Railway requires binding to 0.0.0.0
const DIST = path.join(__dirname, 'dist', 'skf-site', 'browser');
const INDEX = path.join(DIST, 'index.html');
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

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

// Proxy /api requests to the Python backend
console.log(`[startup] BACKEND_URL=${BACKEND_URL}`);

if (!BACKEND_URL || BACKEND_URL === 'http://localhost:8000') {
  console.warn('[startup] WARNING: BACKEND_URL is not set or using localhost fallback!');
  console.warn('[startup] Set BACKEND_URL env var to the backend internal URL.');
}

// Only set up proxy if we have a valid URL
try {
  new URL(BACKEND_URL);
  app.use(
    createProxyMiddleware({
      target: BACKEND_URL,
      changeOrigin: true,
      pathFilter: '/api/**',
      cookieDomainRewrite: '',
      cookiePathRewrite: '/',
      on: {
        proxyReq: (proxyReq, req) => {
          // Preserve the original host so the backend knows the public domain
          proxyReq.setHeader('X-Forwarded-Host', req.headers.host);
          proxyReq.setHeader('X-Forwarded-Proto', req.protocol);
          console.log(`[proxy] ${req.method} ${req.originalUrl} → ${BACKEND_URL}${req.originalUrl}`);
        },
        proxyRes: (proxyRes, req) => {
          console.log(`[proxy] ${req.method} ${req.originalUrl} ← ${proxyRes.statusCode}`);
        },
        error: (err, req, res) => {
          console.error(`[proxy] ERROR ${req.method} ${req.originalUrl}:`, err.code || err.message);
          if (!res.headersSent) {
            res.status(502).json({
              error: 'Backend unavailable',
              detail: err.code || err.message,
              target: BACKEND_URL,
            });
          }
        },
      },
    })
  );
  console.log(`[startup] /api proxy → ${BACKEND_URL}`);
} catch (urlErr) {
  console.error(`[startup] BACKEND_URL is not a valid URL: "${BACKEND_URL}"`);
  app.use('/api', (req, res) => {
    res.status(503).json({
      error: 'Backend not configured',
      detail: `BACKEND_URL="${BACKEND_URL}" is not a valid URL`,
    });
  });
}

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
