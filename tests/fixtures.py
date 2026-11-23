"""Builds small, copyright-free test books in every supported format."""

from __future__ import annotations

import base64
import struct
import zipfile
import zlib
from pathlib import Path

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

XHTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{title}</title><link rel="stylesheet" href="style.css"/></head>
<body>{body}</body></html>"""


def _paras(tag: str, n: int = 40) -> str:
    return "".join(
        f"<p>{tag} paragraph {i}. The reader should lay this text out in comfortable lines, "
        f"turn pages smoothly, and remember exactly where it stopped.</p>"
        for i in range(n)
    )


def _png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write_epub(dest: Path, opf: str, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        for name, data in files.items():
            z.writestr(f"OEBPS/{name}", data)
    return dest


def epub3(dest: Path) -> Path:
    """EPUB 3: nested nav TOC, fragment target, footnote, external link, cover."""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:ebookread-fixture-epub3</dc:identifier>
    <dc:title>Fixture Three</dc:title><dc:creator>Ada Tester</dc:creator><dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch3" href="text/ch3.xhtml" media-type="application/xhtml+xml"/>
    <item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
  </manifest>
  <spine><itemref idref="ch1"/><itemref idref="ch2"/><itemref idref="ch3"/><itemref idref="notes"/></spine>
</package>"""
    nav = XHTML.format(title="Contents", body="""
<nav epub:type="toc"><ol>
  <li><a href="ch1.xhtml">Part One</a><ol>
    <li><a href="ch1.xhtml">One: Beginnings</a></li>
    <li><a href="ch2.xhtml">Two: Middles</a></li>
  </ol></li>
  <li><a href="text/ch3.xhtml">Part Two</a><ol>
    <li><a href="text/ch3.xhtml#late">Three: Late Section</a></li>
  </ol></li>
  <li><a href="notes.xhtml">Notes</a></li>
</ol></nav>""")
    ch1 = XHTML.format(title="One", body=(
        "<h1>One: Beginnings</h1>" + '<p id="inked" style="color:#000000">Inked black by the publisher.</p>'
        + _paras("Alpha", 30)
        + '<p>A claim that needs a source.<a epub:type="noteref" id="r1" href="notes.xhtml#n1">1</a></p>'
        + _paras("Alpha-tail", 30)))
    ch2 = XHTML.format(title="Two", body=(
        "<h1>Two: Middles</h1>" + _paras("Beta", 30)
        + '<p>Visit <a href="https://example.org/ebookread">the project page</a>.</p>' + _paras("Beta-tail", 30)))
    ch3 = XHTML.format(title="Three", body=(
        '<h1>Part Two</h1>' + _paras("Gamma", 40) + '<h2 id="late">Three: Late Section</h2>' + _paras("Delta", 30)
    )).replace('href="style.css"', 'href="../style.css"')
    notes = XHTML.format(title="Notes", body=(
        '<h1>Notes</h1><ol><li epub:type="endnote" id="n1"><p>1. The footnote text lives here.</p></li></ol>'
        + _paras("Notes-filler", 20)))
    return _write_epub(dest, opf, {
        "nav.xhtml": nav, "ch1.xhtml": ch1, "ch2.xhtml": ch2, "text/ch3.xhtml": ch3,
        "notes.xhtml": notes,
        "style.css": 'body { font-family: "DejaVu Sans Mono", monospace; } p { text-indent: 1.2em; }', "cover.png": _png(60, 90, (90, 40, 30)),
    })


def epub2_ncx(dest: Path) -> Path:
    """EPUB 2 with only an NCX table of contents."""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="uid">ebookread-fixture-epub2</dc:identifier>
    <dc:title>Fixture Two</dc:title><dc:creator opf:role="aut">Ben Tester</dc:creator><dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="c1.html" media-type="application/xhtml+xml"/>
    <item id="c2" href="c2.html" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""
    ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>Fixture Two</text></docTitle>
