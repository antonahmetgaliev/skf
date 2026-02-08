const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 8080;
const DIST = path.join(__dirname, 'dist', 'skf-site', 'browser');

// Enable gzip compression for all responses
const compression = (() => { try { return require('compression'); } catch { return null; } })();
if (compression) app.use(compression());

// Serve static files with caching for hashed assets
app.use(
  express.static(DIST, {
    maxAge: '1y',
    setHeaders(res, filePath) {
      // Don't cache index.html so deploys take effect immediately
      if (filePath.endsWith('index.html')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
    },
  })
);

// SPA fallback — all routes serve index.html (Angular handles routing)
app.use((req, res, next) => {
  // If no static file matched, serve index.html for SPA routing
  res.sendFile(path.join(DIST, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`SKF Racing Hub running on port ${PORT}`);
});
