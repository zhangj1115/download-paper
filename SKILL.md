---
name: download-paper
description: Unified academic-literature downloader. Fetches paper PDFs plus supplementary files — from OA direct links, PMC (Proof-of-Work anti-bot), preprints behind Cloudflare, paywalled publishers via the user's institutional library access (Web of Science → SFX resolver, CAS/CARSI/Shibboleth/EZproxy handoff, Elsevier/Springer Nature/IEEE publisher APIs), the 科研通/ablesci.com 文献互助 fallback, and Chinese literature via CNKI (中文文献一律走知网). Batch mode for 2+ papers via `scripts/batch_download.mjs`. Use whenever the user asks to download a paper, fetch a PDF, get supplements/attachments, or save literature locally — even from just a DOI, PMID, or title. Triggers: "下载文献/论文及其附件", "download this paper and supplements", "把这篇文献下到 X 目录", "知网下载这篇中文文献", "用学校图书馆/机构权限下载", "批量下载这些 DOI", "科研通求助下载". Supplements download by default (skip only on "只要正文"/"main only").
---

# Download Paper

Download academic paper PDFs and supplementary materials from the web to a local directory, then verify their integrity and identity. Built to defeat the anti-bot mechanisms (PMC Proof-of-Work, publisher referer checks) that make plain `curl` fail. Also routes **institutional-entitlement downloads** (library Web Access, publisher APIs) and **Chinese literature (CNKI)** — see step 7 and `references/institutional-access.md`.

## Core principle

Most paper PDFs can NOT be downloaded with a bare `curl`/`wget`. Several classes of blocker/source exist, and each needs a different approach:

| Blocker / Source | Symptom | Solution |
|---------|---------|----------|
| **PMC Proof-of-Work** | curl returns ~1.8KB HTML saying "Preparing to download..." with a `POW_CHALLENGE` JS var | Must run JS in a real browser to solve the PoW and get a cookie, then reuse that cookie |
| **Publisher referer/paywall** (Elsevier, Cell, Nature, Wiley) | curl returns 403 or a redirect to a login page | Send a browser User-Agent + the article page as Referer; cookie may still be needed. **For Nature OA articles, a plain `curl -L` with UA+Referer succeeds** (see "Nature OA direct-download" below). If no free copy on PMC, fall back to **机构授权 Web Access (step 7)**, then **科研通 文献互助** (see step 3b) |
| **Subscription-only, no OA copy** (Wiley/Elsevier with paywall + no PMC) | Publisher returns 403/HTML AND no PMCID exists | **机构授权 Web Access first (step 7)** if the user's institution subscribes; if the library has no entitlement, **科研通 (ablesci.com) 文献互助 fallback** — a Chinese research-mutual-aid platform where logged-in users upload paywalled PDFs for each other (~1–10 min turnaround). See step 3b. |
| **Open repo** (arXiv, GitHub) | Usually direct-downloadable | Plain `curl -L -o file.pdf <url>` works |
| **Cloudflare interstitial** (bioRxiv, and many publisher asset hosts) | curl returns 403 + ~5.8KB HTML titled "Just a moment..." | Drive a real browser to the PDF URL, then **same-origin `fetch()` + base64-chunk drain** — see "bioRxiv / Cloudflare sites" below |
| **中文文献 (CNKI/知网)** | Chinese title, `zh` metadata, or a `cnki.net` source URL | CNKI route via the user's logged-in Chrome session — see step 7. Chinese papers never go through the English ladder |
| **Paywalled, but user's institution subscribes** | Publisher 403/login wall AND no OA/PMC/preprint anywhere | Institutional Web Access route (library portal / WoS → SFX → publisher) — see step 7 |

Always diagnose which class you're hitting before choosing a tactic. The fastest diagnostic: try `curl -sS -o /tmp/probe <url>` and check `file /tmp/probe` + the first bytes. If it's HTML mentioning "download" or a challenge, it's class 1 or 2 — switch to the browser-cookie method.

**Source priority** (applies to both the main PDF and supplements — follow this order strictly, do not skip ahead):

1. **原发表网站的正刊（出版商官方版）** — ScienceDirect / Cell / Nature / Wiley / Lancet etc. The published, typeset, final-version PDF. Always try this FIRST.
2. **PubMed + PMC（开放获取副本）** — when the publisher version is genuinely unreachable even via browser (hard paywall, no OA), fall back to the free PMC copy (or the PubMed-linked free full text).
3. **预印本（bioRxiv / arXiv）** — only when both publisher and PMC are unavailable.
4. **机构授权 Web Access** — for paywalled papers with no free copy anywhere, IF the user's institution subscribes. Reuses the user's personally-authenticated browser session (never credentials in chat) — see step 7.
5. **科研通 (ablesci.com) 文献互助** — **last resort, ONLY for paywalled (收费) papers** that have no free legal copy anywhere (no OA, no PMC, no preprint) AND no usable institutional entitlement. Never use 科研通 when a free path exists.

**中文文献 special case**: a Chinese-language paper ALWAYS goes through CNKI (step 7), even if another OA copy appears to exist — CNKI is both the authoritative source and the only route with the user's entitlement.

