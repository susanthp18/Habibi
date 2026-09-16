const SRC = `${import.meta.env.BASE_URL}brand/bigtapp.png`;

/** Company plate — same mark the landing nav uses. */
export function BigtappMark({ size = 22 }: { size?: number }) {
  return (
    <a
      href="https://bigtapp.ai"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Bigtapp home"
      className="shrink-0"
    >
      <img src={SRC} alt="" width={size} height={size} className="rounded-small" />
    </a>
  );
}
