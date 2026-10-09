"""Pack ai/awe-game-designer/ into static/ai/awe-game-designer.zip (deterministic bytes).

Run: python -m ai.build_skill_zip
"""
import io
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "awe-game-designer")
OUT = os.path.join(os.path.dirname(HERE), "static", "ai", "awe-game-designer.zip")


def build_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for root, _dirs, files in sorted(os.walk(SKILL_DIR)):
            for fname in sorted(files):
                full = os.path.join(root, fname)
                arc = os.path.join("awe-game-designer", os.path.relpath(full, SKILL_DIR)).replace(os.sep, "/")
                info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o644 << 16
                with open(full, "rb") as f:
                    zf.writestr(info, f.read().replace(b"\r\n", b"\n"))
    return buf.getvalue()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(build_zip_bytes())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
