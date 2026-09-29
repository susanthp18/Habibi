// Prerender every route into dist/client/<route>/index.html, with the route's
// head (title, description, canonical, Open Graph, JSON-LD), plus sitemap.xml.
// Run after both vite builds (see `npm run build`).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const client = path.join(root, "dist/client");
const serverEntry = path.join(root, "dist/server/entry-server.js");

const { render, routes, site, faqs } = await import(pathToFileURL(serverEntry).href);
const template = fs.readFileSync(path.join(client, "index.html"), "utf8");

const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
const json = (o) => JSON.stringify(o).replace(/</g, "\\u003c");
const ld = (o) =>
  `<script type="application/ld+json">${json({ "@context": "https://schema.org", ...o })}</script>`;
const abs = (p) => new URL(p, site.url + "/").href;

function crumbName(route) {
  return route.nav ?? route.title;
}

function head(route) {
  const url = abs(route.path);
  const image = abs(site.ogImage);
  const tags = [
    `<title>${esc(route.title)}</title>`,
    `<meta name="description" content="${esc(route.description)}" />`,
    `<link rel="canonical" href="${url}" />`,
    `<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="${esc(site.name)}" />`,
    `<meta property="og:title" content="${esc(route.title)}" />`,
    `<meta property="og:description" content="${esc(route.description)}" />`,
    `<meta property="og:url" content="${url}" />`,
    `<meta property="og:image" content="${image}" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${esc(route.title)}" />`,
    `<meta name="twitter:description" content="${esc(route.description)}" />`,
    `<meta name="twitter:image" content="${image}" />`,
    `<meta name="theme-color" content="#f7f9fb" />`,
  ];
  if (route.path === "/") {
    tags.push(
      ld({
        "@type": "Organization",
        name: site.name,
        legalName: site.legalName,
        url: site.url,
        logo: abs("/favicon.svg"),
        email: site.email,
        description: site.orgDescription,
      }),
      ld({ "@type": "WebSite", name: site.name, url: site.url }),
      ld({
        "@type": "SoftwareApplication",
        name: site.name,
        applicationCategory: "BusinessApplication",
        operatingSystem: site.operatingSystem,
        url: site.url,
        description: site.appDescription,
      }),
    );
  } else {
    tags.push(
      ld({
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: abs("/") },
          { "@type": "ListItem", position: 2, name: crumbName(route), item: url },
        ],
      }),
    );
  }
  const qa = faqs[route.path];
  if (qa?.length) {
    tags.push(
      ld({
        "@type": "FAQPage",
        mainEntity: qa.map(([q, a]) => ({
          "@type": "Question",
          name: q,
          acceptedAnswer: { "@type": "Answer", text: a },
        })),
      }),
    );
  }
  return tags.join("\n    ");
}

for (const route of routes) {
  const html = template
    .replace("<!--app-head-->", head(route))
    .replace("<!--app-html-->", render(route.path));
  const dir = path.join(client, route.path);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), html);
  console.log("prerendered", route.path);
}

const today = new Date().toISOString().slice(0, 10);
const urls = routes
  .map(
    (r) =>
      `  <url><loc>${abs(r.path)}</loc><lastmod>${today}</lastmod><changefreq>monthly</changefreq><priority>${r.priority.toFixed(1)}</priority></url>`,
  )
  .join("\n");
fs.writeFileSync(
  path.join(client, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
);
fs.rmSync(path.join(root, "dist/server"), { recursive: true, force: true });
console.log("sitemap.xml:", routes.length, "urls");
