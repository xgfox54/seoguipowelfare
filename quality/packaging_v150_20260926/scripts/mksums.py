import sys, pathlib
sys.stdout.reconfigure(encoding="utf-8")
raw = pathlib.Path(r"C:\Users\xgfox\Documents\Codex\2026-09-24\new-chat-2\work\sha150_raw.txt").read_text(encoding="utf-8-sig").splitlines()
lines = []
for l in raw:
    if not l.strip():
        continue
    h, size, path = l.split("|", 2)
    p = pathlib.Path(path)
    if p.parent.name == "dist":
        lines.append(f"{h} *{p.name}")
out = pathlib.Path(r"C:\Users\xgfox\Documents\Codex\seoguipowelfare-v1.5.0\dist\SHA256SUMS_v1.5.0.txt")
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(out.read_text(encoding="utf-8"))

