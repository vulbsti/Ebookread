"""Import-time metadata and cover extraction for FB2, CBZ, MOBI/AZW3 and PDF.

Pure Python (plus GdkPixbuf for thumbnails), safe to run in a worker thread. Anything
that can't be read here is filled in by foliate-js the first time the book is opened.
"""

from __future__ import annotations

import base64
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
THUMB_MAX = (360, 540)


@dataclass
class FormatInfo:
    title: str | None = None
    author: str | None = None
    language: str | None = None
    cover: bytes | None = None


# ====================================================================== thumbnails


def save_cover(data: bytes | None, dest_dir: Path, key: str) -> str | None:
    """Store a cover thumbnail (scaled to fit THUMB_MAX) and return its path."""
    if not data:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pix = loader.get_pixbuf()
        if pix is None:
            return None
        w, h = pix.get_width(), pix.get_height()
        scale = min(1.0, THUMB_MAX[0] / w, THUMB_MAX[1] / h)
        if scale < 1.0:
            pix = pix.scale_simple(max(1, int(w * scale)), max(1, int(h * scale)), GdkPixbuf.InterpType.BILINEAR)
        out = dest_dir / f"{key}.png" if pix.get_has_alpha() else dest_dir / f"{key}.jpg"
        if pix.get_has_alpha():
            pix.savev(str(out), "png", [], [])
        else:
            pix.savev(str(out), "jpeg", ["quality"], ["88"])
        return str(out)
    except Exception:  # noqa: BLE001 - not an image we can decode: no cover rather than a crash
        return None


# ====================================================================== FB2


def read_fb2(path: Path) -> FormatInfo:
    root = ET.parse(path).getroot()
    ns = {"fb": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"fb": ""}
    q = (lambda tag: f"fb:{tag}") if ns["fb"] else (lambda tag: tag)
    info = FormatInfo()
    ti = root.find(f"{q('description')}/{q('title-info')}", ns)
    if ti is None:
        return info
    info.title = (ti.findtext(q("book-title"), default="", namespaces=ns) or "").strip() or None
    authors = []
    for a in ti.findall(q("author"), ns):
        parts = [(a.findtext(q(p), default="", namespaces=ns) or "").strip()
                 for p in ("first-name", "middle-name", "last-name")]
        name = " ".join(p for p in parts if p) or (a.findtext(q("nickname"), default="", namespaces=ns) or "").strip()
        if name:
            authors.append(name)
    info.author = ", ".join(authors) or None
    info.language = (ti.findtext(q("lang"), default="", namespaces=ns) or "").strip() or None

    image = ti.find(f"{q('coverpage')}/{q('image')}", ns)
    if image is not None:
        href = next((v for k, v in image.attrib.items() if k.endswith("href")), "")
        if href.startswith("#"):
            for binary in root.findall(q("binary"), ns):
                if binary.get("id") == href[1:]:
                    try:
                        info.cover = base64.b64decode("".join((binary.text or "").split()))
                    except ValueError:
                        pass
                    break
    return info


# ====================================================================== CBZ


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def comic_pages(zf: zipfile.ZipFile) -> list[str]:
    names = [
        n for n in zf.namelist()
        if n.lower().endswith(IMAGE_EXTS) and not n.startswith("__MACOSX/") and not Path(n).name.startswith(".")
    ]
    return sorted(names, key=_natural_key)


def read_cbz(path: Path) -> FormatInfo:
    info = FormatInfo()
    with zipfile.ZipFile(path) as zf:
        pages = comic_pages(zf)
        if pages:
            info.cover = zf.read(pages[0])
        meta_name = next((n for n in zf.namelist() if n.lower().endswith("comicinfo.xml")), None)
        if meta_name:
            try:
                ci = ET.fromstring(zf.read(meta_name))
                get = lambda tag: (ci.findtext(tag) or "").strip()  # noqa: E731
                series, number, title = get("Series"), get("Number"), get("Title")
                if title and series:
                    info.title = f"{series} #{number}: {title}" if number else f"{series}: {title}"
                elif series:
                    info.title = f"{series} #{number}" if number else series
                else:
                    info.title = title or None
                info.author = get("Writer") or None
                info.language = get("LanguageISO") or None
            except ET.ParseError:
                pass
    return info


# ====================================================================== MOBI / AZW3

EXTH_AUTHOR, EXTH_COVER, EXTH_THUMB, EXTH_TITLE, EXTH_LANGUAGE = 100, 201, 202, 503, 524


