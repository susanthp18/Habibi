# PayInt marketing site

The public pages at `https://beeonixpayint.bigtapp.net/` (everything except `/app/`,
`/login` and the API). React 19 + Vite, prerendered to one static HTML file per route,
animated with GSAP. No server runtime: production serves `dist/client` from a pinned
nginx container (`deploy/cloudunity/site-production.sh`).

```bash
npm ci
npm run dev       # http://localhost:5173, client-rendered
npm run build     # dist/client: prerendered pages + hashed assets + sitemap.xml
npm run preview   # serve the production build
```

## Layout

| Path | What it holds |
|---|---|
| `src/site.js` | Company facts used across pages (URL, email, JSON-LD text) |
| `src/routes.js` | Every page: path, title, meta description, nav/footer placement |
| `src/data/modules.js` | The product modules, grouped as in the app sidebar. The module count on every page is computed from this list, so keep it in step with `Habibi/src/components/shell/Sidebar.tsx` |
| `src/data/faqs.js` | FAQ entries per page (also emitted as FAQPage JSON-LD) |
| `src/components/` | Header, footer, brand marks, the helix, and the shared section blocks in `ui.jsx` |
| `src/pages/` | One file per route |
| `src/fx.js` | Scroll reveals, counters and video play/pause (off for reduced motion and `?still`) |
| `scripts/prerender.mjs` | Renders each route into `dist/client/<route>/index.html` with its head tags |
| `public/` | Videos, posters, brand images, favicon, robots.txt |

`site-production.sh` refuses a bundle that is missing any route, is a dev build, or is
not prerendered, so add new routes there as well as in `src/routes.js`.

Append `?still` to any URL to render it with all motion settled (screenshots, print).
