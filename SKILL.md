---
name: download-paper
description: Download academic paper PDFs and their supplementary files from the web to a local directory. Use whenever the user asks to download a paper, fetch a paper's PDF, get a paper and its supplements/attachments, or save a literature file locally — even if they only give a DOI, PMID, or paper title. Handles paywalled-publisher sites (including via the 科研通/ablesci.com 文献互助 fallback), PMC (which uses a Proof-of-Work anti-bot challenge that blocks curl), and open repositories. Triggers on phrases like "下载文献", "下载这篇论文及其附件", "download this paper and supplements", "把这篇文献下到 X 目录", "用 opencli 登录科研通求助下载".
---

# Download Paper

Download academic paper PDFs and supplementary materials from the web to a local directory. Built to defeat the anti-bot mechanisms (PMC Proof-of-Work, publisher referer checks) that make plain `curl` fail.

## Core principle

Most paper PDFs can NOT be downloaded with a bare `curl`/`wget`. Four classes of blocker/source exist, and each needs a different approach:

| Blocker / Source | Symptom | Solution |
|---------|---------|----------|
| **PMC Proof-of-Work** | curl returns ~1.8KB HTML saying "Preparing to download..." with a `POW_CHALLENGE` JS var | Must run JS in a real browser to solve the PoW and get a cookie, then reuse that cookie |
| **Publisher referer/paywall** (Elsevier, Cell, Nature, Wiley) | curl returns 403 or a redirect to a login page | Send a browser User-Agent + the article page as Referer; cookie may still be needed. If no open-access copy on PMC, fall back to **科研通 文献互助** (see step 3b) |
| **Subscription-only, no OA copy** (Wiley/Elsevier with paywall + no PMC) | Publisher returns 403/HTML AND no PMCID exists | **科研通 (ablesci.com) 文献互助 fallback** — a Chinese research-mutual-aid platform where logged-in users upload paywalled PDFs for each other (~1–10 min turnaround). See step 3b. |
| **Open repo** (arXiv, bioRxiv, GitHub) | Usually direct-downloadable | Plain `curl -L -o file.pdf <url>` works |

Always diagnose which class you're hitting before choosing a tactic. The fastest diagnostic: try `curl -sS -o /tmp/probe <url>` and check `file /tmp/probe` + the first bytes. If it's HTML mentioning "download" or a challenge, it's class 1 or 2 — switch to the browser-cookie method.

## Workflow

### 1. Identify the paper and its files

Resolve the user's input to concrete download URLs:

- **DOI** → `https://doi.org/<doi>` resolves to the publisher page; look for the PDF link there.
- **PMID** → fetch `https://pubmed.ncbi.nlm.nih.gov/<pmid>/` to get the PMCID (free full text) and publisher link.
- **Title/author** → use `opencli pubmed search "<query>"` or `opencli openalex search "<query>"` to find the PMID/DOI. These adapters return metadata only (title, authors, DOI, PMID), not the PDF.
- **arXiv ID** → `opencli arxiv paper <id>` for metadata; the PDF is at `https://arxiv.org/pdf/<id>.pdf`.

**Supplementary materials** are almost never on PubMed. Find them on:
- **PMC** article page: links like `/articles/instance/<PMCID>/bin/<filename>` (supplements) and `/articles/<PMCID>/pdf/<filename>` (main PDF). Scrape them with `opencli browser <session> eval "Array.from(document.querySelectorAll('a')).filter(...).map(...)"` (see step 4).
- **Publisher page**: usually behind a "Supplementary Material" / "Download Supplemental PDF" link.

List every file you plan to download before starting, so the user can confirm.

### 2. Decide the download tactic by source

| Source | Tactic |
|--------|--------|
| arXiv / bioRxiv / GitHub | Direct `curl -L -o` — no auth needed |
| PMC (pmc.ncbi.nlm.nih.gov) | **Browser-cookie method** (PoW) — see step 3 |
| Elsevier/Cell/Nature/Lancet publisher | **Try publisher direct link first; on 403/HTML, fall back to PMC** (see "Publisher → PMC fallback" below). Do NOT keep retrying a publisher URL that returns 403 — it has extra anti-bot beyond cookies. |
| Wiley / subscription-only with **no PMC copy** | **科研通 (ablesci.com) 文献互助 fallback** — see step 3b. Use when the Publisher → PMC fallback finds no PMCID (paper is genuinely paywalled with no OA copy). |
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
#    automatically and Chrome saves the file to ~/Downloads/. Do NOT use curl here.
opencli browser "$SESSION" open "https://www.ablesci.com/assist/download?id=<FILE_ID>"
#   Wait for the .crdownload file in ~/Downloads/ to finish and rename (~10–60s for 20–30MB).
#   Poll: ls -lat ~/Downloads/ | head -5   until a .pdf appears and no *.crdownload remains.
sleep 30 && ls -lat ~/Downloads/ | head -5
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
- **The 49KB HTML file in Downloads** → if you accidentally `curl`'d the download URL, you got the login-page HTML. Delete it and re-download via browser navigation.
- **Layui popups need two clicks** → the adopt flow sometimes chains a second confirm popup. After the first `.layui-layer-btn0` click, re-check for another popup and click `.layui-layer-btn0` again.