def read_mobi(path: Path) -> FormatInfo:
    """Title, author, language and cover from a Mobipocket/KF8 container's EXTH header."""
    data = path.read_bytes()
    info = FormatInfo()
    if len(data) < 86 or data[60:68] not in (b"BOOKMOBI", b"TEXtREAd"):
        return info
    count = struct.unpack_from(">H", data, 76)[0]
    offsets = [struct.unpack_from(">I", data, 78 + 8 * i)[0] for i in range(count)]
    if not offsets:
        return info
    r0 = offsets[0]
    if data[r0 + 16:r0 + 20] != b"MOBI":
        name = data[:32].split(b"\0", 1)[0].decode("latin-1").replace("_", " ").strip()
        info.title = name or None
        return info

    mobi_len, _type, encoding = struct.unpack_from(">III", data, r0 + 20)
    codec = "utf-8" if encoding == 65001 else "cp1252"
    name_off, name_len = struct.unpack_from(">II", data, r0 + 0x54)
    first_image = struct.unpack_from(">I", data, r0 + 0x6C)[0]
    exth_flags = struct.unpack_from(">I", data, r0 + 0x80)[0]
    full_name = data[r0 + name_off:r0 + name_off + name_len].decode(codec, "replace").strip()
    info.title = full_name or None

    exth: dict[int, list[bytes]] = {}
    if exth_flags & 0x40:
        e = r0 + 16 + mobi_len
        if data[e:e + 4] == b"EXTH":
            n = struct.unpack_from(">I", data, e + 8)[0]
            pos = e + 12
            for _ in range(n):
                rtype, rlen = struct.unpack_from(">II", data, pos)
                if rlen < 8:
                    break
                exth.setdefault(rtype, []).append(data[pos + 8:pos + rlen])
                pos += rlen

    text = lambda k: [v.decode(codec, "replace").strip() for v in exth.get(k, []) if v.strip()]  # noqa: E731
    if text(EXTH_TITLE):
        info.title = text(EXTH_TITLE)[0]
    info.author = ", ".join(text(EXTH_AUTHOR)) or None
    info.language = (text(EXTH_LANGUAGE) or [None])[0]

    for key in (EXTH_COVER, EXTH_THUMB):
        if key in exth and len(exth[key][0]) == 4:
            idx = first_image + struct.unpack(">I", exth[key][0])[0]
            if first_image != 0xFFFFFFFF and idx < len(offsets):
                end = offsets[idx + 1] if idx + 1 < len(offsets) else len(data)
                info.cover = data[offsets[idx]:end]
                break
    return info


# ====================================================================== PDF

_INFO_REF = re.compile(rb"/Info\s+(\d+)\s+(\d+)\s+R")
_INFO_DICT = re.compile(rb"/Info\s*<<(.*?)>>", re.S)


def _pdf_string(raw: bytes) -> str | None:
    """Decode a PDF literal (...) or hex <...> string."""
    raw = raw.strip()
    if raw.startswith(b"<"):
        try:
            b = bytes.fromhex(raw[1:-1].decode("ascii"))
        except ValueError:
            return None
    else:
        body, out, i = raw[1:-1], bytearray(), 0
        esc = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
        while i < len(body):
            c = body[i:i + 1]
            if c == b"\\" and i + 1 < len(body):
                nxt = body[i + 1:i + 2]
                octal = re.match(rb"[0-7]{1,3}", body[i + 1:i + 4])
                if octal:
                    out.append(int(octal.group(0), 8) & 0xFF)
                    i += 1 + len(octal.group(0))
                    continue
                out += esc.get(nxt, nxt)
                i += 2
                continue
            out += c
            i += 1
        b = bytes(out)
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace").strip() or None
    return b.decode("latin-1").strip() or None


def _pdf_field(dict_bytes: bytes, key: bytes) -> str | None:
    m = re.search(rb"/" + key + rb"\s*(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>)", dict_bytes, re.S)
    return _pdf_string(m.group(1)) if m else None


def read_pdf(path: Path) -> FormatInfo:
    """Title/author from the document Info dictionary when it is stored uncompressed."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        data = fh.read() if size <= 8 * 1024 * 1024 else fh.read(2 * 1024 * 1024) + (
            fh.seek(-2 * 1024 * 1024, 2) or b"") + fh.read()
    info = FormatInfo()
    if not data.startswith(b"%PDF"):
        return info
    dict_bytes = None
    refs = _INFO_REF.findall(data)
    if refs:
        num, gen = refs[-1]
        m = re.search(rb"(?<![0-9])" + num + rb"\s+" + gen + rb"\s+obj\s*<<(.*?)>>\s*endobj", data, re.S)
        dict_bytes = m.group(1) if m else None
    if dict_bytes is None:
        m = _INFO_DICT.search(data)
        dict_bytes = m.group(1) if m else None
    if dict_bytes:
        info.title = _pdf_field(dict_bytes, b"Title")
        info.author = _pdf_field(dict_bytes, b"Author")
    return info


READERS = {".fb2": read_fb2, ".cbz": read_cbz, ".mobi": read_mobi, ".azw3": read_mobi, ".pdf": read_pdf}
