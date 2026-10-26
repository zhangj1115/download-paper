#!/usr/bin/env python3
"""Download a paper PDF (and supplements) using cookies harvested from a browser session.

Usage:
  python3 download_pdf.py <url> <out_path> "<cookie_str>" [--referer <url>]

Reads cookies from the command line (typically extracted via `opencli browser <session> eval "document.cookie"`),
then streams the PDF to disk with retry + resume. Handles Range requests for partial downloads.

Exit codes: 0 = success, 1 = failure.
"""
import sys, os, time, urllib.request, argparse

# Exit codes
EXIT_OK = 0
EXIT_DOWNLOAD_FAIL = 1
EXIT_POW_CHALLENGE = 2   # got PoW/HTML instead of the expected file (cookie invalid/expired)

# Type → (magic bytes, offset, label)
# These cover the common paper/supplement file formats. Office files (docx/xlsx/pptx)
# and zip archives all start with the ZIP signature PK\x03\x04.
TYPE_MAGIC = {
    "pdf":        (b"%PDF", 0, "PDF document"),
    "office_zip": (b"PK\x03\x04", 0, "ZIP/Office (docx/xlsx/pptx/zip)"),
    "png":        (b"\x89PNG\r\n\x1a\n", 0, "PNG image"),
    "jpeg":       (b"\xff\xd8\xff", 0, "JPEG image"),
    "gzip":       (b"\x1f\x8b", 0, "gzip archive"),
}

# Map common out_path extensions → expected type key (used when --type auto)
EXT_TO_TYPE = {
    ".pdf": "pdf", ".docx": "office_zip", ".xlsx": "office_zip",
    ".pptx": "office_zip", ".zip": "office_zip", ".png": "png",
    ".jpg": "jpeg", ".jpeg": "jpeg", ".gz": "gzip", ".tgz": "gzip",
}

def detect_file_type(path):
    """Identify a downloaded file by its magic bytes.

    Returns one of: 'pdf', 'office_zip', 'png', 'jpeg', 'gzip', 'small_html',
    'empty', or 'unknown'. 'small_html' is the PoW-challenge / login-page signal:
    a tiny file whose first bytes look like HTML markup. Large files with HTML-ish
    first bytes (e.g. some PDFs with trailing HTML wrappers, or real HTML downloads)
    are reported as 'unknown' rather than 'small_html', to avoid false positives.
    """
    try:
        sz = os.path.getsize(path)
    except OSError:
        return "empty"
    if sz == 0:
        return "empty"
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except Exception:
        return "unknown"
    for key, (magic, off, _label) in TYPE_MAGIC.items():
        if head[off:off + len(magic)] == magic:
            return key
    # Small file starting with '<' → almost certainly a PoW challenge / login HTML page.
    # PoW challenge pages are ~1.8KB; ablesci login walls ~49KB. Use a 64KB cutoff so
    # we catch both, while letting large HTML downloads pass through as 'unknown'.
    if sz < 65536 and head[:1] in (b"<", b"\xef"):  # '<' or UTF-8 BOM + '<'
        return "small_html"
    return "unknown"

def expected_type_for_path(out_path):
    """Infer the expected type key from the output file extension. Returns 'pdf' if
    no mapping (preserves historical behaviour for PDFs without a .pdf extension)."""
    ext = os.path.splitext(out_path)[1].lower()
    return EXT_TO_TYPE.get(ext, "pdf")

def sanitize_cookie(cookie_str):
    """Strip non-ASCII chars (e.g. Unicode symbols from browser eval output)
    and keep only valid 'name=value; name=value' pairs. urllib HTTP headers
    only accept latin-1, so any non-latin-1 char crashes the request."""
    import re
    # Keep only ASCII chars; split on ';', strip, rejoin. Drop empty/malformed.
    pairs = []
    for part in re.sub(r'[^\x20-\x7E]', '', cookie_str).split(';'):
        part = part.strip()
        if '=' in part:
            pairs.append(part)
    return '; '.join(pairs)