**Critical lesson — a `curl` 403 from the publisher does NOT mean "give up on the publisher and fall back to PMC".** Most publisher anti-bot (Akamai `_abck`/`bm_sz`, Cloudflare) blocks *automated curl* but lets a real browser through. Always try driving a real browser (`opencli browser`) to obtain the publisher copy before falling back to PMC/preprint. Only descend to the next priority level when the publisher truly will not serve the bytes even via a browser (e.g. hard subscription paywall with no OA edition) — not merely because curl returned 403/HTML. See the "ScienceDirect signed-URL + Cloudflare extraction" technique below for the hardest case (Elsevier's `pdfft` → signed S3 URL on a host with its own Cloudflare layer, where even the signed URL 403s curl).

**Default: download supplements too.** Every paper download attempts to enumerate and fetch the supplementary materials / attachments alongside the main PDF, unless the user explicitly says "只要正文" / "main only" / "don't get supplements". Supplements are frequently `.docx` / `.xlsx` / `.zip` (not just `.pdf`) — the download script validates by file type, not by PDF magic bytes, so non-PDF supplements are never mistakenly deleted as "challenge pages".


## Workflow

### 1. Identify the paper and its files

Resolve the user's input to concrete download URLs:

- **DOI** → `https://doi.org/<doi>` resolves to the publisher page; look for the PDF link there.
- **PMID** → fetch `https://pubmed.ncbi.nlm.nih.gov/<pmid>/` to get the PMCID (free full text) and publisher link.
- **Title/author** → use `opencli pubmed search "<query>"` or `opencli openalex search "<query>"` to find the PMID/DOI. These adapters return metadata only (title, authors, DOI, PMID), not the PDF.
- **arXiv ID** → `opencli arxiv paper <id>` for metadata; the PDF is at `https://arxiv.org/pdf/<id>.pdf`.
- **中文文献** → Chinese title, `zh` metadata, a `cnki.net` link, or the user says 知网: go straight to the CNKI route (step 7). Do NOT route Chinese papers through PubMed/arXiv/科研通.

**Supplementary materials** are almost never on PubMed — but they ARE a default download target (see "Default: download supplements too" above). **Important: supplements are usually FREE even when the main PDF is paywalled** — publisher CDNs serve them without auth, and PMC `/bin/` paths need only the PoW cookie you already have. Try the free direct links FIRST; only fall back to 科研通 if every free path fails. Enumerate from the source that worked for the main PDF, plus cross-check any other reachable source:

- **Elsevier / ScienceDirect**: supplements are served FREE from the Elsevier CDN at `https://ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc<N>.<ext>` — no login, no SSO, no captcha (the article *page* is paywalled, but the CDN asset host is wide open). The `<PII>` is the `S0142...` id from the article URL; the extension is NOT always `.pdf` — it's often `.docx` / `.xlsx` / `.zip` / `.pdf`, and the correct extension must be guessed/probed (try `.pdf` then `.docx` then `.zip` then `.xlsx`; a 404 means that extension is wrong, not that the file is paywalled — try the next extension). Verified on Li 2026 (Biomaterials): `1-s2.0-S0142961226001043-mmc1.docx` returned the full 49.8 MB docx from `ars.els-cdn.com` with zero auth; the earlier `mmc1.pdf` 404 was a wrong-extension miss, not a paywall. The legacy `/science/article/pii/<PII>/mmc/<N>` endpoint on sciencedirect.com itself redirects through SSO and is less reliable — prefer the CDN `ars.els-cdn.com` URL directly. Download with `curl -L` + a browser UA (no Referer needed, but harmless to include the article page); validate with `file` + `unzip` (NOT `is_pdf` — see step 6).
- **Cell Press** (`cell.com`): supplements at `cell.com/cms/<doi>/attachment/<uuid>/mmc<N>.*`. These `/cms/.../attachment/` links usually work with just a browser UA + Referer even when the main PDF 403s — they are free.
- **PMC** article page: links like `/articles/instance/<PMCID>/bin/<filename>` (supplements) and `/articles/<PMCID>/pdf/<filename>` (main PDF). Free — uses the same PoW cookie as the main PDF (step 3). Scrape them with `opencli browser <session> eval "Array.from(document.querySelectorAll('a')).filter(...).map(...)"` (see step 4).
- **Nature family**: supplement links on the article page under `static-content.nature.com/.../supplementary-information.pdf` or `.xlsx`, or `media.springernature.com/...`. Same UA + Referer, no SSO redirect for these asset hosts — free.
- **Wiley / others**: look for "Supplementary Material" / "Supporting Information" / "Download Supplemental" links on the article page; the linked asset is typically free.
- **科研通 (ablesci)**: the LAST resort for supplements — only when the publisher CDN/PDF is paywalled AND there's no PMC copy AND the free supplement links above all fail. When you do need it, supplements must be requested as a SEPARATE help request ("仅需补充材料"), NOT combined with the main-PDF request — see step 3b.2. In practice this is rare: most publisher supplements are free even when the main text isn't.

List every file you plan to download (main + each supplement) before starting, so the user can confirm.

### 2. Decide the download tactic by source

| Source | Tactic |
|--------|--------|
| arXiv / GitHub | Direct `curl -L -o` — no auth needed |
| bioRxiv (Cloudflare) | **Browser same-origin fetch** — curl 403s; see "bioRxiv / Cloudflare sites" below |
| PMC (pmc.ncbi.nlm.nih.gov) | **Browser-cookie method** (PoW) — see step 3 |
| Elsevier/Cell/Nature/Lancet publisher | **Try publisher direct link first; on 403/HTML, fall back to PMC** (see "Publisher → PMC fallback" below). **For Nature OA articles specifically, try the `nature.com/articles/<id>.pdf` direct link with UA+Referer first — it works without SSO** (see "Nature OA direct-download" below). Do NOT keep retrying a publisher URL that returns 403 — it has extra anti-bot beyond cookies. |
| Elsevier / Springer Nature / IEEE with a **configured publisher API key** | **Publisher API first** (`scripts/configure_credentials.py`, step 7) — on API success you are done; on API failure auto-check OA, then ask once before Web Access |
| Wiley / subscription-only with **no PMC copy** | **Institutional Web Access (step 7)** if the user's library subscribes; else **科研通 (ablesci.com) 文献互助 fallback** — see step 3b. Use when the Publisher → PMC fallback finds no PMCID (paper is genuinely paywalled with no OA copy). |
| 中文文献 (CNKI/知网) | **CNKI branch — step 7** (batch: `scripts/batch_download.mjs --title "<中文题名>"`; PDF/CAJ format rules in the reference file) |
| Unknown / generic site | Try curl first; if it returns HTML/challenge, fall back to browser-cookie method |

#### Publisher → PMC fallback

When a publisher direct link (e.g. `cell.com/.../action/showPdf`, `.../pdfExtended/...`) returns **403 Forbidden** or an HTML login wall, do not retry it. Most Cell Press / Elsevier life-science papers are NIH-funded and have a **free open-access copy on PMC**. Switch to PMC:

1. Find the **DOI** (from the publisher URL's `doi=` param, or the page itself).
2. Resolve DOI → **PMID**: `opencli pubmed search "<title keywords>"` or query NCBI E-utilities:
   ```
   curl -sS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<DOI>[doi]&retmode=json"
   ```
3. Resolve PMID → **PMCID**:
   ```
   curl -sS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id=<PMID>"
   ```
   Look for a `PMCxxxxxxx` id in the response. If none, the paper is NOT on PMC — tell the user it's paywalled and ask about institutional access or a preprint.
4. With the PMCID, download from PMC using the browser-cookie method (step 3) with PMC URLs.

This fallback turned a hard-failed Cell Systems download into a clean success in testing.

#### Nature OA direct-download (do this BEFORE falling back to PMC)

Nature-hosted journals (Nature, npj Precision Oncology, Nature Communications, Nature Methods, etc.) run an SSO cookie-authorization flow (`idp.nature.com/authorize`, client_id `grover`) on every PDF request. **For open-access articles this flow is NOT a paywall — it transparently falls back to the free OA copy** when the client has no SSO cookie, so `curl -L` with a browser UA + Referer lands a valid PDF. The redirect chain looks like a block (`303 → idp.nature.com/authorize → 302 → idp.nature.com/transit → 302 → ...?error=cookies_not_supported → 200 PDF`) but the final 200 serves the real PDF. The `error=cookies_not_supported` query param is misleading — it means "no SSO session, serving OA edition", not "access denied". Verified on npj Precision Oncology 2026 (Xie et al., DOI 10.1038/s41698-026-01529-4): Nature direct download produced a PDF byte-identical (same MD5, same 6912989 bytes) to the PMC copy, 19 pages.

**Diagnostic — OA vs subscription**: check the article page or PubMed record for an open-access license (CC BY, "Open Access", or a PMCID). If OA, the direct download below will work. If subscription-only, the same chain ends in an HTML login page instead of a PDF → fall back to PMC (if a PMCID exists) or 科研通.

**Fastest OA/subscription probe — the HTTP status, not the body.** Run the same `curl -L` for every candidate article id and read the final code:

| Final `http_code` | Meaning |
|---|---|
| `200` + `file` says "PDF document" | OA → done |
| **`404`** + `file` says "HTML document" | **subscription-only.** Nature serves a 404 for the PDF of a non-OA article (verified on Cellpose 1.0, `s41592-020-01018-x`). The body still contains the article `<title>` plus `Access through your institution` / `Subscribe` — so don't be fooled into thinking the article "doesn't exist". |
| `403` | anti-bot, not a paywall → drive a browser (per the source-priority rule) |

So: **`404` on a Nature `.pdf` = stop trying the publisher, descend to PMC → preprint → 科研通.** Do not waste a browser session on it — the browser just lands on the article page (`document.contentType === "text/html"`) because the paywall is account-level, not cookie-level. Cross-check the OA status cheaply before you start:

```bash
# Unpaywall needs a REAL email (it 422s on example.com); Semantic Scholar needs none:
curl -sS "https://api.semanticscholar.org/graph/v1/paper/DOI:<doi>?fields=title,isOpenAccess,openAccessPdf,externalIds"
#   -> openAccessPdf.url + status GREEN = only a repository/preprint copy exists, no publisher OA.
curl -sS "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:%22<doi>%22&resultType=core&format=json"
#   -> hitCount 0 = not in PMC/EuropePMC at all (no free published copy).
```

```bash
# Nature OA article — direct curl works, no browser needed
curl -sS -L \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
  -H "Referer: https://www.nature.com/articles/<article-id>" \
  -H "Accept: application/pdf,*/*" \
  -o "<out_dir>/Author_Year_Title_Journal_main.pdf" \
  "https://www.nature.com/articles/<article-id>.pdf"
# Then verify with `file` + page count — for OA articles this yields a real PDF,
# byte-identical to the PMC copy. If `file` reports HTML instead, the article is
# subscription-only → switch to the Publisher → PMC fallback above.
```

**When to still use PMC for a Nature OA article**: (1) you need the PMC-style supplement paths (`/articles/instance/<PMCID>/bin/...`) and the publisher page's supplement links are hard to enumerate; (2) the Nature direct PDF fails the `file` check for some reason. Otherwise prefer the Nature direct link — it avoids the PoW dance entirely.

**Supplementary materials on Nature**: supplement links on the article page (typically `static-content.nature.com/.../supplementary-information.pdf` or `.xlsx`, or `media.springernature.com/...`) usually work with the same UA + Referer, no SSO redirect. Enumerate them by scraping the publisher page with `opencli browser` (step 4) and curl each directly.

**Exact CDN pattern (verified, no browser and no login needed — even for paywalled articles):**

```
https://media.springernature.com/original/springer-static/esm/art%3A<DOI with / -> %2F>/MediaObjects/<JournalID>_<Year>_<ArticleNo>_MOESM<N>_ESM.<ext>
```

e.g. `art%3A10.1038%2Fs41592-025-02595-5` + `41592_2025_2595_MOESM1_ESM.pdf`.

- **The article HTML page is plain-curl-able** (browser UA only, no Referer needed) — no browser session required just to enumerate. Grep it for the asset host:

  ```bash
  UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
  curl -sS -L -H "User-Agent: $UA" -o art.html "https://www.nature.com/articles/<article-id>"
  python3 - <<'PY'
  import re, html
  h = open('art.html', encoding='utf-8', errors='ignore').read()
  for m in re.finditer(r'href="([^"]*(?:MOESM|MediaObjects|springer\.com/esm)[^"]*)"', h, re.I):
      print(html.unescape(m.group(1)))
  PY
  ```

- **`<ext>` is not always `.pdf`** — expect `.pdf` (Supplementary Information, Reporting Summary, Peer Review File), `.gif` (legacy videos), `.mp4` (modern videos). Probe the link list rather than assuming.
- The supplementary block's link *text* tells you what each MOESM is ("Supplementary Information", "Supplementary Table 1 / Reporting Summary", "Supplementary Video 1", "Peer Review File") — strip tags from the `Supplementary information` section to name the files correctly.
- **Big supplement videos are slow.** Springer CDN served a 54 MB `.mp4` at ~1.2 MB/min, so `--max-time 300` always times out. Loop `curl -C -` until `stat -f%z <file>` reaches the known total (the first attempt's error message prints `X out of Y bytes received`, giving you both numbers):

  ```bash
  for i in 1 2 3 4 5; do
    sz=$(stat -f%z "$F"); [ "$sz" -ge $TOTAL ] && break
    echo "attempt $i, have $sz / $TOTAL"
    curl -sS -L -C - --max-time 1200 -H "User-Agent: $UA" -H "Referer: $ART" -o "$F" "$URL"
  done
  ```

  Run it in the background; a single foreground call will hit the Bash timeout long before the file completes.

#### ScienceDirect signed-URL + Cloudflare extraction (Elsevier/iScience OA — the hard case)

ScienceDirect (Elsevier, incl. the OA Cell-Press journal iScience) serves the main PDF through a **two-layer anti-bot** chain that defeats every curl-based approach, even for OA articles. Verified on Zhou et al. 2026 iScience (DOI 10.1016/j.isci.2026.117151, PII S2589004226025290 — Gold OA, CC BY):

1. The article page's "View PDF" link points to `https://www.sciencedirect.com/science/article/pii/<PII>/pdfft?md5=<token>&pid=1-s2.0-<PII>-main.pdf`. The `sciencedirect.com` host runs Akamai (`_abck`/`bm_sz`, httpOnly — unreadable by `document.cookie`), so `curl` gets 403/HTML. The Elsevier asset CDN (`ars.els-cdn.com/content/article/1-s2.0-<PII>-main.pdf`) returns 404 for the main PDF (it only hosts *images* and *supplements* under `/content/image/`, not the main PDF).
2. When a real browser (with full httpOnly cookies) navigates to the `pdfft` URL, `sciencedirect.com` issues a 302 to a **pre-signed AWS S3 URL** on `pdf.sciencedirectassets.com/.../main.pdf?X-Amz-Signature=...&X-Amz-Expires=300` (5-minute expiry). This URL is self-authenticating by its query params.
3. **The signed S3 host itself runs a SECOND Cloudflare JS challenge.** `curl` of the signed URL (even with Referer + Sec-Fetch headers) returns a ~63 KB "Security verification / JavaScript is disabled" page, NOT the PDF — curl has no `cf_clearance` (httpOnly). So the signed URL is useless to curl; only the browser can pass Cloudflare there.

**The extraction technique** — once the browser has passed both layers and is sitting on the signed S3 URL rendering the PDF (Chrome's built-in viewer; `document.contentType === "application/pdf"`), pull the bytes out with a **same-origin `fetch()`** and base64-chunk them to disk. Same-origin fetch auto-sends `cf_clearance`, so Cloudflare lets it through; CORS doesn't apply (same origin). `opencli browser network` does NOT capture the top-level navigation document body, so this fetch is the only way to get the bytes:

```bash
SESSION="isdldemo"
PII="S2589004226025290"
ART="https://www.sciencedirect.com/science/article/pii/$PII"
# a. drive a real browser to the article page (passes Akamai)
opencli browser "$SESSION" open "$ART"; sleep 5
# b. navigate to pdfft -> browser follows the 302 to the signed S3 URL and passes Cloudflare
opencli browser "$SESSION" open "$ART/pdfft?md5=<token>&pid=1-s2.0-$PII-main.pdf"
sleep 8  # let Cloudflare JS solve + the PDF render; poll until URL host == pdf.sciencedirectassets.com
#    confirm it's the PDF: opencli browser <s> eval "document.contentType"  -> "application/pdf"
# c. SAME-ORIGIN fetch into a window buffer, report size + magic bytes
opencli browser "$SESSION" eval "(async function(){
  var r = await fetch(location.href, {credentials:'include'});
  if(!r.ok) return JSON.stringify({error:'fetch '+r.status});
  window.__pdfBytes = new Uint8Array(await r.arrayBuffer());
  return JSON.stringify({size: window.__pdfBytes.length,
    head: Array.from(window.__pdfBytes.slice(0,8)).map(function(b){return (b<16?'0':'')+b.toString(16)}).join('')});
})()"
#   expect: {"size":14542815,"head":"255044462d312e37"}  (%PDF-1.7)
# d. drain the buffer in base64 chunks (eval return is size-limited; 500KB/chunk is safe)
OUT="Author_Year_Title_Journal_main.pdf"; : > "$OUT"; TOTAL=<size>; CHUNK=500000; off=0
while [ $off -lt $TOTAL ]; do
  B64=$(opencli browser "$SESSION" eval "(function(){
    var b=window.__pdfBytes; if(!b) return 'NOBUF';
    var s=b.subarray($off, Math.min($off+$CHUNK, b.length));
    var bin=''; for(var i=0;i<s.length;i+=8192){ bin+=String.fromCharCode.apply(null, s.subarray(i,i+8192)); }
    return btoa(bin);
  })()")
  [ "$B64" = "NOBUF" ] && { echo "lost buffer — re-fetch (step c)"; break; }
  printf '%s' "$B64" | base64 -d >> "$OUT"; off=$((off+CHUNK))
done
# e. verify: file -> "PDF document"; fitz -> page count; head %PDF / tail %%EOF
```

**Notes / pitfalls** (all hit during testing):
- The signed URL expires in **5 minutes** (`X-Amz-Expires=300`). If you re-navigate to get a fresh one, the `pdfft` redirect can take ~8–15s to clear Akamai + Cloudflare — poll the URL with `opencli browser <s> get url` until the host is `pdf.sciencedirectassets.com`, then immediately run the same-origin fetch. Don't re-navigate rapidly in a loop (can trip a stricter challenge).
- `window.__pdfBytes` persists across `eval` calls (it's a window property) — fetch once, drain in many calls. If a later eval returns `NOBUF`, the page navigated away; re-fetch (step c) before continuing.
- This is for the **main PDF only**. Supplements on Elsevier are FREE on the open CDN `ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc<N>.<ext>` (probe `.pdf`→`.docx`→`.zip`→`.xlsx`) — plain `curl` + UA + Referer, no browser needed (see step 1 supplement enumeration).
- Prefer this publisher path over PMC **even though it's harder** — iScience/Cell-Press OA papers are often not yet deposited in PMC when freshly published (Zhou 2026 had no PMID/PMCID at download time), so the publisher is the *only* free copy. The two-layer anti-bot is surmountable with the browser; a curl 403 is not a reason to descend the source-priority ladder.

#### Prerequisite — pick the right opencli Browser Bridge profile (do this FIRST)

If more than one Chrome profile has the Browser Bridge extension connected, **every** `opencli browser <session> ...` call fails with:

```
✖  Multiple Browser Bridge profiles are connected
✖  Hint: Select one with --profile <name>, OPENCLI_PROFILE=<name>, or opencli profile use <name>.
```

List them and **use the profile ID**, not the display alias:

```bash
opencli profile list
#   fgxd7ufb — connected v1.0.24
#   6bwpqy8y default — connected v1.0.24
# ^^^ the FIRST token is the ID; "default" is a display alias only.

P=6bwpqy8y   # the profile ID
opencli --profile "$P" browser <session> open "<url>"
```

**Pitfall (hit in testing):** `--profile default` prints `Browser profile "default" is not connected` even though `profile list` shows a profile *labelled* `default`. The alias is not resolvable — always pass the ID token. Sanity-check a profile before relying on it:

```bash
opencli --profile "$P" browser t1 state   # should print URL/viewport, not an error
```

Once chosen, prefix **every** browser call in the run with `--profile "$P"`. Also filter the noisy stderr banner (`grep -vE "UNDICI|trace-warnings|Update available|npm install -g"`) so eval output is parseable.

#### bioRxiv / Cloudflare sites — same-origin fetch extraction

bioRxiv (and a growing number of publisher asset hosts) sit behind Cloudflare, so the plain `curl` shortcut 403s with a ~5.8KB "Just a moment..." page. A real browser passes the challenge; get the bytes out with a **same-origin `fetch()`** (which auto-sends `cf_clearance`, so Cloudflare lets it through) and drain via base64 chunks:

```bash
P=6bwpqy8y; SESSION=cpdl
opencli --profile "$P" browser "$SESSION" open "https://www.biorxiv.org/content/<doi>v<ver>.full.pdf"
sleep 12
# confirm the browser is actually rendering the PDF:
opencli --profile "$P" browser "$SESSION" eval "document.contentType"   # -> "application/pdf"
# stash the bytes on window:
opencli --profile "$P" browser "$SESSION" eval "(async function(){
  var r = await fetch(location.href, {credentials:'include'});
  if(!r.ok) return JSON.stringify({error:'fetch '+r.status});
  window.__pdfBytes = new Uint8Array(await r.arrayBuffer());
  return JSON.stringify({size: window.__pdfBytes.length,
    head: Array.from(window.__pdfBytes.slice(0,8)).map(function(b){return (b<16?'0':'')+b.toString(16)}).join('')});
})()"
#   expect: {"size":12478801,"head":"255044462d312e35"}   (%PDF-1.5)
# then drain 500KB chunks (same loop as the ScienceDirect recipe, step 2d)
```

**Pitfalls (all hit during testing):**
- **Do NOT navigate the tab away while draining** — `window.__pdfBytes` is lost and you must re-fetch from step 1.
- A 12–14 MB PDF is 25–30 eval round-trips ≈ 4–5 min, which **exceeds the default 120 s Bash timeout**. Run the drain loop with `run_in_background: true` (or raise the timeout); it is not a failure when the foreground call is SIGTERM'd mid-loop.
- Verify the drained file against the reported `size` — `stat -f%z <file>` (macOS) must equal `window.__pdfBytes.length`, plus `%PDF-` head and a `%%EOF` tail.
- bioRxiv preprints often have **no supplementary files at all** — confirm by opening the abstract page (`.../content/<doi>v<ver>`, not `.full.pdf`) and grepping the page text for `supplement`; if `hasSupp` is false, the main PDF is the complete set. Also list versions via `https://api.biorxiv.org/details/biorxiv/<doi>` — some papers get a v2 after peer review.

### 3. Browser-cookie method (for PMC and other JS-challenge sites)

This is the key technique. `opencli browser` drives a real Chrome that executes the PoW JavaScript and obtains a download cookie. **Critical insight: the PoW cookie (`cloudpmc-viewer-pow`) is NOT set just by loading the article page — it is only set after the browser navigates to a PDF direct-link URL and the page's PoW JS computes the challenge.** Skipping the PDF-URL navigation step yields cookies without `cloudpmc-viewer-pow`, and every download will return a ~1.8KB HTML "Preparing to download..." challenge page instead of the PDF.

Steps:

```bash
SESSION="paperdl"  # any session name

# a. Open the ARTICLE LANDING PAGE to establish the session and grab the csrftoken
opencli browser "$SESSION" open "https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/"
sleep 3

# b. NAVIGATE TO A PDF DIRECT-LINK URL to trigger the PoW challenge.
#    The browser loads the challenge page, runs the PoW JS (~5-10s), sets the
#    cloudpmc-viewer-pow cookie, then auto-redirects back to the article page.
opencli browser "$SESSION" open "https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/pdf/<main>.pdf"
sleep 10  # allow the PoW JS to compute and set the cookie
# Confirm we're back on the article page (PoW passed):
opencli browser "$SESSION" state | head -5  # URL should be .../articles/<PMCID>/, NOT .../pdf/...

# c. NOW harvest the cookie — it MUST contain 'cloudpmc-viewer-pow'
COOKIES=$(opencli browser "$SESSION" eval "document.cookie" 2>&1)
#   Sanity check: echo "$COOKIES" | grep -o 'cloudpmc-viewer-pow=[^;]*'
#   If the grep is empty, PoW didn't fire — repeat step b with a longer sleep.

# d. Download each file using the cookie (helper script does retry + resume + %PDF validation)
python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/pdf/<main>.pdf" \
  "<out_dir>/<Paper_Year_Author_Journal_main.pdf>" \
  "$COOKIES" \
  --referer "https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/"

python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/instance/<PMCID>/bin/<supp>.pdf" \
  "<out_dir>/<Paper_Year_Author_Journal_supplementary.pdf>" \
  "$COOKIES" \
  --referer "https://pmc.ncbi.nlm.nih.gov/articles/<PMCID>/"
```

The helper script (`scripts/download_pdf.py`) streams to disk with 65536-byte chunks, retries up to 8 times, and uses HTTP `Range` to resume partial downloads. **It validates the first 4 bytes are `%PDF` after writing — if it receives a PoW challenge HTML page instead, it deletes the fake file and exits with code 2 (EXIT_POW_CHALLENGE), printing a hint to re-trigger PoW.** Do NOT treat exit code 2 as a normal failure: it means the cookie's PoW token expired mid-session.

#### Cookie expiry mid-session

PoW cookies have a limited lifetime. If you successfully download some files but later ones return exit code 2, re-trigger PoW and retry just the failed files:

```bash
# Re-trigger PoW (same as step b):
opencli browser "$SESSION" open "<any-pdf-direct-link-url>"
sleep 10
COOKIES=$(opencli browser "$SESSION" eval "document.cookie")
# Then retry the failed download with the fresh cookie.
```

You may need to re-trigger PoW once or twice for large multi-file batches.

### 3b. 科研通 (ablesci.com) 文献互助 fallback — for subscription-only papers with no OA copy

When a paywalled publisher URL (Wiley/Elsevier/etc.) returns 403 AND the Publisher → PMC fallback (step 2) finds **no PMCID**, the paper has no free legal copy online. The Chinese platform **科研通 / ablesci.com** is a research-mutual-aid site where logged-in users request and upload paywalled PDFs for each other, typically fulfilled within minutes to hours. Use `opencli browser` to drive the site.

**Prerequisite**: a logged-in ablesci.com session in `opencli browser`. The browser session must already be authenticated (visit the site once and log in via the user's existing cookies — do NOT attempt to register or log in with credentials yourself; ask the user to log in if needed). Verify login before posting:

```bash
SESSION="ablesci"

# a. Open the homepage and confirm login state
opencli browser "$SESSION" open "https://www.ablesci.com/"
sleep 3
# A logged-in user shows an avatar/username element; a logged-out user shows "登录/注册"
opencli browser "$SESSION" eval "document.querySelector('.user-info, .avatar, [class*=avatar], [class*=user]')?.textContent?.trim() || 'no user element'"
```

**Post a help request** at `/assist/create`:

```bash
# b. Open the create-page and wait for the form to render
opencli browser "$SESSION" open "https://www.ablesci.com/assist/create"
sleep 6  # the form loads via JS; #Assist-doi must exist before filling
opencli browser "$SESSION" eval "document.querySelector('#Assist-doi') ? 'ready' : 'not ready'"
#   If "not ready", the previous request may be blocking — see the "pending request" note below.

# c. Fill the four required fields. Use a real publisher URL as #Assist-url
#    (Wiley: https://onlinelibrary.wiley.com/doi/<DOI>; Elsevier: the article page).
opencli browser "$SESSION" fill "#Assist-doi"   "10.1111/iej.14131"
opencli browser "$SESSION" fill "#Assist-title" "How does orthodontic tooth movement influence the dental pulp? ..."
opencli browser "$SESSION" fill "#Assist-url"   "https://onlinelibrary.wiley.com/doi/10.1111/iej.14131"
opencli browser "$SESSION" fill "#Assist-note"  "<FirstAuthor> <et al>. <Journal>, <Year>; <vol>(<iss>):<pages>. PMID: <PMID>. 需要全文PDF。谢谢！"

# d. Submit. The button id is #form-submit-btn.
opencli browser "$SESSION" click "#form-submit-btn"
sleep 5
#   Success popup: "求助发布成功，您可在求助详情页面查看下载"
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('.layui-layer-msg, .layui-layer-content')).map(el => el.textContent.trim().slice(0,200))"
```

**Retrieve the request ID** from the "我的求助" page:

```bash
opencli browser "$SESSION" open "https://www.ablesci.com/my/assist-my"
sleep 3
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a')).filter(a => /assist\/detail/i.test(a.href)).map(a => ({text: a.textContent.trim().slice(0,60), href: a.href})).slice(0,3)"
#   → href like https://www.ablesci.com/assist/detail?id=zBBmOa   (id is the request ID)
```

**Wait for an uploader, then download via the browser's native download** (NOT curl — ablesci's session cookie is httpOnly, invisible to `document.cookie`, so curl cannot authenticate):

```bash
# e. Poll the detail page until a file appears (status "等待确认" + an upload record)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=<REQUEST_ID>"
sleep 4
opencli browser "$SESSION" eval "document.body.innerText.replace(/\s+/g,' ').slice(0, 1200)"
#   Look for text like "XX已上传文件 ... 等待确认" and a download link.

# f. Find the download link id (format /assist/download?id=<FILE_ID>)
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a[href*=download]')).map(a => ({text: a.textContent.trim().slice(0,50), href: a.href}))"

# g. Navigate the BROWSER to the download URL — the browser sends httpOnly cookies
#    automatically. Do NOT use curl here.
opencli browser "$SESSION" open "https://www.ablesci.com/assist/download?id=<FILE_ID>"

# g2. THIS IS A TWO-STEP FLOW — the URL above is an INTERMEDIATE page, NOT the file.
#     It renders as "下载文件 - 科研通" with the filename + size and a download-line
#     picker (线路1/2/3 = free; "⚡高速通道" costs ~2 points) plus an action row:
#       #download-continue        "继续当前下载"    <- free line; click THIS one
#       #download-manual-save     "手动保存文件"    (an <a>, no href)
#       #download-manual-download "手动下载文件"
#       #download-retry           "重新下载"
#     `document.contentType` on this page is "text/html" — that is EXPECTED, not a failure.
#     The buttons have NO inline onclick (bound via JS listeners), so scraping hrefs
#     finds nothing useful — you must click. Click #download-continue exactly ONCE:
opencli browser "$SESSION" eval "document.querySelector('#download-continue').click(); 'go'"
sleep 20 && ls -lat ~/Downloads/ | head -5
#   The file lands as "<Title>(科研通-ablesci.com).pdf" (~10–60s for 20–30MB).
#   Poll until no *.crdownload remains.
```

**Adopt (采纳) the uploaded file** — this rewards the uploader with points and is required before posting new requests (the site blocks new posts while an unprocessed fulfilled request exists):

```bash
# h. Back on the detail page, click the adopt button (class .btn-handle-file)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=<REQUEST_ID>"
sleep 4
opencli browser "$SESSION" eval "document.querySelectorAll('.btn-handle-file')[0]?.click(); 'clicked'"
sleep 3
# i. A layui confirm popup appears ("确定"/"取消"). Click .layui-layer-btn0 to confirm.
opencli browser "$SESSION" eval "document.querySelector('.layui-layer-btn0')?.click(); 'confirmed'"
sleep 5
#   Sometimes the first confirm only opens a second popup — click again:
opencli browser "$SESSION" eval "document.querySelector('.layui-layer-btn0')?.click(); 'ok'"
sleep 4
opencli browser "$SESSION" eval "document.body.innerText.replace(/\s+/g,' ').includes('已完成') ? 'completed' : 'still pending'"
#   "已完成" = the uploader's file was accepted; "本次互助完结" appears in the timeline.
```

**Common pitfalls on ablesci (all hit during testing):**

- **"您有部分求助已经有人上传文件，但您还尚未处理"** when trying to post a new request → a previous fulfilled request is awaiting adoption. Go adopt it first (step h–i), then re-open `/assist/create`.
- **Form not rendering after `open`** → the create page blocks if a pending fulfilled request exists; resolve it first, then re-navigate. Always sanity-check `document.querySelector('#Assist-doi')` before filling.
- **curl returns HTML instead of PDF** → the download endpoint needs the httpOnly session cookie that `document.cookie` cannot see. Always download by **navigating the browser** to the `/assist/download?id=<FILE_ID>` URL (step g), never with curl. The file lands in `~/Downloads/` with a name like `Title(科研通-ablesci.com).pdf`.
- **`/assist/download?id=...` is a two-step flow, not a direct file** → navigating there gives a `text/html` intermediate page ("下载文件 - 科研通") with free 线路1/2/3 and a paid ⚡高速通道. You must then click **`#download-continue` ("继续当前下载")** to actually receive the file. If `~/Downloads/` stays empty after navigating to the download URL, this is why — do NOT conclude the download failed, and do NOT burn 2 points on 高速通道 before trying the free line.
- **Click `#download-continue` only ONCE** → clicking it twice downloads the file twice; Chrome de-dupes the name with a ` (1)` suffix, so you end up with two identical copies in `~/Downloads/`. Verify with `md5 -q` (macOS) / `md5sum` and delete the duplicate before archiving.
- **The 49KB HTML file in Downloads** → if you accidentally `curl`'d the download URL, you got the login-page HTML. Delete it and re-download via browser navigation.
- **Layui popups need two clicks** → the adopt flow sometimes chains a second confirm popup. After the first `.layui-layer-btn0` click, re-check for another popup and click `.layui-layer-btn0` again.

**Rate-limit / etiquette**: ablesci costs the user points per request (default ~10). Don't spam requests. Post one paper, wait for fulfillment, adopt, then post the next. Turnaround is usually fast (1–10 min during Chinese daytime hours).

### 3b.2 补充材料求助（仅需补充材料 / 附件）— 仅当所有免费路径都失败时的最后手段

**Before posting a supplement request on ablesci, exhaust the free paths first** (step 1 supplement enumeration). Most publisher supplements — including Elsevier's `ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc<N>.<ext>`, Cell's `/cms/.../attachment/`, Nature's `static-content.nature.com`, and PMC's `/bin/` — are served FREE even when the main text is paywalled. The ablesci supplement request below is only for the rare case where the main text needed 科研通 (paywalled, no PMC copy) AND the publisher's free supplement CDN links also fail (e.g. the mmc files don't exist on the CDN, or the publisher uses a non-standard asset host that blocks curl).

ablesci **requires** main-text and supplementary-material requests to be posted separately — you cannot ask for both in one request. When a paywalled paper has no PMC copy AND the free supplement links all failed AND the user wants supplements (the default), run the 3b flow twice: first the main PDF (3b steps a–i), adopt it, then post a second request for the supplement only.

**Key differences from the main-PDF request:**

1. **`Assist[suppl]` radio — select "仅需补充材料" (value=1)**. The default is "只需要正文" (value=0). The form field is `Assist[suppl]`; select the value-1 option so the platform marks the request as a supplement request:
   ```bash
   opencli browser "$SESSION" eval "document.querySelector('input[name=\"Assist[suppl]\"][value=\"1\"]').click(); 'suppl=1 selected'"
   # sanity: document.querySelector('input[name=\"Assist[suppl]\"][value=\"1\"]').checked === true
   ```

2. **悬赏积分 = 正文 × 2**. Supplements cost double: Elsevier main is 10 → supplement is 20; check the form's tip text ("补充材料所需的最低悬赏积分是正文的2倍"). The `#Assist-point` field must be raised, or submission silently fails (no error visible — the AJAX just returns `code:1`). Clear and refill:
   ```bash
   opencli browser "$SESSION" eval "const el=document.querySelector('#Assist-point'); el.value=''; el.focus(); 'cleared'"
   opencli browser "$SESSION" fill "#Assist-point" "20"   # adjust to 2× the main-text minimum for this publisher
   ```

3. **Assist-note must say "仅需要补充材料，请勿上传正文"** so the uploader doesn't attach the main PDF. Template:
   ```
   <FirstAuthor> <et al>. <Journal>, <Year>;<vol>:<page>. PMID:<PMID>. 已有正文PDF，仅需要补充材料附件(Supplementary Materials，含Fig S1-Sxx 和 Table Sx，文件名通常为mmc1.pdf/.docx)。请勿上传正文。谢谢！
   ```

4. **Order constraint — post main first, adopt, THEN post supplement.** ablesci blocks a second request for the same DOI while a prior one is unadopted ("系统检测到您在1小时内发布了相同DOI的文献求助"). The same-DOI block also fires if your first submission "looked failed" but actually created a request (verify by capturing the POST `/assist/create` AJAX response — a `code:1` with a `/assist/detail?id=...` link means a prior request already exists; navigate to it instead of re-posting). Flow:
   ```bash
   # (main-PDF request: 3b steps a–i, ADOPT it first)
   # THEN:
   opencli browser "$SESSION" open "https://www.ablesci.com/assist/create"
   sleep 6
   # ...fill DOI/title/url/note, select Assist[suppl]=1, set point=2×, submit...
   ```
   If the user already has the main PDF and ONLY needs the supplement, you can go straight to the supplement request (no main-PDF request needed) — but still confirm no unadopted fulfilled request is blocking the form first.

5. **Supplements are often `.docx` / `.xlsx` / `.zip`, not PDF.** Do NOT validate them with the PDF magic-bytes check — use `file <downloaded>` (e.g. `Microsoft Word 2007+` for docx, `Microsoft Excel 2007+` for xlsx) or the download script's `--type office_zip` (it infers from the `.docx`/`.xlsx`/`.zip` extension automatically, so `--type auto` is fine). See step 6 for non-PDF verification.

6. **Download via browser navigation (same as main PDF — remember it is TWO steps).** Once an uploader attaches a file, the detail page shows "已上传文件 ... 待审核 <filename> (<size>)". Extract the `/assist/download?id=<FILE_ID>` link and navigate the browser to it (httpOnly session cookie, curl cannot authenticate), then **click `#download-continue`** on the "下载文件" page — that second click is what actually writes the file to `~/Downloads/`. Poll `ls -lat ~/Downloads/` for the new file.

**Real example (Li 2026, Biomaterials, Elsevier, no PMC copy):** user already had the main PDF; only the supplement was needed. Single supplement request with `Assist[suppl]=1`, 20 points, note "已有正文PDF，仅需要补充材料附件(Supplementary Materials，含Fig S1-S45和Table S1，文件名通常为mmc1.pdf)。请勿上传正文。谢谢！" — fulfilled in ~1 minute; uploader attached `1-s2.0-S0142961226001043-mmc1.slim.docx` (8.28 MB). Downloaded via browser nav, verified with `unzip -l` (46 embedded images + Fig. S1–S45 + Table S1 references), adopted. See Example 5 for the full trace.

### 4. Discovering supplementary file links and cross-checking

Supplementary materials often differ between publisher and PMC copies. Enumerate from BOTH sources and cross-check, or you'll silently miss files.

**From PMC** (once the article page is open in the browser, step 3a):

```bash
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a')).filter(a => /pdf|supplement|nihms|bin/i.test(a.href + ' ' + a.textContent)).map(a => ({text: a.textContent.trim().slice(0,50), href: a.href}))"
```

This returns a JSON array of `{text, href}` for every PDF/supplement anchor. Common patterns:
- Main PDF: `.../articles/<PMCID>/pdf/<filename>.pdf` (text often "PDF (1.3 MB)")
- Supplements: `.../articles/instance/<PMCID>/bin/<filename>.pdf` (text is the raw filename)

**From the publisher page** (Cell Press / Elsevier):

```bash
# After opening the publisher article page:
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a')).filter(a => /pdf|supplement|mmc|download/i.test(a.href + ' ' + a.textContent + ' ' + (a.getAttribute('download')||''))).map(a => ({text: a.textContent.trim().slice(0,60), href: a.href, download: a.getAttribute('download')||''})).filter(a => /mmc|bin|attachment|cms/i.test(a.href))"
```

Publisher supplements typically live at `cell.com/cms/<doi>/attachment/<uuid>/mmc<N>.pdf`.

**Cross-check**: compare the count and file sizes between sources. If the publisher lists 3 supplements (e.g. mmc1/mmc2/mmc3, sizes 1.12MB/2.99MB/4.57MB) but PMC only has 2 supplement files, the missing one must be fetched from the publisher page directly (publisher supplement links at `/cms/.../attachment/...` usually work with just a browser User-Agent + Referer, unlike the main PDF). Flag any discrepancy to the user and download the missing file from whichever source has it.

Download each file with the helper script in step 3d.

### 5. Name the files and directories sensibly

**Paper directory naming (user-standard, always apply):** `<YYYYMM>-<ShortKeywords>/`

- `YYYYMM` = the paper's **publication year-month**, confirmed from the PubMed or publisher record.
- `<ShortKeywords>` = a concise method name or the paper's core topic; omit the journal name.

Examples: `202009-DEPTH-ITH/`, `202609-Paper2Agent/`. This sorts directories chronologically and keeps the method or topic visible. Create the directory under the user's current working directory unless they specified another location. If the user gives a different directory name explicitly, honor it.

The workflow examples below preserve paths from their original runs. For new downloads, use the naming rule above unless the user explicitly specifies a destination.

**File naming inside the directory** — use a consistent, grep-friendly scheme so the `read-local-pdf` skill and the user can identify them later:

```
<FirstAuthor>_<Year>_<ShortTitle>_<Journal>_main.pdf
<FirstAuthor>_<Year>_<ShortTitle>_<Journal>_supplementary_<type>.pdf
```

Example: `Wolock_2019_Scrublet_CellSystems_main.pdf`, `Wolock_2019_Scrublet_CellSystems_supplementary_figures.pdf`

### 6. Verify every downloaded file

The helper script already validates `%PDF` magic bytes after each download (exit code 2 = PoW challenge page received, file auto-deleted). But still do a full integrity check — a partial PDF is a real risk with large supplements.

```bash
# Use the read-local-pdf skill's extractor, or directly:
python3 -c "import fitz; d=fitz.open('<file>'); print('pages:', d.page_count)"
file <file>   # must say "PDF document", not "HTML document" or "empty"
```

**`file`'s page count is NOT trustworthy — only its format verdict is.** It reported `0 pages` for a valid 2-page supplement and `2 pages` for a valid 19-page PDF (linearized / object-stream files confuse it). Use `file` only to answer "is this a PDF or an HTML page?", and get the real page count from PyMuPDF. If the managed python has no `fitz`, fall back to a system python that does (e.g. `/opt/homebrew/bin/python3`):

```bash
for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  "$py" -c "import fitz" 2>/dev/null && { echo "fitz OK: $py"; break; }
done
```

Print the first page's text next to the page count — a matching title is the strongest confirmation that you got the right paper (and not, say, a sibling article or a peer-review PDF).

Exit codes from `download_pdf.py`:
| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success, validated as PDF | Proceed |
| 1 | Network failure after retries | Re-run the command (partial file auto-resumes) |
| 2 | **PoW challenge page received** (cookie expired) | Re-trigger PoW (step 3b), re-harvest cookies, retry the failed file |

A valid result: `PDF document, version X.Y` + a nonzero page count. If `file` says "HTML document" or page count is 0, the download was blocked/incomplete — re-harvest the cookie (it may have expired) and retry. Delete corrupt partial files before retrying so resume doesn't append to garbage.

**Non-PDF supplements** (docx / xlsx / zip — common for Elsevier mmc and Cell mmc files): the download script (`scripts/download_pdf.py`) validates by detected file type vs. the output extension (`--type auto`, default), so it will NOT mistake a `PK\x03\x04`-headed docx for a PoW challenge page. Verify with:
```bash
file <file>   # docx→"Microsoft Word 2007+", xlsx→"Microsoft Excel 2007+", zip→"Zip archive"
# docx content sanity (count embedded images + look for Fig S / Table S text):
python3 -c "import zipfile, re; z=zipfile.ZipFile('<file>'); names=z.namelist(); print('条目数:', len(names)); print('图片数:', len([n for n in names if n.startswith('word/media')])); xml=z.read('word/document.xml').decode('utf-8','ignore'); import re; print('FigS refs:', len(re.findall(r'Figure S\d', xml))); print('TableS refs:', len(re.findall(r'Table S\d', xml)))"
# or simply
unzip -l <file> | head
```
If `file` reports "HTML document" for a supplement you expected to be docx/xlsx, the download hit a login/challenge wall — re-harvest cookies and retry (the script would already have deleted it and exited 2 if it was a small_html page).

Report to the user: final directory path, each file's size, page count (for PDFs) or entry/image count (for office archives), and the verified title from metadata.

### 7. 机构授权与中文文献分支 (Institutional access & CNKI branch)

Enter this branch when ANY of these apply — and **READ the full protocol at `references/institutional-access.md` before acting** (it defines the routing decision tree, script inventory, configuration, status codes, and boundaries):

- **中文文献** — Chinese title, `zh` metadata, a `cnki.net` link, or the user says 知网 → **CNKI route only** (via the user's logged-in Chrome session), even if an OA copy appears to exist elsewhere. `scripts/batch_download.mjs --title "<中文题名>"` handles it; add `--cnki-format pdf` when the user wants PDF (not CAJ). Never save CAJ/HTML as if it were a PDF.
- **Paywalled English paper, no free copy (no OA/PMC/preprint), but the user's institution subscribes** → Web Access route: authenticate once through the library aggregation portal / Web of Science → SFX/OpenURL full-text resolver → publisher page → save the PDF from the browser context with `scripts/browser_pdf_downloader.mjs`.
- **Elsevier / Springer Nature / IEEE with a configured API key** → publisher-API first via `scripts/configure_credentials.py` (API success ends the task; API failure auto-falls-back to the OA ladder; ask once before Web Access only after both fail).
- **Batch of 2+ papers** → `scripts/batch_download.mjs` routes OA / publisher API / CNKI / Web Access automatically and writes an audited manifest (SHA-256, route, OA evidence, status codes). This skill downloads supplements by default, so batch runs pass `--si` by default; pass `--no-si` ONLY when the user explicitly says main-text-only. The script refuses to run without one of the two flags (`si_confirmation_required`).

Hard rules for this branch (full detail in the reference file):

- **Lawful access only**: never bypass paywalls, DRM, or 2FA. Never ask for (or accept) institutional passwords, OTP codes, or session tokens in chat; never read/export cookies or browser profiles. Login handoff happens in the user's own browser tab — a saved-login confirm button may be clicked ONCE only if the user explicitly authorizes it and the page is on the expected institutional domain.
- **Reuse the user's logged-in browser session.** If automation attaches to a fresh browser profile, that failure does NOT mean the library lacks permission — reattach to the authenticated session first; believe `library_no_permission` only when the resolver/publisher explicitly says so.
- **Bounded auto-verification**: visible sliders / robot checks (incl. CNKI Geetest) get at most 2 automated attempts via `scripts/lib/anti-bot.mjs`, then hand the tab back to the user — never more.
- **Batch etiquette**: sensitive publishers one article at a time, no whole-issue downloads, keep the audit trail (manifest + `examples/carsi-retry-template.tsv` / `publisher-verification-template.tsv` when interrupted).

Scripts (absorbed from the former `nature-downloader` skill; inventory in the reference file §1): `batch_download.mjs`, `configure_school.py`, `configure_credentials.py`, `browser_pdf_downloader.mjs`, `lib/anti-bot.mjs`. Branch status codes (`carsi_waiting_user`, `library_no_permission`, `full_text_html_available`, `api_fallback_confirmation_required`, `verification_auto_passed/failed`, …) are defined in the reference file §8.

After a successful branch download, the paper re-enters the main pipeline: verify (step 6) → report. CAJ is delivered natively; HTML full text is saved and reported as `full_text_html_available` with a plain statement that no PDF was available.

## Anti-patterns

- **Don't try bare `curl` on PMC and give up when it "fails".** The 1.8KB HTML response is the PoW challenge, not a real failure — it's a signal to use the browser-cookie method.
- **Don't harvest cookies from the article page and assume PoW is done.** The `cloudpmc-viewer-pow` cookie only appears AFTER navigating to a PDF direct-link URL (step 3b). Cookies from the article page alone lack the PoW token and will return challenge pages. Always sanity-check: `echo "$COOKIES" | grep cloudpmc-viewer-pow`.
- **Don't descend the source-priority ladder just because `curl` 403s the publisher.** A publisher 403/HTML (Akamai, Cloudflare) blocks *automated curl*, not a real browser. Per the source-priority rule, the publisher official version comes FIRST — try driving `opencli browser` to obtain it (including the ScienceDirect same-origin-fetch technique for the two-layer-anti-bot case) before falling back to PMC. Only drop to PMC/preprint when the publisher truly won't serve bytes even via browser (hard paywall, no OA). Related: don't keep retrying the *same curl approach* that 403s — Cell/Elsevier `showPdf`/`pdfExtended` links have anti-bot beyond cookies, so no header tweak fixes curl; switch *tactic* (curl → browser), not *source* (publisher → PMC).
- **Don't write a one-off inline Python download script.** Use `scripts/download_pdf.py`; it has the retry/resume/chunk logic AND the `%PDF` magic-bytes validation that catches PoW challenge pages.
- **Don't download only the main PDF and call it done** when the user asked for "附件/supplements too". Supplements live at different URLs (the `/bin/` path on PMC, the `/cms/.../attachment/` path on Cell) — enumerate them in step 4 (from both sources!) and download each.
- **Don't claim success without verifying.** A 0-page or HTML-typed file is a failed download, not a success. The helper script now rejects non-PDF content (exit 2), but still run the step-6 page-count check and report real numbers.
- **Don't ignore the helper script's exit code 2.** Exit 2 specifically means "got PoW challenge, cookie expired" — re-trigger PoW (step 3b) and retry, rather than treating it as a generic network failure.
- **Don't try to `curl` a 科研通/ablesci download URL.** The `/assist/download?id=...` endpoint requires the httpOnly session cookie, which `document.cookie` cannot read and curl therefore cannot send. You'll get a 49KB HTML login page instead of the PDF. Always download by **navigating the browser** (`opencli browser <session> open <download-url>`) so Chrome sends the httpOnly cookie itself; the PDF lands in `~/Downloads/`.
- **Don't stop after navigating to the `/assist/download?id=...` URL — that's only step 1 of 2.** The page you land on is a JS-driven "下载文件 - 科研通" shell (`document.contentType === "text/html"`, filename + size + 线路1/2/3 + ⚡高速通道 + `#download-continue`). No file is written until you click `#download-continue`. Symptom of missing this: the browser is on the right URL, `~/Downloads/` is empty, and it looks like a silent failure. The action buttons carry no `onclick` attribute, so href/onclick scraping returns nothing — click by id.
- **Don't click `#download-continue` more than once.** A second click re-downloads the same file; Chrome names it `... (1).pdf`. Compare with `md5 -q` and delete the duplicate.
- **Don't post a second ablesci request before adopting the first.** The site blocks new posts while a fulfilled request is unprocessed, with a misleading "处理提示" page that looks like the form failed to load. Adopt the prior file (step 3b.h–i), then re-open `/assist/create`.
- **Don't try to register or log in to ablesci yourself.** The session must already be authenticated with the user's own account. If `document.querySelector('.user-info,...')` shows no username, ask the user to log in first.
- **Don't jump to 科研通 for supplements when a free CDN link exists.** Most publisher supplements are FREE even when the main text is paywalled — Elsevier's `ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc<N>.<ext>`, Cell's `/cms/.../attachment/`, Nature's `static-content.nature.com`, and PMC's `/bin/` all serve supplements without auth. Always try these free direct links (for Elsevier, probe several extensions: `.pdf` → `.docx` → `.zip` → `.xlsx` — a 404 means the extension is wrong, not that the file is paywalled) BEFORE posting a 科研通 supplement request. The ablesci split (below) is the LAST resort, for the rare case where the main text needed 科研通 AND the free supplement links all failed.
- **Don't combine main-text and supplement requests in one ablesci request.** ablesci requires them split: `Assist[suppl]=0` for main text, `Assist[suppl]=1` for "仅需补充材料". A same-DOI re-post is blocked within ~1 hour (the POST `/assist/create` AJAX returns `code:1` + a `/assist/detail?id=...` link to the existing request — navigate to that instead of re-posting). Order: post main → adopt → post supplement. Supplement悬赏 = 正文 × 2 (check the form's tip text), or submission silently fails.
- **Don't validate `.docx` / `.xlsx` / `.zip` supplements with the PDF magic-bytes check.** Their signature is `PK\x03\x04`, not `%PDF` — an `is_pdf`-style check would flag them as "PoW challenge page" and delete them. The download script now validates by detected type vs. the output extension (`--type auto`), so it handles non-PDF supplements correctly. For manual checks use `file <path>` (`Microsoft Word 2007+` / `Microsoft Excel 2007+` / `Zip archive`), or `--type office_zip` if the output path has no recognizable extension.
- **Don't route a Nature OA article through PMC just because the publisher page "redirects to idp.nature.com".** That SSO redirect chain (`303 → authorize → transit → ?error=cookies_not_supported → 200 PDF`) is NOT a paywall for OA articles — `curl -L` with a browser UA + Referer lands the real PDF (verified byte-identical to the PMC copy, same MD5). Only fall back to PMC when the final response is actually an HTML login page (i.e. the article is subscription-only). Treating the SSO redirect as a block wastes time on the PoW dance for no reason.
- **Don't forget `curl -g` when the URL contains `[` `]`** — the NCBI E-utilities DOI idiom `term=<doi>[doi]` is a *zsh glob*, and zsh aborts with `curl: (3) bad range in URL position N` before the request is even sent. Use `curl -gsS "…&term=10.1038%2Fs41592-020-01018-y%5Bdoi%5D&retmode=json"` (or `--globoff`). Symptom of getting this wrong: an empty `PMID:` and a Python `JSONDecodeError: Expecting value: line 1 column 1`.
- **Don't trust the DOI in a README/badge short-link.** The Cellpose README's Nature Methods link hid `10.1038/s41592-020-01018-y`; the real DOI is `…-01018-x` (the `-y` returns a Nature 404). When a DOI-based lookup returns zero hits, resolve the *title* through bioRxiv's API (`api.biorxiv.org/details/biorxiv/<preprint-doi>` → the `published` field carries the journal DOI) or Europe PMC before concluding the paper doesn't exist.
- **Don't `curl` a Cloudflare-fronted host repeatedly hoping it clears.** bioRxiv 403s every time — switch tactic to the browser same-origin fetch on the first 403 rather than retrying with different headers.
- **Don't run a multi-hundred-MB download in the foreground.** Supplement videos on Springer/Nature CDNs can take 30+ min; always background it and loop `curl -C -` against a known total size.
- **Don't report a page count from `file`.** It is wrong for object-stream PDFs (`0 pages`, `2 pages` for real 2-/19-page files). Use PyMuPDF.
- **Don't put Chinese literature through the English ladder.** A Chinese title never goes to PubMed/arXiv/科研通 — CNKI is the only route (step 7), even when an OA copy exists elsewhere.
- **Don't ask for (or accept) institutional passwords, OTP codes, or session tokens in chat, and never export cookies/browser profiles.** Login handoff happens in the user's own browser tab; a saved-login confirm button may be clicked once only with the user's explicit authorization, on the expected institutional domain, without reading or typing any credential. (Publisher API keys follow the separate save-on-receipt rule in the reference file §4.)
- **Don't run `batch_download.mjs` without `--si` or `--no-si`.** The script refuses (`si_confirmation_required`) by design; this skill's default is `--si` because supplements download by default.
- **Don't treat a fresh-profile automation failure as "the library has no permission".** Reattach to the user's authenticated browser session first; only report `library_no_permission` when the portal/SFX resolver/publisher explicitly says the institution lacks entitlement.
- **Don't save CAJ or HTML as if it were a PDF.** Format is part of the deliverable: deliver CAJ natively, save readable HTML full text as `full_text_html_available` and say plainly that no PDF was available through the current route.
- **Don't spam publisher/API or institutional routes.** One article at a time for sensitive publishers, no whole-issue/volume downloads, bounded verification attempts, and keep the manifest + retry-sheet audit trail.

## Open-access shortcuts

For sources with no anti-bot, skip the browser entirely:

```bash
# arXiv
curl -L -o "Author_Year_Title_arxiv.pdf" "https://arxiv.org/pdf/<id>.pdf"

# bioRxiv — NO LONGER curl-able. As of 2025+ bioRxiv is behind Cloudflare:
#   curl -L "https://www.biorxiv.org/content/<doi>v<ver>.full.pdf"
#   -> 403, ~5.8KB HTML whose <title> is "Just a moment..."  (Cloudflare interstitial)
# Use the browser same-origin-fetch + base64 drain instead (see "bioRxiv / Cloudflare
# sites — same-origin fetch extraction" below). The bioRxiv metadata API is still
# plain-curl-friendly and is the cheap way to list versions / find the published DOI:
#   curl -sS "https://api.biorxiv.org/details/biorxiv/<doi>"   # per-version list

# GitHub-hosted PDF
curl -L -o "file.pdf" "https://github.com/<repo>/raw/<branch>/<path>.pdf"

# Nature OA article (npj / Nature Communications / Nature Methods / etc.)
# The SSO redirect chain (idp.nature.com/authorize → transit → ?error=cookies_not_supported)
# is NOT a paywall for OA articles — the final 200 serves the real PDF.
# Requires a browser UA + the article page as Referer.
curl -sS -L \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
  -H "Referer: https://www.nature.com/articles/<article-id>" \
  -o "Author_Year_Title_Journal_main.pdf" \
  "https://www.nature.com/articles/<article-id>.pdf"
```

If these return a valid PDF (check with `file`), done. If they return HTML, fall back to the browser-cookie method (or, for Nature subscription articles, the Publisher → PMC fallback).

## Example 1 (PMC direct — the Scrublet case)

User: "下载 Scrublet 方法对应的文献及附件到 Scrublet 目录"

```bash
# 1. identify: PMID 30954476 → PMCID PMC6625319 (Wolock et al. 2019, Cell Systems)
# 2. source = PMC → browser-cookie method
mkdir -p Scrublet
opencli browser paperdl open "https://pmc.ncbi.nlm.nih.gov/articles/PMC6625319/"
sleep 3
# TRIGGER PoW by navigating to the PDF direct link:
opencli browser paperdl open "https://pmc.ncbi.nlm.nih.gov/articles/PMC6625319/pdf/nihms-1515604.pdf"
sleep 10
COOKIES=$(opencli browser paperdl eval "document.cookie")
# sanity check: echo "$COOKIES" | grep cloudpmc-viewer-pow  # must be present
# 3. enumerate links
opencli browser paperdl eval "Array.from(document.querySelectorAll('a')).filter(a => /pdf|supplement|bin/i.test(a.href)).map(a => a.href)"
#   → main:  .../PMC6625319/pdf/nihms-1515604.pdf
#   → supp:   .../instance/6625319/bin/NIHMS1515604-supplement-Supp_figures.pdf
# 4. download both
python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/PMC6625319/pdf/nihms-1515604.pdf" \
  "Scrublet/Wolock_2019_Scrublet_CellSystems_main.pdf" \
  "$COOKIES" --referer "https://pmc.ncbi.nlm.nih.gov/articles/PMC6625319/"
python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/instance/6625319/bin/NIHMS1515604-supplement-Supp_figures.pdf" \
  "Scrublet/Wolock_2019_Scrublet_CellSystems_supplementary_figures.pdf" \
  "$COOKIES" --referer "https://pmc.ncbi.nlm.nih.gov/articles/PMC6625319/"
# 5. verify
python3 -c "import fitz; [print(f, fitz.open(f).page_count) for f in ['Scrublet/Wolock_..._main.pdf','Scrublet/Wolock_..._supplementary_figures.pdf']]"
```

Result: 38-page main PDF + 7-page supplement, both verified.

## Example 2 (Cell Press 403 → PMC fallback — the Xi & Li 2021 case)

User gave a `cell.com` URL; publisher direct links returned 403.

```bash
# 1. Publisher links enumerated: showPdf (403), pdfExtended (403), 3 supplements at /cms/.../attachment/.../mmc{1,2,3}.pdf
# 2. Fallback: resolve DOI 10.1016/j.cels.2020.11.008 → PMID 33338399 → PMCID PMC7897250
curl -sS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=10.1016/j.cels.2020.11.008[doi]"
#    → 33338399
curl -sS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id=33338399"
#    → PMC7897250
# 3. PMC browser-cookie method (note: trigger PoW by navigating to PDF URL!)
opencli browser pmcdl open "https://pmc.ncbi.nlm.nih.gov/articles/PMC7897250/"
sleep 3
opencli browser pmcdl open "https://pmc.ncbi.nlm.nih.gov/articles/PMC7897250/pdf/nihms-1656187.pdf"
sleep 10
COOKIES=$(opencli browser pmcdl eval "document.cookie")
# sanity: echo "$COOKIES" | grep cloudpmc-viewer-pow
# 4. enumerate (PMC lists 2 supplements; publisher listed 3 — cross-check!)
#    publisher mmc1.pdf (1.12MB) had no PMC counterpart → fetch from publisher /cms/ link
# 5. download from PMC
python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/PMC7897250/pdf/nihms-1656187.pdf" \
  "Scrublet/Xi_2021_BenchmarkingDoubletDetection_CellSystems_main.pdf" \
  "$COOKIES" --referer "https://pmc.ncbi.nlm.nih.gov/articles/PMC7897250/"
# ...download supplements similarly...
# 6. verify: main 44pp, supp_1 31pp, supp_tables 17pp ✓
```

Result: main PDF + 2 supplements from PMC verified. (The publisher's 3rd supplement had no separate PMC file — flagged to user; fetched directly from the publisher `/cms/.../attachment/` URL if needed.)

## Example 3 (Wiley paywalled, no PMC → 科研通 mutual-aid — the Zhao 2024/2025 OTM RNA-seq case)

Two Wiley subscription papers (Int Endod J 2024, J Periodontal Res 2025) had no PMC open-access copy, plus one open-access companion paper on PMC. The two Wiley papers were obtained via 科研通; the PMC one via the PoW browser-cookie method.

```bash
SESSION="ablesci"
mkdir -p references/zhao_OTM_RNAseq_papers

# ── Paper 1: Wiley, no PMCID → 科研通 ──
# 0. confirm login
opencli browser "$SESSION" open "https://www.ablesci.com/"
sleep 3
opencli browser "$SESSION" eval "document.querySelector('.user-info,.avatar,[class*=user]')?.textContent?.trim() || 'NO LOGIN'"

# 1. post request
opencli browser "$SESSION" open "https://www.ablesci.com/assist/create"
sleep 6
opencli browser "$SESSION" eval "document.querySelector('#Assist-doi') ? 'ready' : 'not ready'"
opencli browser "$SESSION" fill "#Assist-doi"   "10.1111/iej.14131"
opencli browser "$SESSION" fill "#Assist-title" "How does orthodontic tooth movement influence the dental pulp? RNA-sequencing on human premolars"
opencli browser "$SESSION" fill "#Assist-url"   "https://onlinelibrary.wiley.com/doi/10.1111/iej.14131"
opencli browser "$SESSION" fill "#Assist-note"  "Zhao Z et al. Int Endod J 2024 Dec;57(12):1783-1801. PMID:39086033. 需要全文PDF。谢谢！"
opencli browser "$SESSION" click "#form-submit-btn"
sleep 5

# 2. get request id
opencli browser "$SESSION" open "https://www.ablesci.com/my/assist-my"
sleep 3
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a')).filter(a => /assist\/detail/i.test(a.href)).map(a => a.href)[0]"
#   → https://www.ablesci.com/assist/detail?id=zBBmOa

# 3. wait for upload, then download via BROWSER NAVIGATION (not curl!)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=zBBmOa"
sleep 4
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a[href*=download]')).map(a => a.href)[0]"
#   → https://www.ablesci.com/assist/download?id=W9jJRG
opencli browser "$SESSION" open "https://www.ablesci.com/assist/download?id=W9jJRG"
sleep 60 && ls -lat ~/Downloads/ | head -3
#   → "How does orthodontic tooth movement...(科研通-ablesci.com).pdf"  (23.7MB)

# 4. move + rename + verify
mv ~/Downloads/*科研通-ablesci.com\).pdf references/zhao_OTM_RNAseq_papers/Zhao_2024_DentalPulp_OTM_RNAseq_IntEndodJ_main.pdf
python3 -c "import fitz; print('pages:', fitz.open('references/zhao_OTM_RNAseq_papers/Zhao_2024_DentalPulp_OTM_RNAseq_IntEndodJ_main.pdf').page_count)"

# 5. adopt the file (REQUIRED before posting the next request)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=zBBmOa"
sleep 4
opencli browser "$SESSION" eval "document.querySelectorAll('.btn-handle-file')[0]?.click()"
sleep 3
opencli browser "$SESSION" eval "document.querySelector('.layui-layer-btn0')?.click()"
sleep 5
opencli browser "$SESSION" eval "document.body.innerText.replace(/\s+/g,' ').includes('已完成') ? 'completed' : 'still pending'"

# ── Paper 2: same Wiley/no-PMCID flow, after adopting paper 1 ──
opencli browser "$SESSION" open "https://www.ablesci.com/assist/create"   # now loads (no pending block)
sleep 6
# ...same fill/submit/retrieve/download/adopt steps with DOI 10.1111/jre.13352...
# Result: Zhao_2025_PDL_OTM_JPeriodontalRes_main.pdf (29.1MB, 20pp) ✓

# ── Paper 3: open access on PMC → PoW browser-cookie method (step 3) ──
opencli browser pmc open "https://pmc.ncbi.nlm.nih.gov/articles/PMC12644353/"
sleep 4
opencli browser pmc open "https://pmc.ncbi.nlm.nih.gov/articles/PMC12644353/pdf/40510_2025_Article_596.pdf"
sleep 10
COOKIES=$(opencli browser pmc eval "document.cookie")
python3 <skill_dir>/scripts/download_pdf.py \
  "https://pmc.ncbi.nlm.nih.gov/articles/PMC12644353/pdf/40510_2025_Article_596.pdf" \
  "references/zhao_OTM_RNAseq_papers/Zhao_2025_SexAge_OTM_PDL_DP_ProgOrthod_main.pdf" \
  "$COOKIES" --referer "https://pmc.ncbi.nlm.nih.gov/articles/PMC12644353/"
# Result: 19pp, 3.4MB ✓
```

Result: all 3 papers downloaded. Two Wiley subscription PDFs via 科研通 mutual-aid (each fulfilled in ~1–3 min, adopted to reward uploaders), one open-access PDF via PMC PoW. Key lessons encoded in this example: (1) httpOnly cookies force browser-navigation downloads on ablesci; (2) the site blocks new requests while a fulfilled one is unadopted; (3) the adopt popup sometimes needs two `.layui-layer-btn0` clicks.

## Example 4 (Nature OA direct link — the Xie 2026 SQLE case)

A Nature-hosted OA article (npj Precision Oncology). The publisher page redirects through `idp.nature.com/authorize` (SSO), which looks like a block but is not — OA articles fall back to the free copy when no SSO cookie is present. No browser, no PoW needed.

```bash
# 0. identify: DOI 10.1038/s41698-026-01529-4 → PMID 42215741 → PMCID PMC13246886 (OA, CC BY)
#    Article page: https://www.nature.com/articles/s41698-026-01529-4
#    PDF direct link: https://www.nature.com/articles/s41698-026-01529-4.pdf
mkdir -p SQLE_LIHC_Xie_2026

# 1. main PDF — single curl, no browser/PoW
curl -sS -L \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
  -H "Referer: https://www.nature.com/articles/s41698-026-01529-4" \
  -H "Accept: application/pdf,*/*" \
  -o "SQLE_LIHC_Xie_2026/Xie_2026_SQLE_LIHC_npjPrecisionOncol_main.pdf" \
  "https://www.nature.com/articles/s41698-026-01529-4.pdf"
#   redirect chain observed: 303 → idp.nature.com/authorize → 302 → idp.nature.com/transit
#   → 302 → .../s41698-026-01529-4.pdf?error=cookies_not_supported → 200 (real PDF, 6912989 bytes)
#   `file` → "PDF document, version 1.4"; fitz → 19 pages; title metadata matches.

# 2. supplementary .xlsx — same UA+Referer, no SSO redirect for supplement assets
#    (supplement links live under static-content.nature.com / media.springernature.com,
#    which don't run the grover SSO flow). Enumerate them by scraping the article page,
#    or fall back to PMC's /articles/instance/<PMCID>/bin/<file> path.
curl -sS -L \
  -H "User-Agent: Mozilla/5.0 (...)" \
  -H "Referer: https://www.nature.com/articles/s41698-026-01529-4" \
  -o "SQLE_LIHC_Xie_2026/Xie_2026_SQLE_LIHC_npjPrecisionOncol_supplementary_MOESM1.xlsx" \
  "https://pmc.ncbi.nlm.nih.gov/articles/instance/13246886/bin/41698_2026_1529_MOESM1_ESM.xlsx"
#   `file` → "Microsoft Excel 2007+"; openpyxl loads Sheet1; 19.48 MB.

# 3. verify — both files
file SQLE_LIHC_Xie_2026/*
python3 -c "import fitz; print('main pages:', fitz.open('SQLE_LIHC_Xie_2026/Xie_2026_SQLE_LIHC_npjPrecisionOncol_main.pdf').page_count)"

# 4. cross-check against PMC copy (optional sanity check that OA editions match)
md5 -q SQLE_LIHC_Xie_2026/Xie_2026_SQLE_LIHC_npjPrecisionOncol_main.pdf
#   → 321a10282191c165465526f813822390 (identical to the PMC-fetched copy in testing)
```

Result: 19-page main PDF (6.91 MB) + 19.48 MB supplementary xlsx, both verified. The Nature direct link produced a main PDF **byte-identical** (same MD5) to the PMC copy — confirming that for OA articles the SSO redirect chain is a no-op, not a paywall. Lesson: for Nature-family OA journals, try `nature.com/articles/<id>.pdf` with UA+Referer FIRST; only fall back to PMC PoW if `file` reports HTML (i.e. the article is actually subscription-only). This skips the entire browser/PoW dance and saves ~30s + a browser session per paper.

## Example 5 (Elsevier paywalled main text, FREE supplement on CDN, supplement-only via 科研通 — the Li 2026 sea-cucumber hydrogel case)

An Elsevier *Biomaterials* 2026 paper (Li et al., DOI 10.1016/j.biomaterials.2026.124080, PMID 41713048). The user already had the main PDF from their own institutional access and only needed the supplementary materials (Fig. S1–S45 + Table S1). No PMC open-access copy existed (elink returned `pubmed_pmc_refs` — PMC articles that *cite* this paper, not a copy of it). ScienceDirect blocked automated access to the article page (curl 403; `opencli browser` got an "Are you a robot?" captcha).

**⚠️ Post-mortem note: the supplement was actually FREE on the Elsevier CDN.** The correct free direct link is `https://ars.els-cdn.com/content/image/1-s2.0-S0142961226001043-mmc1.docx` — it returns the full 49.8 MB docx with no auth, no SSO, no captcha. The `mmc1.pdf` 404 we hit earlier was a **wrong-extension** miss (the file is `.docx`, not `.pdf`), not a paywall. The 科研通 path below worked but cost the user 20 points and ~5 min of round-trip that was unnecessary. **The lesson encoded in this skill: for Elsevier supplements, always try `ars.els-cdn.com/content/image/1-s2.0-<PII>-mmc<N>.<ext>` with several extensions (.pdf → .docx → .zip → .xlsx) BEFORE falling back to 科研通.** This example is kept as a reference for the 科研通 supplement-request mechanics (3b.2) and the AJAX-interceptor debugging trick, which remain valid when the free path genuinely fails.

Fell back to 科研通 for the supplement only (what was actually done):

```bash
SESSION="pmcdl"
# 0. Confirm there is no PMC copy of THIS paper (elink linkname must be pubmed_pmc_refs, NOT pmc):
curl -sS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id=41713048&retmode=json"
#   → linkname "pubmed_pmc_refs" with links to PMC13361327 etc. = those are papers CITING this one, not this paper's copy. No self-PMCID → paywalled, use 科研通.

# 1. Confirm ablesci login (user "信你个鬼" was already authenticated)
opencli browser "$SESSION" open "https://www.ablesci.com/"
sleep 3
opencli browser "$SESSION" eval "document.querySelector('.user-info,.avatar,[class*=user]')?.textContent?.trim() || 'NO LOGIN'"

# 2. Open the create form and fill the four required fields
opencli browser "$SESSION" open "https://www.ablesci.com/assist/create"
sleep 6
opencli browser "$SESSION" eval "document.querySelector('#Assist-doi') ? 'ready' : 'not ready'"
opencli browser "$SESSION" fill "#Assist-doi"   "10.1016/j.biomaterials.2026.124080"
opencli browser "$SESSION" fill "#Assist-title" "Biomimetic hydrogel strategy inspired by sea cucumbers: Integrating antibacterial, osteoimmune, and osteogenic functions for infected bone repair"
opencli browser "$SESSION" fill "#Assist-url"   "https://www.sciencedirect.com/science/article/pii/S0142961226001043"
opencli browser "$SESSION" fill "#Assist-note"  "Li X et al. Biomaterials 2026;330:124080. PMID:41713048. 已有正文PDF，仅需要补充材料附件(Supplementary Materials，含Fig S1-S45和Table S1，文件名通常为mmc1.pdf)。请勿上传正文。谢谢！"

# 3. SELECT "仅需补充材料" (Assist[suppl] value=1) — NOT the default value=0
opencli browser "$SESSION" eval "document.querySelector('input[name=\"Assist[suppl]\"][value=\"1\"]').click(); 'suppl=1'"
#    sanity: document.querySelector('input[name=\"Assist[suppl]\"][value=\"1\"]').checked === true

# 4. RAISE points to 2× the main-text minimum (Elsevier main=10 → supplement=20)
opencli browser "$SESSION" eval "const el=document.querySelector('#Assist-point'); el.value=''; el.focus(); 'cleared'"
opencli browser "$SESSION" fill "#Assist-point" "20"

# 5. Submit. If it "fails" silently, capture the AJAX response to see why:
opencli browser "$SESSION" eval "window.__cap=[]; const o=XMLHttpRequest.prototype.open,s=XMLHttpRequest.prototype.send; XMLHttpRequest.prototype.open=function(m,u){this._u=u;this._m=m;return o.apply(this,arguments)}; XMLHttpRequest.prototype.send=function(b){this.addEventListener('load',function(){window.__cap.push({m:this._m,u:this._u,s:this.status,r:(this.responseText||'').slice(0,400)})}); return s.apply(this,arguments)}; 'interceptor'"
opencli browser "$SESSION" eval "document.querySelector('#form-submit-btn').click()"
sleep 5
opencli browser "$SESSION" eval "JSON.stringify(window.__cap)"
#   → POST /assist/create returned code:1 "系统检测到您在1小时内发布了相同DOI的文献求助 <a href=\"/assist/detail?id=99AyoX\">点击查看</a>"
#   The first submission DID create a request (id=99AyoX) despite looking "failed". Navigate to it.

# 6. Detail page — an uploader already attached the supplement
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=99AyoX"
sleep 4
opencli browser "$SESSION" eval "Array.from(document.querySelectorAll('a[href*=download]')).map(a => ({text: a.textContent.trim().slice(0,50), href: a.href}))"
#   → [{ text: "1-s2.0-S0142961226001043-mmc1.slim.docx", href: "https://www.ablesci.com/assist/download?id=oGmBlG" }]

# 7. Download via BROWSER NAVIGATION (httpOnly cookie — curl would get a 49KB HTML login page)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/download?id=oGmBlG"
sleep 25 && ls -lat ~/Downloads/ | head -5
#   → 1-s2.0-S0142961226001043-mmc1.slim(科研通-ablesci.com).docx  (8.68 MB)

# 8. Verify the NON-PDF supplement with `file` + unzip (NOT is_pdf — docx starts with PK\x03\x04)
file ~/Downloads/1-s2.0-S0142961226001043-mmc1.slim*.docx   # → "Microsoft Word 2007+"
python3 -c "import zipfile,re; z=zipfile.ZipFile('$HOME/Downloads/1-s2.0-S0142961226001043-mmc1.slim(科研通-ablesci.com).docx'); n=z.namelist(); print('条目:',len(n),'图片:',len([x for x in n if x.startswith('word/media')])); xml=z.read('word/document.xml').decode('utf-8','ignore'); print('FigS refs:',len(re.findall(r'Figure S\d',xml)),'TableS refs:',len(re.findall(r'Table S\d',xml)))"
#   → 条目: 77  图片: 46  FigS refs: 26  TableS refs: present  (= Supporting Information with Fig S1–S45 + Table S1) ✓

# 9. Move + rename into the paper directory (current working dir, by convention)
mv ~/Downloads/1-s2.0-S0142961226001043-mmc1.slim\(科研通-ablesci.com\).docx \
   ./Li_2026_SeaCucumberHydrogel_Biomaterials/Li_2026_SeaCucumberHydrogel_Biomaterials_supplementary_mmc1.docx

# 10. ADOPT the uploaded file (rewards the uploader, unblocks future requests)
opencli browser "$SESSION" open "https://www.ablesci.com/assist/detail?id=99AyoX"
sleep 4
opencli browser "$SESSION" eval "document.querySelectorAll('.btn-handle-file')[0]?.click(); 'clicked'"
sleep 3
# Two chained layui confirm popups — click "确定" on each
opencli browser "$SESSION" eval "document.querySelectorAll('.layui-layer-btn0').forEach(b=>b.click()); 'confirmed all'"
sleep 4
opencli browser "$SESSION" eval "document.body.innerText.replace(/\s+/g,' ').includes('已完结') ? 'completed' : 'still pending'"
#   → "操作成功，感谢使用科研通" → status "已完结" ✓
```

Result: `Li_2026_SeaCucumberHydrogel_Biomaterials_supplementary_mmc1.docx` (8.68 MB) — the Elsevier mmc1 supplement (Fig. S1–S45 + Table S1, 46 embedded images), verified via `unzip` + regex on `word/document.xml`, downloaded via browser navigation (httpOnly cookie), and the ablesci request adopted to reward the uploader. Key lessons encoded: (1) `pubmed_pmc_refs` elink ≠ a self-PMCID — those are citing papers, not the paper's own OA copy; (2) ablesci's same-DOI 1-hour block fires even for "failed-looking" first submissions — capture the `/assist/create` AJAX to find the real request id; (3) `Assist[suppl]=1` + 2× points + "请勿上传正文" note is the correct supplement-request configuration; (4) verify docx supplements with `file`/`unzip`, never with `is_pdf`.

## Example 6 (iScience OA, two-layer anti-bot — the Zhou 2026 cancer-associated thrombosis case)

User gave a ScienceDirect URL: `https://www.sciencedirect.com/science/article/pii/S2589004226025290`. PII prefix `S2589-0042` = iScience (Cell Press, Gold OA, CC BY). The paper was brand-new (pub 2026/09) and **not yet indexed in PubMed/PMC** (Europe PMC PII search hitCount 0; NCBI esearch by DOI found no PMID) — so the publisher was the *only* free copy. Source priority (rule 1) said: get the publisher version, don't fall back just because it's hard. It was hard — two anti-bot layers stacked.

```bash
SESSION="isdldemo"
PII="S2589004226025290"
ART="https://www.sciencedirect.com/science/article/pii/$PII"
mkdir -p iScience_CAT_singlecell_2026

# 0. metadata via real browser (curl gets a JS-bootstrap page with no article data)
opencli browser "$SESSION" open "$ART"; sleep 6
opencli browser "$SESSION" eval "JSON.stringify({title:document.querySelector('meta[name=citation_title]')?.content, doi:document.querySelector('meta[name=citation_doi]')?.content, journal:document.querySelector('meta[name=citation_journal_title]')?.content})"
#   → title "Single-cell immune profiling of blood and thrombus in cancer-associated thrombosis",
#     doi 10.1016/j.isci.2026.117151, journal iScience, first author Linlin Zhou
#   "View PDF" link = $ART/pdfft?md5=<token>&pid=1-s2.0-$PII-main.pdf

# 1. curl probes that FAIL (documenting why the browser path is needed):
#    - curl $ART/pdfft?...            -> 403 HTML (Akamai _abck/bm_sz, httpOnly)
#    - curl ars.els-cdn.com/content/article/1-s2.0-$PII-main.pdf  -> 404 (CDN hosts images/supplements only)
#    - curl the signed pdf.sciencedirectassets.com URL (even + Referer + Sec-Fetch) -> 63KB "Security verification" HTML
#      (the S3 host runs its OWN Cloudflare; curl has no cf_clearance)

# 2. drive browser to pdfft -> 302 to signed S3 URL -> Cloudflare passes -> Chrome renders PDF
opencli browser "$SESSION" open "$ART/pdfft?md5=<token>&pid=1-s2.0-$PII-main.pdf"
# poll until URL host == pdf.sciencedirectassets.com (signed URL, 5-min expiry)
opencli browser "$SESSION" eval "document.contentType"   # -> "application/pdf"

# 3. SAME-ORIGIN fetch -> base64-chunk drain to disk (the only way to get bytes out)
opencli browser "$SESSION" eval "(async function(){var r=await fetch(location.href,{credentials:'include'});window.__pdfBytes=new Uint8Array(await r.arrayBuffer());return JSON.stringify({size:window.__pdfBytes.length,head:Array.from(window.__pdfBytes.slice(0,8)).map(function(b){return (b<16?'0':'')+b.toString(16)}).join('')})})()"
#   -> {"size":14542815,"head":"255044462d312e37"}  (%PDF-1.7)
OUT="iScience_CAT_singlecell_2026/Zhou_2026_SingleCellCAT_iScience_main.pdf"; : > "$OUT"; TOTAL=14542815; CHUNK=500000; off=0
while [ $off -lt $TOTAL ]; do
  B64=$(opencli browser "$SESSION" eval "(function(){var b=window.__pdfBytes;if(!b)return 'NOBUF';var s=b.subarray($off,Math.min($off+$CHUNK,b.length));var bin='';for(var i=0;i<s.length;i+=8192){bin+=String.fromCharCode.apply(null,s.subarray(i,i+8192))}return btoa(bin)})()")
  [ "$B64" = "NOBUF" ] && break; printf '%s' "$B64" | base64 -d >> "$OUT"; off=$((off+CHUNK))
done
#   -> file: PDF document v1.7; fitz: 17 pages; head %PDF-1.7 / tail %%EOF ✓

# 4. supplements — FREE on the open CDN (no browser needed); probe extensions
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ... Chrome/126.0.0.0 Safari/537.36"
for n in 1 2 3; do for ext in pdf docx zip xlsx; do
  curl -sS -o /dev/null -w "mmc${n}.${ext} %{http_code}\n" -H "User-Agent: $UA" -H "Referer: $ART" \
    "https://ars.els-cdn.com/content/image/1-s2.0-$PII-mmc${n}.${ext}"
done; done
#   -> mmc1.pdf 200 (5.9MB, Document S1), mmc2.xlsx 200 (8.8KB, Table S4), mmc3.xlsx 200 (13KB, Table S5); others 404
curl -sS -L -H "User-Agent: $UA" -H "Referer: $ART" -o "..._mmc1_DocumentS1.pdf"  "https://ars.els-cdn.com/content/image/1-s2.0-$PII-mmc1.pdf"
curl -sS -L -H "User-Agent: $UA" -H "Referer: $ART" -o "..._mmc2_TableS4.xlsx"   "https://ars.els-cdn.com/content/image/1-s2.0-$PII-mmc2.xlsx"
curl -sS -L -H "User-Agent: $UA" -H "Referer: $ART" -o "..._mmc3_TableS5.xlsx"   "https://ars.els-cdn.com/content/image/1-s2.0-$PII-mmc3.xlsx"
#   -> mmc1: PDF v1.7, 16pp; mmc2: Excel "Table S4"; mmc3: Excel "Table S5A","Table S5B" ✓
```

Result: 17-page main PDF (13.9 MB) + 3 supplements (mmc1.pdf 16pp, mmc2.xlsx, mmc3.xlsx), all verified. Key lessons encoded: (1) **source priority rule 1 held even though the publisher was the hardest path** — the paper was OA but freshly published with no PMC copy yet, so the publisher was the only free source; a curl 403 is a signal to switch *tactic* (curl → real browser), not to switch *source* (publisher → PMC); (2) ScienceDirect stacks **two** anti-bot layers (Akamai on `sciencedirect.com` + Cloudflare on `pdf.sciencedirectassets.com`), and the signed S3 URL is useless to curl because of the second layer — only the browser passes both; (3) once the browser is on the signed URL, **same-origin `fetch(location.href)` + base64-chunk drain** is the reliable byte-extraction method (`opencli browser network` does not capture the top-level navigation document body); (4) Elsevier supplements remain free on `ars.els-cdn.com/content/image/` even for this OA paper — enumerate by probing `.pdf`→`.docx`→`.zip`→`.xlsx` per mmc index.

## Example 7 (one repo → its whole citation set, mixed OA/paywall/Cloudflare — the Cellpose case)

User: "阅读 https://github.com/MouseLand/cellpose ，把这个算法对应的文献下载下来"

The repo's README cited **four** papers spanning the algorithm's lineage. Resolving all four *before* downloading anything is what makes this cheap — the four needed three completely different tactics.

```bash
# 0. Enumerate the citations from the repo README, then resolve each to DOI/PMID/PMCID.
#    Cellpose 1.0 10.1038/s41592-020-01018-x | Cellpose 2.0 10.1038/s41592-022-01663-4
#    Cellpose3    10.1038/s41592-025-02595-5 | Cellpose-SAM 10.1101/2025.04.28.651001
for doi in ...; do
  pmid=$(curl -gsS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${doi}%5Bdoi%5D&retmode=json" \
        | python3 -c "import sys,json;d=json.load(sys.stdin)['esearchresult']['idlist'];print(d[0] if d else 'NONE')")
  curl -gsS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id=${pmid}&linkname=pubmed_pmc"   # self-PMCID?
done

# 1. Nature OA probe — ONE curl per article decides OA vs paywalled by http_code
#    2.0 -> 200 PDF (18pp)  |  Cellpose3 -> 200 PDF (23pp)  |  1.0 -> 404 HTML = paywalled
# 2. Nature supplements — plain curl, no browser, even for the PAYWALLED article:
#    media.springernature.com/original/springer-static/esm/art%3A<doi%2Fid>/MediaObjects/41592_<yr>_<no>_MOESM<N>_ESM.<ext>
#    -> 1.0: 2 PDF + 2 GIF (160 frames each) | 2.0: 1 PDF + 1 MP4 (54MB) | Cellpose3: 3 PDF
# 3. Cellpose 1.0 has NO PMC and NO publisher OA -> bioRxiv preprint v2 is the only free copy
#    (Semantic Scholar openAccessPdf.status = GREEN confirmed it). Use the browser fetch drain.
# 4. Cellpose-SAM is bioRxiv-only (v1, no supplements) -> same browser fetch drain.
```

Result: 13 files / ~160 MB across 4 directories, every PDF page-count-verified via PyMuPDF and every GIF/MP4 structurally checked. Key lessons encoded: (1) **resolve the whole citation set first and probe OA status with one `curl` each** — that single probe decided 3 of the 4 tactics and avoided both a wasted browser session and a wasted 科研通 request; (2) **a Nature 404 means subscription, a 200-with-HTML means anti-bot** — do not confuse them; (3) **supplements are free even when the article is paywalled**, so Cellpose 1.0's supplements came from the publisher CDN while its main text had to come from the preprint; (4) the **preprint is an acceptable substitute** when publisher + PMC are both closed (source-priority rule 3) — name it `..._bioRxiv_preprint_main.pdf`, tell the user, and offer 科研通 only if they specifically need the typeset version; (5) bioRxiv needed the Cloudflare browser-fetch path twice (12.5 MB and 14.35 MB), both backgrounded.

## Example 8 (Nature OA end-to-end: main + supplements — the Paper2Agent case)

User gave a Nature URL (`https://www.nature.com/articles/s41586-026-11044-y` — Paper2Agent, Miao et al. 2026, DOI 10.1038/s41586-026-11044-y). The deliverable was 4 verified PDFs.

```bash
# 0. OA probe FIRST (decides the tactic, zero browser cost):
#    Unpaywall: is_oa=true, hybrid, CC BY-NC-ND, publisher-hosted → publisher direct link will work.
# 1. Main PDF: curl -L + UA + Referer from https://www.nature.com/articles/<id>.pdf
#    (equivalently: node scripts/batch_download.mjs --dois "10.1038/s41586-026-11044-y" --si --out <dir>
#     resolves the OA evidence and downloads in one command, status open_access_downloaded) — 14 MB, 18pp.
# 2. Enumerate supplements by scraping the article HTML page (plain curl + browser UA, no browser session):
#    grep hrefs for MOESM|MediaObjects|static-content|media.springernature + their anchor text
#    → 3 files at media.springernature.com/original/springer-static/esm/art%3A<doi>/MediaObjects/41586_2026_11044_MOESM{1,2,3}_ESM.pdf
#    named from anchor text: supplementary_information (61pp) / reporting_summary (3pp) / peer_review_file (96pp).
#    ⚠ The page's citation block also carried an UNRELATED journal's asset (41588_2025_2301_MOESM4_ESM.xlsx) —
#    filter by THIS article's journal id + article number (41586_2026_11044), not just any MOESM link.
# 3. curl -L each supplement (free CDN, no SSO) → verify: `file` + PyMuPDF page count + first-page text.
```

Result: `202609-Paper2Agent/` with 4 verified PDFs. The OA probe (Unpaywall/Semantic Scholar) picks the route before any browser is launched, and the supplementary block's anchor text names each MOESM for clear file naming.
