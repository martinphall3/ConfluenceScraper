#!/usr/bin/env python3
"""
Export the CLIENTHELP Confluence space into ONE combined document:
  clienthelp_export/CLIENTHELP_knowledge_base.md    Markdown (images in assets/)
  clienthelp_export/CLIENTHELP_knowledge_base.html  HTML (images in assets/)
  clienthelp_export/CLIENTHELP_knowledge_base.pdf   PDF with screenshots embedded
"""
import os, re, time, hashlib, datetime, html as H
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import mimetypes
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    OCR = os.environ.get("OCR", "1") == "1"      # set OCR=0 to switch off
except ImportError:
    OCR = False

# ---------------- settings ----------------
SITE     = ""
EMAIL    = ""
TOKEN    = ""
SPACE    = ""
HOME_ID  = ""                       # space homepage, placed first
OUT      = "export"
ASSETS   = os.path.join(OUT, "assets")
BASENAME = "export_result"
EXCLUDE_LABEL    = "exclude-bot"
INCLUDE_COMMENTS = True
# ------------------------------------------

CQL    = f'space = "{SPACE}" AND type = page AND label != "{EXCLUDE_LABEL}"'
EXPAND = "body.export_view,ancestors,metadata.labels,version"

s = requests.Session()
s.auth = (EMAIL, TOKEN)
s.headers["Accept"] = "application/json"


def get(url, **params):
    for _ in range(6):
        r = s.get(url, params=params, timeout=120)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(int(r.headers.get("Retry-After", 10)))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def slug(t):
    return re.sub(r"[^\w\-]+", "-", t).strip("-")[:60] or "file"


# ---------- fetch & order pages ----------
def fetch_pages():
    pages, url = [], f"{SITE}/wiki/rest/api/content/search"
    params = {"cql": CQL, "expand": EXPAND, "limit": 50}
    while url:
        data = get(url, **params)
        pages += data["results"]
        nxt = data.get("_links", {}).get("next")
        url, params = (SITE + "/wiki" + nxt.removeprefix("/wiki"), {}) if nxt else (None, None)
        print(f"  fetched {len(pages)} pages...")
    return pages


def order_pages(pages):
    """Depth-first walk of the page tree; siblings sorted by title."""
    by_id, children, roots = {p["id"]: p for p in pages}, {}, []
    for p in pages:
        anc = [a["id"] for a in p.get("ancestors", [])]
        parent = next((a for a in reversed(anc) if a in by_id), None)
        (children.setdefault(parent, []) if parent else roots).append(p)

    ordered = []
    def walk(p, depth):
        ordered.append((p, depth))
        for c in sorted(children.get(p["id"], []), key=lambda x: x["title"].lower()):
            walk(c, depth + 1)
    for r in sorted(roots, key=lambda x: (x["id"] != HOME_ID, x["title"].lower())):
        walk(r, 0)
    return ordered


# ---------- images, links, comments, attachments ----------

def download(url, dest):
    """Download an authenticated Confluence attachment."""
    try:
        full_url = urljoin(SITE + "/", url)

        response = s.get(
            full_url,
            timeout=120,
            allow_redirects=True,
            headers={"Accept": "*/*"}
        )

        if response.status_code != 200:
            print(
                f"IMAGE ERROR: HTTP {response.status_code}"
                f" | {urlparse(full_url).path}"
            )
            return False

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        # Prevent saving an HTML login/error page as an image.
        if "text/html" in content_type:
            print(
                "IMAGE ERROR: Received HTML instead "
                "of image data. Check attachment access."
            )
            return False

        if not response.content:
            print("IMAGE ERROR: Empty response")
            return False

        os.makedirs(os.path.dirname(dest), exist_ok=True)

        with open(dest, "wb") as file:
            file.write(response.content)

        print(f"Downloaded: {os.path.basename(dest)}")
        return True

    except requests.RequestException as error:
        print(f"IMAGE ERROR: {type(error).__name__}: {error}")
        return False


def ocr_text(path):
    try:
        return " ".join(pytesseract.image_to_string(Image.open(path)).split())
    except Exception:
        return ""