def download(url, out_path, cookie_str, referer=None, ua=None, max_retries=8, expected_type="auto"):
    ua = ua or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    referer = referer or ""
    cookie_str = sanitize_cookie(cookie_str)
    # Resolve the expected type. 'auto' infers from the output extension; callers
    # downloading PDFs without a .pdf extension should pass --type pdf explicitly.
    if expected_type == "auto":
        expected_type = expected_type_for_path(out_path)
    for attempt in range(1, max_retries + 1):
        have = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        # If a partial file exists but ISN'T a valid file start for the expected
        # type, it's likely a leftover PoW challenge page — delete it so Range
        # resume doesn't append to garbage. We only do this for small partials
        # (<64KB) so a half-downloaded large file keeps resuming.
        if have > 0 and have < 65536 and detect_file_type(out_path) == "small_html":
            os.remove(out_path)
            have = 0
        headers = {"User-Agent": ua, "Cookie": cookie_str}
        if referer:
            headers["Referer"] = referer
        if have > 0:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=90)
            cl = resp.headers.get("Content-Length")
            total_expected = (int(cl) + have) if cl else 0
            # 200 with existing partial data => server doesn't support Range, restart
            if have > 0 and resp.status == 200:
                have = 0
                mode = "wb"
            else:
                mode = "ab" if have > 0 else "wb"
            print(f"[attempt {attempt}] status={resp.status} content-length={cl} have={have} total~={total_expected}")
            with open(out_path, mode) as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            sz = os.path.getsize(out_path)
            print(f"  -> {sz} bytes written")
            # Magic-bytes validation. 'small_html' = a tiny HTML page, which is the
            # PoW/login challenge, NOT the file we asked for — delete and bail.
            got = detect_file_type(out_path)
            if got == "small_html":
                os.remove(out_path)
                print(f"ERROR: received HTML (PoW/login challenge page) instead of "
                      f"expected type '{expected_type}'. Cookie invalid or expired. "
                      f"Re-trigger PoW: navigate browser to the file URL, wait ~10s, "
                      f"re-harvest cookies, then retry.",
                      file=sys.stderr)
                return EXIT_POW_CHALLENGE
            if got == "empty":
                os.remove(out_path)
                print(f"ERROR: downloaded file is empty.", file=sys.stderr)
                return EXIT_DOWNLOAD_FAIL
            # Match against expected type. office_zip covers docx/xlsx/pptx/zip;
            # accept any of those extensions when the magic is office_zip.
            type_ok = (got == expected_type) or (
                expected_type == "office_zip" and got == "office_zip")
            if not type_ok:
                # Don't delete — the download may be a valid file of an unexpected
                # type (e.g. a PDF saved with .docx extension, or a redirect). Warn
                # loudly and let the caller decide. Only small_html is fatal above.
                print(f"WARNING: expected type '{expected_type}' but detected "
                      f"'{got}' (file kept for caller inspection).", file=sys.stderr)
            if total_expected == 0 or sz >= total_expected:
                print(f"Download complete. (type={got}, expected={expected_type})")
                return EXIT_OK
        except Exception as e:
            sz = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            print(f"[attempt {attempt}] error: {e} (have {sz} bytes), retrying in 3s...")
            time.sleep(3)
    print(f"Failed after {max_retries} attempts. Partial file may exist at {out_path}.")
    return EXIT_DOWNLOAD_FAIL

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Direct URL to download (PDF, docx/xlsx/zip supplement, etc.)")
    ap.add_argument("out_path", help="Local output file path")
    ap.add_argument("cookie_str", help='Cookie header string, e.g. "name1=val1; name2=val2"')
    ap.add_argument("--referer", default="", help="Referer URL (often the article landing page)")
    ap.add_argument("--type", dest="expected_type", default="auto",
                     choices=["auto", "pdf", "office_zip", "png", "jpeg", "gzip"],
                     help="Expected file type for magic-byte validation (default: auto, "
                          "inferred from out_path extension). Use --type pdf for a PDF "
                          "saved without a .pdf extension; --type office_zip for a "
                          "docx/xlsx/pptx/zip supplement saved with a non-standard name.")
    args = ap.parse_args()
    rc = download(args.url, args.out_path, args.cookie_str,
                  referer=args.referer, expected_type=args.expected_type)
    if rc == EXIT_POW_CHALLENGE:
        print("\n[TIP] Exit code 2 = PoW/login challenge page received instead of the file.\n"
              "      Re-trigger PoW and retry:\n"
              "        opencli browser <session> open <file_url>   # trigger PoW JS\n"
              "        sleep 10\n"
              "        COOKIES=$(opencli browser <session> eval \"document.cookie\")\n"
              "        python3 download_pdf.py <url> <out> \"$COOKIES\" --referer <article_url>\n"
              "      Note: for non-PDF supplements (docx/xlsx/zip), pass --type office_zip "
              "if the output path has no recognizable extension.",
              file=sys.stderr)
    sys.exit(rc)

if __name__ == "__main__":
    main()