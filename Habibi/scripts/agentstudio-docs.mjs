/**
 * AgentStudio help: the engine's documentation (agentstudio/engine/docs,
 * Mintlify MDX, BSD-2) rendered to white-labelled HTML at port time.
 *
 * Output:
 *   src/agentstudio/docs.generated.ts   navigation + page HTML (vendored tree)
 *   public/agentstudio-docs/images/      the images those pages reference
 *
 * Mintlify components become plain HTML (callouts, accordions, cards, tabs);
 * links to other help pages point at /studio/docs/<slug>; the vendor's name,
 * hosted-service links and video embeds are removed. Pages about installing,
 * deploying or contributing to the engine, and about the vendor's own hosted
 * services, are not part of AgentStudio help (EXCLUDE).
 */
import fs from "node:fs";
import path from "node:path";

import { Marked } from "marked";

const EXCLUDE = new Set([
  "getting-started/index",
  "getting-started/prerequisites",
  "getting-started/troubleshooting",
  "integrations/telephony/dograh-sip",
  "developer/environment-variables",
]);
// The engine's REST reference is internal here: the engine sits behind the gateway.
const EXCLUDE_GROUPS = new Set([
  "Contribution",
  "SDKs",
  "Deployment",
  "Resources",
  "Authentication & Errors",
]);

const CALLOUTS = ["Note", "Tip", "Info", "Warning", "Check", "Danger"];
const BLOCK_WRAPPERS = ["AccordionGroup", "CodeGroup", "Tabs", "Steps", "Frame", "Columns"];

function attr(tag, name) {
  const m = tag.match(new RegExp(`${name}=(?:"([^"]*)"|'([^']*)'|\\{["'\`]([^"'\`]*)["'\`]\\})`));
  return m ? (m[1] ?? m[2] ?? m[3]) : undefined;
}

