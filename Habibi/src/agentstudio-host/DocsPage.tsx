/**
 * AgentStudio help. Pages are the engine's documentation, white-labelled and
 * rendered to HTML when the UI is ported (scripts/agentstudio-docs.mjs), so
 * the HTML is our own build output, not user content. Links between help
 * pages and to AgentStudio screens stay in-app.
 */
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, type MouseEvent } from "react";

import { DOCS_NAV, DOCS_PAGES } from "@/agentstudio/docs.generated";
import { cn } from "@/lib/utils";

const BASE = import.meta.env.BASE_URL;
const FIRST = DOCS_NAV[0]?.pages[0]?.slug ?? "";

/** Root-relative links and images in the generated HTML, under the app's base path. */
function withBase(html: string): string {
  return html
    .replaceAll('href="/studio/', `href="${BASE}studio/`)
    .replaceAll('src="/agentstudio-docs/', `src="${BASE}agentstudio-docs/`);
}

export default function DocsPage() {
  const params = useParams({ strict: false });
  const slug = (params._splat ?? "").replace(/\/$/, "") || FIRST;
  const page = DOCS_PAGES[slug];
  const navigate = useNavigate();
  const articleRef = useRef<HTMLElement>(null);
  const html = useMemo(() => (page ? withBase(page.html) : ""), [page]);

  useEffect(() => {
    articleRef.current?.parentElement?.scrollTo({ top: 0 });
  }, [slug]);

  function onArticleClick(event: MouseEvent<HTMLElement>) {
    const anchor = (event.target as HTMLElement).closest("a");
    const href = anchor?.getAttribute("href") ?? "";
    if (!anchor || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    if (href.startsWith("#")) {
      event.preventDefault();
      articleRef.current?.querySelector(href)?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    if (href.startsWith(`${BASE}studio/`)) {
      event.preventDefault();
      void navigate({ href: `/${href.slice(BASE.length)}` });
    }
  }

  return (
    <div className="flex min-h-full">
      <nav
        aria-label="Help topics"
        className="sticky top-0 hidden max-h-screen w-64 shrink-0 overflow-y-auto border-r border-border px-300 py-400 md:block"
      >
        {DOCS_NAV.map((group) => (
          <div key={group.group} className="mb-300">
            <p className="mb-100 text-body-small font-weight-bold-token text-text-subtle">
              {group.group}
            </p>
            <ul>
              {group.pages.map((p) => (
                <li key={p.slug}>
                  <Link
                    to="/studio/docs/$"
                    params={{ _splat: p.slug }}
                    className={cn(
                      "block rounded-small px-100 py-050 text-body-small hover:bg-background-neutral-subtle-hovered",
                      p.slug === slug ? "bg-background-selected text-text-selected" : "text-text",
                    )}
                  >
                    {p.title}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <main className="min-w-0 flex-1 px-600 py-500">
        {page ? (
          <>
            <h1 className="heading-large text-text">{page.title}</h1>
            {page.description ? (
              <p className="mt-100 text-body text-text-subtle">{page.description}</p>
            ) : null}
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- delegated handler for the links inside the generated help HTML; the links themselves are keyboard-operable */}
            <article
              ref={articleRef}
              className="as-doc mt-400 max-w-3xl"
              onClick={onArticleClick}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </>
        ) : (
          <div className="max-w-xl">
            <h1 className="heading-large text-text">Not part of Voice Studio help</h1>
            <p className="mt-100 text-body text-text-subtle">
              That topic covers the engine itself, not building agents in Voice Studio.
            </p>
            <Link
              to="/studio/docs/$"
              params={{ _splat: FIRST }}
              className="mt-200 inline-block text-body text-link"
            >
              Go to help
            </Link>
          </div>
        )}
      </main>
    </div>
  );
}