<navMap>
  <navPoint id="p1" playOrder="1"><navLabel><text>First Chapter</text></navLabel><content src="c1.html"/></navPoint>
  <navPoint id="p2" playOrder="2"><navLabel><text>Second Chapter</text></navLabel><content src="c2.html"/>
    <navPoint id="p3" playOrder="3"><navLabel><text>Second, Later Part</text></navLabel><content src="c2.html#later"/></navPoint>
  </navPoint>
</navMap></ncx>"""
    c1 = XHTML.format(title="c1", body="<h1>First Chapter</h1>" + _paras("Epsilon", 40))
    c2 = XHTML.format(title="c2", body="<h1>Second Chapter</h1>" + _paras("Zeta", 40)
                      + '<h2 id="later">Second, Later Part</h2>' + _paras("Eta", 30))
    return _write_epub(dest, opf, {"toc.ncx": ncx, "c1.html": c1, "c2.html": c2})


def epub_empty_metadata(dest: Path) -> Path:
    """Calibre-style export whose <metadata> element is empty."""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  </metadata>
  <manifest><item id="c1" href="c1.html" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    return _write_epub(dest, opf, {"c1.html": XHTML.format(title="c1", body="<h1>Untitled Export</h1>" + _paras("Theta", 20))})


def epub_malicious(dest: Path) -> Path:
    """Tries to run script three ways and reach the Python bridge."""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">evil</dc:identifier><dc:title>Evil</dc:title></metadata>
  <manifest>
    <item id="a" href="a.xhtml" media-type="application/xhtml+xml" properties="scripted"/>
    <item id="js" href="evil.js" media-type="application/javascript"/>
  </manifest>
  <spine><itemref idref="a"/></spine>
</package>"""
    beacon = "window.top.webkit.messageHandlers.ebookread.postMessage(JSON.stringify({type:'BOOK_SCRIPT_RAN', via:'%s'}))"
    body = (
        "<h1>Evil</h1><p>hello</p>"
        f'<img src="missing.png" onerror="{beacon % "onerror"}"/>'
        f"<script>{beacon % 'inline'}</script>"
        '<script src="evil.js"></script>'
        '<p><a id="ext" href="https://example.org/evil">external</a></p>'
    )
    return _write_epub(dest, opf, {"a.xhtml": XHTML.format(title="a", body=body), "evil.js": beacon % "file"})


def fb2(dest: Path) -> Path:
    paras = "".join(f"<p>FictionBook paragraph {i} with <emphasis>emphasis</emphasis>.</p>" for i in range(50))
    dest.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description><title-info><author><first-name>Fiona</first-name><last-name>Tester</last-name></author>