function whiteLabel(text) {
  return (
    text
      .replace(/https?:\/\/app\.dograh\.com\/?/g, "/studio/")
      .replace(/https?:\/\/(?:api\.)?dograh\.com/g, "https://<your-payint-host>")
      .replace(/https?:\/\/[a-z.]*dograh\.(?:com|ai)[^\s)"'`]*/g, "#")
      .replace(/\b(?:app\.)?dograh\.com\b/g, "PayInt Voice Studio")
      // "Dograh-managed" too; "X-Dograh-*" header names are real and stay.
      .replace(/(?<![-\w/.])Dograh(?!\w)/g, "PayInt Voice Studio")
  );
}

/** Resolve a doc link (absolute, relative, or docs.dograh.com) to a slug, else null. */
function docSlug(href, fromSlug) {
  let p = href.replace(/^https?:\/\/docs\.dograh\.com/, "");
  const hash = p.includes("#") ? p.slice(p.indexOf("#")) : "";
  p = p.replace(/#.*$/, "").replace(/\.mdx?$/, "");
  if (/^[a-z]+:/i.test(p) || p === "") return null;
  if (!p.startsWith("/")) p = path.posix.join(path.posix.dirname(fromSlug), p);
  return { slug: path.posix.normalize(p).replace(/^\/+/, ""), hash };
}

function convert(mdx, slug, images) {
  // Video embeds reach third-party hosts; they span lines, so drop them first.
  const lines = mdx
    .replace(/\r\n/g, "\n")
    .replace(/<iframe[\s\S]*?(?:<\/iframe>|\/>)/g, "")
    .split("\n");
  const out = [];
  let depth = 0;
  let fence = null;
  for (let raw of lines) {
    // Content nested in components is indented; undo that so Markdown does
    // not read it as an indented code block.
    const lead = raw.match(/^ */)[0].length;
    let line = raw.slice(Math.min(lead, depth * 2));
    const trimmed = line.trim();
    if (fence) {
      if (trimmed.startsWith(fence)) fence = null;
      out.push(whiteLabel(line));
      continue;
    }
    const open = trimmed.match(/^(`{3,}|~{3,})/);
    if (open) {
      fence = open[1];
      out.push(whiteLabel(line));
      continue;
    }
    line = line.replace(/<iframe[\s\S]*?<\/iframe>/g, "").replace(/<Stream\b[^>]*\/?>/g, "");
    line = line.replace(/<\/?([A-Z][A-Za-z]*)\b([^>]*?)(\/?)>/g, (tag, name, attrs, selfClose) => {
      const closing = tag.startsWith("</");
      if (CALLOUTS.includes(name)) {
        if (closing) return (depth--, "\n\n</div>\n\n");
        depth++;
        return `\n\n<div class="as-callout as-callout-${name.toLowerCase()}">\n\n`;
      }
      if (name === "Accordion") {
        if (closing) return (depth--, "\n\n</details>\n\n");
        depth++;
        return `\n\n<details class="as-accordion"><summary>${whiteLabel(attr(attrs, "title") ?? "Details")}</summary>\n\n`;
      }
      if (name === "CardGroup") {
        if (closing) return (depth--, "\n\n</div>\n\n");
        depth++;
        return '\n\n<div class="as-cards">\n\n';
      }
      if (name === "Card") {
        if (closing) return (depth--, "\n\n</div>\n\n");
        const title = whiteLabel(attr(attrs, "title") ?? "");
        const href = attr(attrs, "href");
        const target = href ? docSlug(href, slug) : null;
        const heading = target
          ? `<a class="as-card-title" href="/studio/docs/${target.slug}${target.hash}">${title}</a>`
          : `<strong class="as-card-title">${title}</strong>`;
        if (selfClose) return `\n\n<div class="as-card">${heading}</div>\n\n`;
        depth++;
        return `\n\n<div class="as-card">${heading}\n\n`;
      }
      if (name === "Tab" || name === "Step") {
        if (closing) return (depth--, "\n\n");
        depth++;
        return `\n\n#### ${whiteLabel(attr(attrs, "title") ?? "")}\n\n`;
      }
      if (BLOCK_WRAPPERS.includes(name)) {
        if (!selfClose) depth += closing ? -1 : 1;
        return "\n\n";
      }
      return tag; // not a Mintlify component (e.g. <TwiML> in prose): leave as text
    });
    line = line.replace(
      /(!\[[^\]]*\]\(|src=["'])((?:\.\.\/)+images\/|\/images\/)([^)"'\s]+)/g,
      (m, lead2, _dir, file) => {
        images.add(file);
        return `${lead2}/agentstudio-docs/images/${file}`;
      },
    );
    line = line.replace(/\]\(([^)\s]+)\)/g, (m, href) => {
      if (href.startsWith("/agentstudio-docs/") || href.startsWith("#")) return m;
      if (/^https?:\/\/(?!docs\.dograh\.com)/.test(href)) return m;
      const target = docSlug(href, slug);
      return target ? `](/studio/docs/${target.slug}${target.hash})` : m;
    });
    out.push(whiteLabel(line));
  }
  return out.join("\n");
}

function headingId(text) {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function navFromDocsJson(docsJson) {
  const groups = [];
  const walk = (node, groupName, include) => {
    if (typeof node === "string") {
      if (include && !EXCLUDE.has(node)) groups.at(-1).pages.push(node);
      return;
    }
    const name = node.group ?? node.tab ?? "";
    const keep = include && !EXCLUDE_GROUPS.has(name);
    const isTopGroup = node.group && !groupName;
    if (isTopGroup && keep) groups.push({ group: name, pages: [] });
    for (const key of ["tabs", "groups", "pages"]) {
      for (const child of node[key] ?? []) walk(child, isTopGroup ? name : groupName, keep);
    }
  };
  walk(docsJson.navigation, "", true);
  return groups.filter((g) => g.pages.length > 0);
}

export function portDocs({ engineRoot, habibiRoot }) {
  const docsRoot = path.join(engineRoot, "docs");
  const docsJson = JSON.parse(fs.readFileSync(path.join(docsRoot, "docs.json"), "utf8"));
  const nav = navFromDocsJson(docsJson);
  const images = new Set();
  const marked = new Marked({
    gfm: true,
    renderer: {
      heading({ tokens, depth }) {
        const inner = this.parser.parseInline(tokens);
        return `<h${depth} id="${headingId(inner)}">${inner}</h${depth}>\n`;
      },
    },
  });

  const pages = {};
  for (const group of nav) {
    for (const slug of group.pages) {
      const file = path.join(docsRoot, `${slug}.mdx`);
      if (!fs.existsSync(file)) continue;
      const source = fs.readFileSync(file, "utf8");
      const fm = source.match(/^---\n([\s\S]*?)\n---\n?/);
      const front = fm ? fm[1] : "";
      const title = whiteLabel((front.match(/^title:\s*["']?(.*?)["']?\s*$/m) ?? [])[1] ?? slug);
      const description = whiteLabel(
        (front.match(/^description:\s*["']?(.*?)["']?\s*$/m) ?? [])[1] ?? "",
      );
      const body = convert(fm ? source.slice(fm[0].length) : source, slug, images);
      pages[slug] = { title, description, html: marked.parse(body) };
    }
  }
  const navOut = nav.map((g) => ({
    group: whiteLabel(g.group),
    pages: g.pages.filter((s) => pages[s]).map((s) => ({ slug: s, title: pages[s].title })),
  }));

  const outFile = path.join(habibiRoot, "src/agentstudio/docs.generated.ts");
  fs.writeFileSync(
    outFile,
    "// Generated by scripts/agentstudio-docs.mjs from agentstudio/engine/docs. Do not edit.\n" +
      `export const DOCS_NAV: { group: string; pages: { slug: string; title: string }[] }[] = ${JSON.stringify(navOut, null, 1)};\n` +
      `export const DOCS_PAGES: Record<string, { title: string; description: string; html: string }> = ${JSON.stringify(pages)};\n`,
  );

  const imgOut = path.join(habibiRoot, "public/agentstudio-docs/images");
  fs.rmSync(imgOut, { recursive: true, force: true });
  let copied = 0;
  for (const rel of images) {
    const src = path.join(docsRoot, "images", rel);
    if (!fs.existsSync(src)) continue;
    const dest = path.join(imgOut, rel);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
    copied++;
  }
  return { pages: Object.keys(pages).length, images: copied };
}
