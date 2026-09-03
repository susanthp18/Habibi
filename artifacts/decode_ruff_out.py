import pathlib

p = pathlib.Path(r"D:\Hackathon\artifacts")
names = [
    "ruff-e402-ignoressqa.txt",
    "ruff-f-ignoressqa.txt",
    "ruff-wider.txt",
    "ruff-e402-entrypoints.txt",
    "ruff-stats.txt",
    "ruff-f-stats.txt",
    "ruff-concise.txt",
]
out = p / "ruff-decoded.md"
chunks = []
for name in names:
    f = p / name
    b = f.read_bytes() if f.exists() else b""
    chunks.append(f"## {name} (bytes={len(b)})\n")
    text = None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "cp1252"):
        try:
            text = b.decode(enc)
            chunks.append(f"_decoded as {enc}_\n\n")
            break
        except Exception:
            continue
    if text is None:
        chunks.append(f"_undecodable; head hex: {b[:40].hex()}_\n\n")
    else:
        chunks.append("```\n" + text[:12000] + ("\n...TRUNC...\n" if len(text) > 12000 else "") + "```\n\n")
out.write_text("".join(chunks), encoding="utf-8")
print("wrote", out, "chars", sum(len(c) for c in chunks))
