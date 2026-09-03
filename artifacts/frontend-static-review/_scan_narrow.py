import os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = r"D:\Hackathon\Habibi\src"
categories = [
    ("@ts-ignore", re.compile(r"@ts-ignore")),
    ("@ts-expect-error", re.compile(r"@ts-expect-error")),
    ("@ts-nocheck", re.compile(r"@ts-nocheck")),
    ("as any", re.compile(r"\bas any\b")),
    (": any", re.compile(r": any\b")),
    ("as unknown as", re.compile(r"\bas unknown as\b")),
    ("as never", re.compile(r"\bas never\b")),
    ("from zod", re.compile(r"from ['\"]zod['\"]")),
    ("JSON.parse", re.compile(r"JSON\.parse")),
    ("from @/data/*-seed", re.compile(r"from ['\"]@/data/[^'\"]*-seed")),
]
hits = {name: [] for name, _ in categories}
nfiles = 0
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if d != "node_modules"]
    for fn in fns:
        if not fn.endswith((".ts", ".tsx")):
            continue
        nfiles += 1
        path = os.path.join(dp, fn)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    for name, rx in categories:
                        if rx.search(line):
                            hits[name].append("%s:%d:%s" % (path, i, line.rstrip()))
        except OSError as e:
            print("READ_ERROR", path, e)
print("SCANNED_FILES", nfiles)
for name, _ in categories:
    items = hits[name]
    print("===== %s (%d) =====" % (name, len(items)))
    for h in items:
        print(h)
print("===== TOTAL_MATCHES %d =====" % sum(len(v) for v in hits.values()))