<book-title>Fixture FB2</book-title><lang>en</lang>
<coverpage><image l:href="#cover.png"/></coverpage></title-info></description>
<body><section><title><p>Chapter One</p></title>{paras}</section>
<section><title><p>Chapter Two</p></title>{paras}</section></body>
<binary id="cover.png" content-type="image/png">{base64.b64encode(_png(60, 90, (30, 90, 40))).decode()}</binary>
</FictionBook>""", encoding="utf-8")
    return dest


def cbz(dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w") as z:
        for i, col in enumerate([(200, 40, 40), (40, 160, 40), (40, 40, 200), (200, 200, 40)]):
            z.writestr(f"page{i + 1:02}.png", _png(300, 450, col))
    return dest


def cbz_comicinfo(dest: Path) -> Path:
    """Pages named so plain sorting is wrong (p10 before p2); metadata in ComicInfo.xml."""
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("p10.png", _png(30, 45, (0, 0, 255)))
        z.writestr("p2.png", _png(30, 45, (0, 255, 0)))
        z.writestr("p1.png", _png(30, 45, (255, 0, 0)))
        z.writestr("__MACOSX/._p1.png", b"junk")
        z.writestr("ComicInfo.xml", "<ComicInfo><Series>Fixture Saga</Series><Number>3</Number>"
                                    "<Title>Red Page</Title><Writer>Cara Tester</Writer></ComicInfo>")
    return dest


def mobi(dest: Path) -> Path:
    """Minimal Mobipocket container: PalmDB + MOBI header + EXTH (title, author, cover)."""
    def exth_rec(rtype: int, payload: bytes) -> bytes:
        return struct.pack(">II", rtype, 8 + len(payload)) + payload

    recs = [exth_rec(503, "Fixture Mobi".encode()), exth_rec(100, b"Moby Tester"),
            exth_rec(524, b"en"), exth_rec(201, struct.pack(">I", 0))]
    exth = b"EXTH" + struct.pack(">II", 12 + sum(map(len, recs)), len(recs)) + b"".join(recs)
    exth += b"\0" * (-len(exth) % 4)
    mobi_len = 232
    full_name = b"Fixture Mobi Full Name"
    header = bytearray(16 + mobi_len)
    struct.pack_into(">HHIHHHH", header, 0, 1, 0, 0, 1, 4096, 0, 0)   # PalmDOC header
    header[16:20] = b"MOBI"
    struct.pack_into(">III", header, 20, mobi_len, 2, 65001)          # length, type, UTF-8
    struct.pack_into(">II", header, 0x54, len(header) + len(exth), len(full_name))
    struct.pack_into(">I", header, 0x6C, 2)                           # first image record
    struct.pack_into(">I", header, 0x80, 0x40)                        # EXTH present
    rec0 = bytes(header) + exth + full_name + b"\0\0"
    records = [rec0, b"<html><body><p>Hello Mobi</p></body></html>", _png(50, 80, (120, 40, 160))]

    count = len(records)
    start = 78 + 8 * count + 2
    offsets, pos = [], start
    for r in records:
        offsets.append(pos)
        pos += len(r)
    head = bytearray(78)
    head[:32] = b"Fixture_Mobi".ljust(32, b"\0")
    head[60:68] = b"BOOKMOBI"
    struct.pack_into(">H", head, 76, count)
    table = b"".join(struct.pack(">II", o, i * 2) for i, o in enumerate(offsets))
    dest.write_bytes(bytes(head) + table + b"\0\0" + b"".join(records))
    return dest


def pdf(dest: Path) -> Path:
    """Three text pages with a document outline (PDF bookmarks)."""
    titles = ["Opening", "Development", "Resolution"]
    objs: list[bytes] = []

    def add(body: str) -> int:
        objs.append(body.encode("latin-1"))
        return len(objs)

    catalog = add("")  # placeholder, filled below
    pages = add("")
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    for t in titles:
        stream = f"BT /F1 24 Tf 72 700 Td ({t}) Tj ET"
        content = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_ids.append(add(
            f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"))
    outlines = add("")
    item_ids = list(range(len(objs) + 1, len(objs) + 1 + len(titles)))
    for i, (t, pid) in enumerate(zip(titles, page_ids)):
        prev = f"/Prev {item_ids[i - 1]} 0 R " if i > 0 else ""
        nxt = f"/Next {item_ids[i + 1]} 0 R " if i < len(titles) - 1 else ""
        add(f"<< /Title ({t}) /Parent {outlines} 0 R {prev}{nxt}/Dest [{pid} 0 R /Fit] >>")
    objs[outlines - 1] = f"<< /Type /Outlines /First {item_ids[0]} 0 R /Last {item_ids[-1]} 0 R /Count {len(titles)} >>".encode()
    objs[pages - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(page_ids)} >>".encode()
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages} 0 R /Outlines {outlines} 0 R /PageMode /UseOutlines >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info << /Title (Fixture PDF) /Author (Pat Tester) >> >>\nstartxref\n{xref}\n%%EOF\n".encode()
    dest.write_bytes(bytes(out))
    return dest


BUILDERS = {
    "epub3.epub": epub3,
    "epub2.epub": epub2_ncx,
    "empty_meta.epub": epub_empty_metadata,
    "evil.epub": epub_malicious,
    "fixture.fb2": fb2,
    "comic.cbz": cbz,
    "comicinfo.cbz": cbz_comicinfo,
    "fixture.mobi": mobi,
    "outline.pdf": pdf,
}


def build_all(dest_dir: Path) -> dict[str, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    return {name: fn(dest_dir / name) for name, fn in BUILDERS.items()}
