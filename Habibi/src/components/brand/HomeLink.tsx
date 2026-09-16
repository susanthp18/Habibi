import type { ReactNode, MouseEvent } from "react";

/**
 * Leaves the console for the public site at `/`.
 * A plain `<a href="/">` is swallowed by the router when the app is mounted
 * at `/app`, so this always does a real navigation.
 */
export function HomeLink({
  className,
  children = "Home",
}: {
  className?: string;
  children?: ReactNode;
}) {
  const go = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    window.location.assign("/");
  };

  return (
    <a href="/" className={className} onClick={go}>
      {children}
    </a>
  );
}
