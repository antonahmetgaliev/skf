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

// The login's tokens live in localStorage, where any script running on the page
// can read them — so only our own scripts (and Google Analytics) may run here.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' https://*.googletagmanager.com",
  // Angular adds component styles as <style> elements.
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  // Avatars, driver photos and stream thumbnails come from other sites.
  "img-src 'self' data: https:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ');

app.use((req, res, next) => {
  res.setHeader('Content-Security-Policy', CONTENT_SECURITY_POLICY);
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  next();
});

// Health check endpoint (Railway uses this to verify the app is alive)
app.get('/healthz', (req, res) => res.status(200).send('ok'));

// Runtime browser config, read by src/app/env.ts. Served to every visitor, so it must only ever
// carry public values — never secrets. Registered before express.static so it wins over any
// public/env.js that a local build copied into dist.
const BROWSER_ENV = {
  GA_MEASUREMENT_ID: process.env.GA_MEASUREMENT_ID || '',
};

console.log(
  `[startup] GA_MEASUREMENT_ID=${BROWSER_ENV.GA_MEASUREMENT_ID || '(unset — analytics disabled)'}`
);

app.get('/env.js', (req, res) => {
  res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.send(`window.SKF_ENV = ${JSON.stringify(BROWSER_ENV)};`);
});

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
      // The OAuth state cookie is the only one the backend sets.
      cookieDomainRewrite: '',
      cookiePathRewrite: '/',
      on: {
        proxyReq: (proxyReq, req) => {
          // Preserve the original host so the backend knows the public domain
          proxyReq.setHeader('X-Forwarded-Host', req.headers.host);
          proxyReq.setHeader('X-Forwarded-Proto', req.protocol);
        },
        // Paths only: a query string can carry an OAuth code.
        proxyRes: (proxyRes, req) => {
          console.log(`[proxy] ${req.method} ${req.path} ← ${proxyRes.statusCode}`);
        },
        error: (err, req, res) => {
          console.error(`[proxy] ERROR ${req.method} ${req.path}:`, err.code || err.message);
          if (!res.headersSent) {
            res.status(502).json({ error: 'Backend unavailable' });
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