def process_body(raw_html, pid, exported_ids):
    """Returns (markdown, html). Downloads images, adds OCR text, fixes links."""
    soup = BeautifulSoup(raw_html or "", "html.parser")
    
    image_map = download_page_images(pid)

    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")

        candidates = [
            img.get("data-linked-resource-id", ""),
            img.get("data-linked-resource-default-alias", ""),
            img.get("data-image-title", ""),
            img.get("data-filename", ""),
            unquote(urlparse(src).path).split("/")[-1],
            alt,
        ]

        matched = None

        for candidate in candidates:
            key = candidate.casefold()
            if key in image_map:
                matched = image_map[key]
                break

        if matched:
            img["src"] = matched
            img.attrs.pop("srcset", None)
            img.attrs.pop("data-src", None)

    site_host = urlparse(SITE).netloc

    for i, img in enumerate(soup.find_all("img")):
        src = (img.get("src") or "").strip()

        if (
            not src
            or src.startswith("data:")
            or "/images/icons/" in src
            or "emoticon" in src
        ):
            continue

    # Images already downloaded from Confluence
    # must NOT be downloaded again.
        if src.startswith(("assets/", "./assets/")):
            local_file = Path(OUT) / src.removeprefix("./")

            if local_file.is_file():
                print(f"Image linked successfully: {src}")
            else:
                print(f"WARNING: Local image missing: {local_file}")

            continue

    # Only download images that still have remote URLs.
        full = urljoin(SITE + "/", src)
        if urlparse(full).netloc != site_host:
            continue                                  # external image: leave as-is
        ext = os.path.splitext(unquote(urlparse(full).path))[1].lower() or ".png"
        if len(ext) > 5:
            ext = ".png"
        name = f"{pid}-{i:02d}-{hashlib.md5(full.encode()).hexdigest()[:8]}{ext}"
        dest = os.path.join(ASSETS, name)
        if not download(full, dest):
            note = soup.new_tag("p")
            note.string = f"[Image could not be downloaded: {img.get('alt') or name}]"
            img.replace_with(note)
            continue
        img["src"] = f"assets/{name}"
        for attr in ("srcset", "width", "height", "data-image-src"):
            img.attrs.pop(attr, None)
        if OCR:
            text = ocr_text(dest)
            if text:
                note = soup.new_tag("p", attrs={"class": "ocr"})
                note.string = f"[Screenshot text] {text}"
                img.insert_after(note)

    # make relative links absolute; remember links to other exported pages
    internal = []
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("/"):
            a["href"] = urljoin(SITE + "/", a["href"])
        m = re.search(r"/pages/(\d+)", a["href"])
        if m and m.group(1) in exported_ids and SITE in a["href"]:
            internal.append((a, m.group(1)))

    markdown = md(str(soup), heading_style="ATX").strip()   # keeps absolute links

    for a, target in internal:                              # in-document jumps for HTML/PDF
        a["href"] = f"#page-{target}"
    return markdown, str(soup)


def comments(pid):
    if not INCLUDE_COMMENTS:
        return []
    data = get(f"{SITE}/wiki/rest/api/content/{pid}/child/comment",
               expand="body.view,version", depth="all", limit=100)
    return [(c["version"]["by"].get("displayName", "unknown"),
             c["version"]["when"][:10],
             c["body"]["view"]["value"]) for c in data.get("results", [])]


def attachments(pid):
    data = get(f"{SITE}/wiki/rest/api/content/{pid}/child/attachment", limit=100)
    return [(a["title"], f"{SITE}/wiki{a['_links']['download']}") for a in data.get("results", [])]


def download_page_images(pid):
    """
    Download image attachments for one Confluence page.
    Return a mapping of original filename to local path.
    """
    url = (
        f"{SITE}/wiki/rest/api/content/"
        f"{pid}/child/attachment"
    )

    image_map = {}
    params = {"limit": 100}

    while url:
        data = get(url, **params)

        for attachment in data.get("results", []):
            filename = attachment["title"]
            media_type = attachment.get(
                "metadata", {}
            ).get("mediaType", "")

            is_image = (
                media_type.startswith("image/")
                or filename.lower().endswith(
                    (".png", ".jpg", ".jpeg",
                     ".gif", ".webp", ".bmp")
                )
            )

            if not is_image:
                continue

            attachment_id = attachment["id"]
            extension = os.path.splitext(filename)[1]

            local_name = (
                f"{pid}-{attachment_id}{extension}"
            )
            local_path = os.path.join(
                ASSETS, local_name
            )

            download_path = attachment.get(
                "_links", {}
            ).get("download")

            if not download_path:
                print(f"No download link: {filename}")
                continue

            full_url = urljoin(
                SITE + "/",
                "/wiki/" + download_path.lstrip("/")
                if not download_path.startswith("/wiki/")
                else download_path
            )

            if download(full_url, local_path):
                relative_path = f"assets/{local_name}"

                image_map[filename.casefold()] = relative_path
                image_map[unquote(filename).casefold()] = relative_path
                image_map[str(attachment_id).casefold()] = relative_path
            image_map[f"att{attachment_id}".casefold()] = relative_path

        next_link = data.get(
            "_links", {}
        ).get("next")

        if next_link:
            url = urljoin(
                SITE + "/",
                "/wiki/" + next_link.lstrip("/")
                if not next_link.startswith("/wiki/")
                else next_link
            )
            params = {}
        else:
            url = None

    return image_map


# ---------- output ----------
CSS = """
@page { size: Letter; margin: 18mm 15mm;
        @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #666; } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; color: #172b4d; }
h1 { color: #0052cc; font-size: 18pt; }
section.page { page-break-before: always; }
.meta { font-size: 8.5pt; color: #555; border-left: 3px solid #0052cc; padding-left: 8px; margin-bottom: 12px; }
img { max-width: 100%; height: auto; border: 1px solid #ddd; margin: 6px 0; }
.ocr { font-size: 8pt; color: #777; font-style: italic; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; word-wrap: break-word; }
th, td { border: 1px solid #ccc; padding: 4px; vertical-align: top; }
pre, code { white-space: pre-wrap; word-break: break-all; font-size: 9pt; background: #f4f5f7; }
.expand-content, .expand-container { display: block !important; }
.toc ul { list-style: none; padding-left: 1.2em; }
.toc a { text-decoration: none; color: #172b4d; }
.toc a::after { content: leader('.') target-counter(attr(href), page); }
.comments { font-size: 9pt; background: #fffae6; padding: 6px 10px; }
"""


