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
EXIT_POW_CHALLENGE = 2   # got PoW/HTML instead of PDF (cookie invalid/expired)

def is_pdf(path):
    """Check magic bytes. PDF files start with '%PDF'."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False

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

def download(url, out_path, cookie_str, referer=None, ua=None, max_retries=8):
    ua = ua or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    referer = referer or ""
    cookie_str = sanitize_cookie(cookie_str)
    for attempt in range(1, max_retries + 1):
        have = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        # If a partial file exists but ISN'T a valid PDF start, it's likely a
        # leftover PoW challenge page — delete it so Range resume doesn't
        # append to garbage.
        if have > 0 and have < 4096 and not is_pdf(out_path):
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
            # Magic-bytes validation: if we got HTML (PoW challenge) instead of PDF,
            # the cookie is invalid/expired. Delete the fake file and bail immediately.
            if not is_pdf(out_path):
                os.remove(out_path)
                print(f"ERROR: received non-PDF content (likely PoW challenge page). "
                      f"Cookie invalid or expired. Re-trigger PoW: navigate browser "
                      f"to the PDF URL, wait ~10s, re-harvest cookies, then retry.",
                      file=sys.stderr)
                return EXIT_POW_CHALLENGE
            if total_expected == 0 or sz >= total_expected:
                print("Download complete.")
                return EXIT_OK
        except Exception as e:
            sz = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            print(f"[attempt {attempt}] error: {e} (have {sz} bytes), retrying in 3s...")
            time.sleep(3)
    print(f"Failed after {max_retries} attempts. Partial file may exist at {out_path}.")
    return EXIT_DOWNLOAD_FAIL

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Direct PDF URL to download")
    ap.add_argument("out_path", help="Local output file path")
    ap.add_argument("cookie_str", help='Cookie header string, e.g. "name1=val1; name2=val2"')
    ap.add_argument("--referer", default="", help="Referer URL (often the article landing page)")
    args = ap.parse_args()
    rc = download(args.url, args.out_path, args.cookie_str, referer=args.referer)
    if rc == EXIT_POW_CHALLENGE:
        print("\n[TIP] Exit code 2 = PoW challenge page received instead of PDF.\n"
              "      Re-trigger PoW and retry:\n"
              "        opencli browser <session> open <pdf_url>   # trigger PoW JS\n"
              "        sleep 10\n"
              "        COOKIES=$(opencli browser <session> eval \"document.cookie\")\n"
              "        python3 download_pdf.py <url> <out> \"$COOKIES\" --referer <article_url>",
              file=sys.stderr)
    sys.exit(rc)

if __name__ == "__main__":
    main()