**Rate-limit / etiquette**: ablesci costs the user points per request (default ~10). Don't spam requests. Post one paper, wait for fulfillment, adopt, then post the next. Turnaround is usually fast (1–10 min during Chinese daytime hours).

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

### 5. Name the files sensibly

Use a consistent, grep-friendly naming scheme so the `read-local-pdf` skill and the user can identify them later:

```
<FirstAuthor>_<Year>_<ShortTitle>_<Journal>_main.pdf
<FirstAuthor>_<Year>_<ShortTitle>_<Journal>_supplementary_<type>.pdf
```

Example: `Wolock_2019_Scrublet_CellSystems_main.pdf`, `Wolock_2019_Scrublet_CellSystems_supplementary_figures.pdf`

Put all files for one paper in a single directory named after the paper's key concept (e.g. `Scrublet/`), under the user's current working directory unless they specified otherwise.

### 6. Verify every downloaded file

The helper script already validates `%PDF` magic bytes after each download (exit code 2 = PoW challenge page received, file auto-deleted). But still do a full integrity check — a partial PDF is a real risk with large supplements.

```bash
# Use the read-local-pdf skill's extractor, or directly:
python3 -c "import fitz; d=fitz.open('<file>'); print('pages:', d.page_count)"
file <file>   # must say "PDF document", not "HTML document" or "empty"
```

Exit codes from `download_pdf.py`:
| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success, validated as PDF | Proceed |
| 1 | Network failure after retries | Re-run the command (partial file auto-resumes) |
| 2 | **PoW challenge page received** (cookie expired) | Re-trigger PoW (step 3b), re-harvest cookies, retry the failed file |

A valid result: `PDF document, version X.Y` + a nonzero page count. If `file` says "HTML document" or page count is 0, the download was blocked/incomplete — re-harvest the cookie (it may have expired) and retry. Delete corrupt partial files before retrying so resume doesn't append to garbage.

Report to the user: final directory path, each file's size, page count, and the verified title from metadata.

## Anti-patterns

- **Don't try bare `curl` on PMC and give up when it "fails".** The 1.8KB HTML response is the PoW challenge, not a real failure — it's a signal to use the browser-cookie method.
- **Don't harvest cookies from the article page and assume PoW is done.** The `cloudpmc-viewer-pow` cookie only appears AFTER navigating to a PDF direct-link URL (step 3b). Cookies from the article page alone lack the PoW token and will return challenge pages. Always sanity-check: `echo "$COOKIES" | grep cloudpmc-viewer-pow`.
- **Don't keep retrying a publisher URL that returns 403.** Cell/Elsevier `showPdf`/`pdfExtended` links have anti-bot beyond cookies — no amount of cookie/header tweaking fixes 403. Switch to the PMC fallback (step 2) instead.
- **Don't write a one-off inline Python download script.** Use `scripts/download_pdf.py`; it has the retry/resume/chunk logic AND the `%PDF` magic-bytes validation that catches PoW challenge pages.
- **Don't download only the main PDF and call it done** when the user asked for "附件/supplements too". Supplements live at different URLs (the `/bin/` path on PMC, the `/cms/.../attachment/` path on Cell) — enumerate them in step 4 (from both sources!) and download each.
- **Don't claim success without verifying.** A 0-page or HTML-typed file is a failed download, not a success. The helper script now rejects non-PDF content (exit 2), but still run the step-6 page-count check and report real numbers.
- **Don't ignore the helper script's exit code 2.** Exit 2 specifically means "got PoW challenge, cookie expired" — re-trigger PoW (step 3b) and retry, rather than treating it as a generic network failure.
- **Don't try to `curl` a 科研通/ablesci download URL.** The `/assist/download?id=...` endpoint requires the httpOnly session cookie, which `document.cookie` cannot read and curl therefore cannot send. You'll get a 49KB HTML login page instead of the PDF. Always download by **navigating the browser** (`opencli browser <session> open <download-url>`) so Chrome sends the httpOnly cookie itself; the PDF lands in `~/Downloads/`.
- **Don't post a second ablesci request before adopting the first.** The site blocks new posts while a fulfilled request is unprocessed, with a misleading "处理提示" page that looks like the form failed to load. Adopt the prior file (step 3b.h–i), then re-open `/assist/create`.
- **Don't try to register or log in to ablesci yourself.** The session must already be authenticated with the user's own account. If `document.querySelector('.user-info,...')` shows no username, ask the user to log in first.

## Open-access shortcuts

For sources with no anti-bot, skip the browser entirely:

```bash
# arXiv
curl -L -o "Author_Year_Title_arxiv.pdf" "https://arxiv.org/pdf/<id>.pdf"

# bioRxiv
curl -L -o "Author_Year_Title_biorxiv.pdf" "https://www.biorxiv.org/content/<doi>v<ver>.full.pdf"

# GitHub-hosted PDF
curl -L -o "file.pdf" "https://github.com/<repo>/raw/<branch>/<path>.pdf"
```

If these return a valid PDF (check with `file`), done. If they return HTML, fall back to the browser-cookie method.

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