def make_pdf(html_path, pdf_path):
    try:
        from weasyprint import HTML
    except Exception as e:
        print(f"! PDF skipped (WeasyPrint not available: {e}).\n"
              f"  Open {html_path} in Chrome and use Print > Save as PDF instead.")
        return
    print("Rendering PDF (can take a few minutes)...")
    HTML(filename=html_path).write_pdf(pdf_path)
    print(f"PDF written: {pdf_path}")

def main():
    os.makedirs(ASSETS, exist_ok=True)
    print("Fetching pages...")
    pages = fetch_pages()
    ordered = order_pages(pages)
    ids = {p["id"] for p in pages}
    today = datetime.date.today().isoformat()

    md_toc, md_body, html_toc, html_body = [], [], [], []
    for n, (p, depth) in enumerate(ordered, 1):
        pid, title = p["id"], p["title"]
        link    = SITE + "/wiki" + p["_links"]["webui"]
        crumb   = " > ".join(a["title"] for a in p.get("ancestors", []))
        labels  = [l["name"] for l in p["metadata"]["labels"]["results"]]
        updated = p["version"]["when"][:10]
        print(f"[{n}/{len(ordered)}] {title}")

        body_md, body_html = process_body(p["body"]["export_view"]["value"], pid, ids)
        atts, coms = attachments(pid), comments(pid)

        # --- Markdown ---
        md_toc.append(f"{'  ' * depth}- [{title}](#page-{pid})")
        sec = [f"<!-- PAGE START {pid} -->", f'<a id="page-{pid}"></a>', f"# {title}", "",
               f"> **Source:** {link}  ",
               f"> **Path:** {crumb or '(top level)'}  ",
               f"> **Labels:** {', '.join(labels) or 'none'}  ",
               f"> **Last updated:** {updated}", "",
               body_md or "_(This page has no text content of its own.)_"]
        if atts:
            sec += ["", "## Attachments", *[f"- [{t}]({u})" for t, u in atts]]
        if coms:
            sec += ["", "## Comments (may contain corrections)",
                    *[f"- **{w} ({d}):** {md(c).strip()}" for w, d, c in coms]]
        sec += [f"<!-- PAGE END {pid} -->", ""]
        md_body.append("\n".join(sec))

        # --- HTML ---
        html_toc.append((depth, f'<a href="#page-{pid}">{H.escape(title)}</a>'))
        h = [f'<section class="page" id="page-{pid}">', f"<h1>{H.escape(title)}</h1>",
             '<div class="meta">',
             f'<b>Source:</b> <a href="{link}">{H.escape(link)}</a><br>',
             f"<b>Path:</b> {H.escape(crumb or '(top level)')}<br>",
             f"<b>Labels:</b> {H.escape(', '.join(labels) or 'none')}<br>",
             f"<b>Last updated:</b> {updated}</div>",
             body_html or "<p><i>(This page has no text content of its own.)</i></p>"]
        if atts:
            h += ["<h2>Attachments</h2><ul>",
                  *[f'<li><a href="{u}">{H.escape(t)}</a></li>' for t, u in atts], "</ul>"]
        if coms:
            h += ['<div class="comments"><h2>Comments (may contain corrections)</h2>',
                  *[f"<p><b>{H.escape(w)} ({d}):</b></p>{c}" for w, d, c in coms], "</div>"]
        h.append("</section>")
        html_body.append("\n".join(h))

    # write Markdown
    header = (f"# Fortress Information Security Knowledge Base ({SPACE})\n\n"
              f"Exported {today} from {SITE}/wiki/spaces/{SPACE} - {len(ordered)} pages.\n\n"
              "## Contents\n\n")
    md_path = os.path.join(OUT, f"{BASENAME}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(md_toc) + "\n\n---\n\n" + "\n".join(md_body))

    # write HTML (nested TOC)
    toc, prev = ["<ul>"], 0
    for depth, item in html_toc:
        toc += ["<ul>"] * (depth - prev) + ["</ul>"] * (prev - depth)
        toc.append(f"<li>{item}</li>")
        prev = depth
    toc += ["</ul>"] * (prev + 1)
    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Knowledge Base</title><style>{CSS}</style></head><body>
<h1>Knowledge Base ({SPACE})</h1>
<p>Exported {today} from <a href="{SITE}/wiki/spaces/{SPACE}">{SITE}/wiki/spaces/{SPACE}</a> - {len(ordered)} pages.</p>
<div class="toc"><h2>Contents</h2>{''.join(toc)}</div>
{''.join(html_body)}
</body></html>"""
    html_path = os.path.join(OUT, f"{BASENAME}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Markdown written: {md_path}\nHTML written: {html_path}")
    make_pdf(html_path, os.path.join(OUT, f"{BASENAME}.pdf"))


if __name__ == "__main__":
    main()