---
name: web-scraper
description: INVOKE when scrape_url (Firecrawl) is unavailable, rate-limited, returns an error, OR you need custom HTML parsing logic (specific tables, selectors, multi-page traversal). Uses requests + BeautifulSoup in the sandbox. Prefer scrape_url for plain markdown extraction. Triggers — "parse HTML", "extract from page", "scrape failed", "custom scraping", "follow links".
---

# Web Scraper

## Overview
Retrieve web content via HTTP inside the sandbox and parse HTML with BeautifulSoup. All network requests happen from inside the E2B sandbox.

## When to Use
- User asks to fetch or scrape a URL
- Extracting titles, links, tables, or article text from a web page
- Checking availability or content of a URL

## Instructions

### Pattern: fetch and parse
Write a script to `/home/user/workspace/scrape.py`:

```python
import requests
from bs4 import BeautifulSoup

url = "https://example.com"
resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "lxml")
print("Title:", soup.title.string if soup.title else "N/A")

# Extract all links
for a in soup.find_all("a", href=True)[:10]:
    print(a["href"], "-", a.get_text(strip=True))
```

Then run:
```
execute("python /home/user/workspace/scrape.py")
```

### Pattern: quick one-liner
```
execute("python -c \"import requests; r=requests.get('https://example.com'); print(r.status_code)\"")
```

### Tips
- Always set a `timeout` on requests to avoid hanging
- Use `lxml` parser (faster than html.parser and pre-installed)
- Respect robots.txt and terms of service
- For JSON APIs use `resp.json()` directly instead of BeautifulSoup
