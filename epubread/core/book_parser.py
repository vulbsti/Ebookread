"""Pure-stdlib EPUB parser + metadata/cover extractor with multi-format hooks."""

from __future__ import annotations

import mimetypes
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .config import get_data_dir
from .db import compute_file_hash
from .formats import READERS, FormatInfo, save_cover

SUPPORTED_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3", ".fb2", ".cbz"}


@dataclass
class TocItem:
    title: str
    href: str
    chapter_index: int
    fragment: str = ""
    children: list["TocItem"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "href": self.href,
            "chapter_index": self.chapter_index,
            "fragment": self.fragment,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class SpineItem:
    index: int
    idref: str
    href: str          # Path inside zip relative to zip root (POSIX)
    media_type: str


@dataclass
class ParsedMetadata:
    file_path: Path
    file_hash: str
    file_format: str
    title: str
    author: str
    language: str
    cover_path: str | None


def fallback_title(path: Path) -> str:
    """Title used when a file carries no usable metadata."""
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.stem


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _normalize_zip_path(base_dir: str, rel_href: str) -> str:
    clean = unquote(rel_href.split("#", 1)[0])
    if not base_dir:
        return posixpath.normpath(clean).lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, clean)).lstrip("/")


class EpubArchive:
    """Fast, zero-dependency EPUB 2 & EPUB 3 archive reader."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path).resolve()
        self.zf = zipfile.ZipFile(self.file_path, "r")
        self.opf_path = self._find_opf_path()
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.title = fallback_title(self.file_path)
        self.author = "Unknown Author"
        self.language = "en"
        self.manifest: dict[str, tuple[str, str, str]] = {}  # id -> (zip_path, media_type, properties)
        self.spine: list[SpineItem] = []
        self.toc: list[TocItem] = []
        self.cover_zip_path: str | None = None
        self._parse_opf()
        self._parse_toc()

    def close(self) -> None:
        self.zf.close()

    def __enter__(self) -> "EpubArchive":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _find_opf_path(self) -> str:
        try:
            container_xml = self.zf.read("META-INF/container.xml")
            root = ET.fromstring(container_xml)
            for elem in root.iter():
                if _local(elem.tag) == "rootfile" and elem.attrib.get("full-path"):
                    return elem.attrib["full-path"]
        except (KeyError, ET.ParseError):
            pass
        for name in self.zf.namelist():
            if name.lower().endswith(".opf"):
                return name
        raise ValueError(f"No OPF package document found in {self.file_path.name}")

    def _parse_opf(self) -> None:
        root = ET.fromstring(self.zf.read(self.opf_path))
        cover_meta_id: str | None = None
        toc_id: str | None = None

        for child in root:
            name = _local(child.tag)
            if name == "metadata":
                authors: list[str] = []
                for m in child:
                    mtag = _local(m.tag)
                    text = (m.text or "").strip()
                    if mtag == "title" and text and self.title == fallback_title(self.file_path):
                        self.title = text
                    elif mtag == "creator" and text:
                        authors.append(text)
                    elif mtag == "language" and text:
                        self.language = text
                    elif mtag == "meta" and m.attrib.get("name") == "cover":
                        cover_meta_id = m.attrib.get("content")
                if authors:
                    self.author = ", ".join(authors)

            elif name == "manifest":
                for item in child:
                    if _local(item.tag) != "item":
                        continue
                    item_id = item.attrib.get("id", "")
                    href = item.attrib.get("href", "")
                    media_type = item.attrib.get("media-type", "")
                    props = item.attrib.get("properties", "")
                    zip_path = _normalize_zip_path(self.opf_dir, href)
                    self.manifest[item_id] = (zip_path, media_type, props)
                    if "cover-image" in props.split():
                        self.cover_zip_path = zip_path

            elif name == "spine":
                toc_id = child.attrib.get("toc")
                for idx, itemref in enumerate(child):
                    if _local(itemref.tag) != "itemref":
                        continue
                    idref = itemref.attrib.get("idref", "")
                    if idref in self.manifest:
                        zpath, mtype, _ = self.manifest[idref]
                        self.spine.append(
                            SpineItem(
                                index=len(self.spine),
                                idref=idref,
                                href=zpath,
                                media_type=mtype or "application/xhtml+xml",
                            )
                        )

        self._ncx_id = toc_id
        if not self.cover_zip_path and cover_meta_id and cover_meta_id in self.manifest:
            self.cover_zip_path = self.manifest[cover_meta_id][0]
        if not self.cover_zip_path:
            for zpath, mtype, _ in self.manifest.values():
                if mtype.startswith("image/") and "cover" in posixpath.basename(zpath).lower():
                    self.cover_zip_path = zpath
                    break

    def _spine_index_for(self, zip_path: str) -> int:
        for item in self.spine:
            if item.href == zip_path:
                return item.index
        return 0

    def _parse_toc(self) -> None:
        # Prefer EPUB 3 nav document
        for zpath, _mtype, props in self.manifest.values():
            if "nav" in props.split():
                if self._parse_epub3_nav(zpath):
                    return
        # Fall back to EPUB 2 NCX
        ncx_path: str | None = None
        if getattr(self, "_ncx_id", None) and self._ncx_id in self.manifest:
            ncx_path = self.manifest[self._ncx_id][0]
        else:
            for zpath, mtype, _ in self.manifest.values():
                if mtype == "application/x-dtbncx+xml" or zpath.lower().endswith(".ncx"):
                    ncx_path = zpath
                    break
        if ncx_path:
            self._parse_ncx(ncx_path)
        if not self.toc:
            self.toc = [
                TocItem(title=f"Section {s.index + 1}", href=s.href, chapter_index=s.index)
                for s in self.spine
            ]

    def _parse_epub3_nav(self, nav_zip_path: str) -> bool:
        try:
            root = ET.fromstring(self.zf.read(nav_zip_path))
        except (KeyError, ET.ParseError):
            return False
        nav_dir = posixpath.dirname(nav_zip_path)
        toc_nav = None
        for elem in root.iter():
            if _local(elem.tag) == "nav":
                for k, v in elem.attrib.items():
                    if k.endswith("type") and v == "toc":
                        toc_nav = elem
                        break
            if toc_nav is not None:
                break
        if toc_nav is None:
            return False

        def parse_ol(ol_elem: ET.Element) -> list[TocItem]:
            items: list[TocItem] = []
            for li in ol_elem:
                if _local(li.tag) != "li":
                    continue
                link = None
                nested_ol = None
                for ch in li:
                    tag = _local(ch.tag)
                    if tag == "a" and link is None:
                        link = ch
                    elif tag == "ol":
                        nested_ol = ch
                if link is None:
                    continue
                label = "".join(link.itertext()).strip() or "Untitled"
                raw_href = link.attrib.get("href", "")
                frag = raw_href.split("#", 1)[1] if "#" in raw_href else ""
                zpath = _normalize_zip_path(nav_dir, raw_href)
                items.append(
                    TocItem(
                        title=label,
                        href=zpath,
                        chapter_index=self._spine_index_for(zpath),
                        fragment=frag,
                        children=parse_ol(nested_ol) if nested_ol is not None else [],
                    )
                )
            return items

        for ch in toc_nav:
            if _local(ch.tag) == "ol":
                self.toc = parse_ol(ch)
                return bool(self.toc)
        return False

    def _parse_ncx(self, ncx_zip_path: str) -> None:
        try:
            root = ET.fromstring(self.zf.read(ncx_zip_path))
        except (KeyError, ET.ParseError):
            return
        ncx_dir = posixpath.dirname(ncx_zip_path)

        def parse_navpoints(parent: ET.Element) -> list[TocItem]:
            items: list[TocItem] = []
            for elem in parent:
                if _local(elem.tag) != "navPoint":
                    continue
                label = "Untitled"
                raw_src = ""
                for ch in elem:
                    t = _local(ch.tag)
                    if t == "navLabel":
                        label = "".join(ch.itertext()).strip() or label
                    elif t == "content":
                        raw_src = ch.attrib.get("src", "")
                frag = raw_src.split("#", 1)[1] if "#" in raw_src else ""
                zpath = _normalize_zip_path(ncx_dir, raw_src)
                items.append(
                    TocItem(
                        title=label,
                        href=zpath,
                        chapter_index=self._spine_index_for(zpath),
                        fragment=frag,
                        children=parse_navpoints(elem),
                    )
                )
            return items

        for ch in root:
            if _local(ch.tag) == "navMap":
                self.toc = parse_navpoints(ch)
                break

    def read_resource(self, zip_path: str) -> tuple[bytes, str]:
        clean = posixpath.normpath(unquote(zip_path)).lstrip("/")
        data = self.zf.read(clean)
        mtype, _ = mimetypes.guess_type(clean)
        if not mtype:
            for zp, mt, _ in self.manifest.values():
                if zp == clean:
                    mtype = mt
                    break
        return data, (mtype or "application/octet-stream")

    def cover_bytes(self) -> bytes | None:
        if not self.cover_zip_path:
            return None
        try:
            return self.read_resource(self.cover_zip_path)[0]
        except KeyError:
            return None


def covers_dir() -> Path:
    # Data, not cache: covers captured on first open (PDFs) can't be cheaply recreated.
    return get_data_dir() / "covers"


def extract_book_metadata(file_path: str | Path, cover_dir: Path | None = None) -> ParsedMetadata:
    """Metadata and a cover thumbnail for any supported format. Safe in a worker thread."""
    path = Path(file_path).resolve()
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported format: {ext}")
    file_hash = compute_file_hash(path)
    covers = cover_dir or covers_dir()

    if ext == ".epub":
        with EpubArchive(path) as epub:
            return ParsedMetadata(
                file_path=path,
                file_hash=file_hash,
                file_format="epub",
                title=epub.title,
                author=epub.author,
                language=epub.language,
                cover_path=save_cover(epub.cover_bytes(), covers, file_hash),
            )

    try:
        info = READERS[ext](path)
    except Exception:  # noqa: BLE001 - unreadable metadata still imports, titled by file name
        info = FormatInfo()
    return ParsedMetadata(
        file_path=path,
        file_hash=file_hash,
        file_format=ext.lstrip("."),
        title=info.title or fallback_title(path),
        author=info.author or "Unknown Author",
        language=info.language or "en",
        cover_path=save_cover(info.cover, covers, file_hash),
    )
