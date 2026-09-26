/**
 * `next/link` for the ported AgentStudio screens: a real anchor (so middle
 * click and "open in new tab" work) that navigates client-side on a plain
 * click, with the engine UI's paths mapped under STUDIO_BASE.
 */
import { useNavigate, useRouter } from "@tanstack/react-router";
import { forwardRef, type AnchorHTMLAttributes, type MouseEvent } from "react";

import { toHostPath } from "../base";

type Href = string | { pathname?: string; query?: Record<string, string | number | undefined> };

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  href: Href;
  replace?: boolean;
  prefetch?: boolean | null;
  scroll?: boolean;
  shallow?: boolean;
}

function toString(href: Href): string {
  if (typeof href === "string") return href;
  const qs = new URLSearchParams(
    Object.entries(href.query ?? {})
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return `${href.pathname ?? ""}${qs ? `?${qs}` : ""}`;
}

const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  {
    href,
    replace,
    prefetch: _prefetch,
    scroll: _scroll,
    shallow: _shallow,
    onClick,
    target,
    ...rest
  },
  ref,
) {
  const navigate = useNavigate();
  const basepath = useRouter().options.basepath ?? "/";
  const raw = toString(href);
  const internal = raw.startsWith("/") && !raw.startsWith("//");
  const hostHref = internal ? toHostPath(raw) : raw;
  const anchorHref = internal ? `${basepath.replace(/\/$/, "")}${hostHref}` : hostHref;

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (
      !internal ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (target && target !== "_self")
    ) {
      return;
    }
    event.preventDefault();
    void navigate({ href: hostHref, replace });
  }

  // Content arrives through `rest.children`, as with next/link.
  // eslint-disable-next-line jsx-a11y/anchor-has-content
  return <a ref={ref} href={anchorHref} target={target} onClick={handleClick} {...rest} />;
});

export default Link;
