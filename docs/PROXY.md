# Licensed PDFs through your institutional proxy

PaperFlow fetches PDFs open-access-first (arXiv, Unpaywall). For papers that
are only available through your university's subscription, it can fall back to
your institution's web proxy (EZproxy-style). This is **off by default**.

## How it works

1. You log in to your library proxy **in your normal browser** (Duo/2FA and
   all). PaperFlow never touches your password.
2. You export that browser session's cookies as a Netscape `cookies.txt`.
3. PaperFlow rewrites the paper's DOI URL through the proxy template, rides
   your session cookies, finds the `citation_pdf_url` on the publisher page,
   and downloads the PDF — slowly, and never more than `daily_limit` per day.

When the session expires, downloads stop working and `paperflow trace` shows
`proxy session expired` — just log in again in the browser and re-export.

## Setup

### 1. Find your proxy URL template

Open a licensed article via your library website and look at the address bar.
Typical patterns:

- Login-redirect style: `https://login.ezproxy.YOURUNI.edu/login?url=<target>`
  → template: `"https://login.ezproxy.YOURUNI.edu/login?url={url}"`
- Host-rewrite style: `https://www-nature-com.ezproxy.YOURUNI.edu/...`
  → use the login-redirect form of the same proxy if available (check your
  library's "off-campus access" page; nearly every EZproxy install supports
  `/login?url=`).

### 2. Export cookies

Log in through the proxy in Chrome/Firefox, then export cookies with any
"cookies.txt" browser extension (Netscape format). Save the file somewhere
private, e.g. `~/.paperflow/proxy_cookies.txt` (readable only by you:
`chmod 600`).

### 3. Configure

```toml
[proxy]
enabled = true
url_template = "https://login.ezproxy.YOURUNI.edu/login?url={url}"
cookie_file = "~/.paperflow/proxy_cookies.txt"
daily_limit = 10
request_delay_sec = 10
```

Run `paperflow doctor` to validate, then `paperflow run-once` — items whose
OA lookup failed will retry through the proxy.

## Please read: be a good citizen

Your library's license agreements prohibit systematic/bulk downloading, and
publishers automatically block campuses when they detect it. PaperFlow's
guardrails (sequential fetches, long delays, a small daily cap) are not
optional switches to max out — they are what keeps this feature safe to use.
If you need hundreds of PDFs at once, talk to your librarian instead.

## VPN alternative

If you use your university VPN, your IP is already on-campus and many
publishers serve PDFs directly. In that case you may not need the proxy at
all: leave `[proxy] enabled = false` and PaperFlow's normal downloader will
succeed for publishers that honor IP-based access (the OA chain tries the
publisher's `citation_pdf_url` only via proxy, so VPN users can also just use
Zotero's own "Find Available PDF" for stragglers).
