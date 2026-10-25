"""ICAI launch-batch monitor.

Drives the real page in a headless browser (Playwright), because the site is an
ASP.NET form whose dropdowns reload the page. Reads the batch table for each
configured course, compares with the last run (state.json) and sends a Telegram
message when a batch is new, removed, or its seats / details changed.

Environment variables
  TELEGRAM_BOT_TOKEN   required (GitHub secret)
  TELEGRAM_CHAT_ID     required (GitHub secret)
  ICAI_REGION          default "Central"
  ICAI_POU             default "Indore"
  ICAI_COURSES         default: the three below, separated by "|"
  DEBUG_DIR            default "debug" (screenshot + html saved here on failure)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://www.icaionlineregistration.org/launchbatchdetail.aspx"
STATE_FILE = Path("state.json")
REGION = os.environ.get("ICAI_REGION", "Central")
POU = os.environ.get("ICAI_POU", "Indore")
DEFAULT_COURSES = [
    "AICITSS - Advanced Information Technology",
    "Advanced (ICITSS) MCS Course",
    "Advanced (ICITSS) MCS Course - Weekend",
]
COURSES = [c.strip() for c in os.environ.get("ICAI_COURSES", "|".join(DEFAULT_COURSES)).split("|") if c.strip()]
DEBUG_DIR = Path(os.environ.get("DEBUG_DIR", "debug"))


# ----------------------------------------------------------------- telegram
def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    # Telegram limit is 4096 chars per message
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or [text]
    for chunk in chunks:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()


# ------------------------------------------------------------------ diffing
def row_key_and_seats(headers, cells):
    """Return (key, seats_text). Seats columns are excluded from the key so a
    seat change is reported as a change, not as a removed + new batch."""
    low = [h.lower() for h in headers]
    seat_idx = [i for i, h in enumerate(low) if "seat" in h or "vacan" in h or "available" in h]
    batch_idx = [i for i, h in enumerate(low) if "batch" in h and i not in seat_idx]
    if batch_idx:
        key_idx = batch_idx
    else:
        key_idx = [i for i in range(len(cells)) if i not in seat_idx]
    key = " | ".join(cells[i] for i in key_idx if i < len(cells))
    seats = " | ".join(f"{headers[i]}: {cells[i]}" for i in seat_idx if i < len(cells))
    return key, seats


def table_to_batches(headers, rows):
    out = {}
    for cells in rows:
        key, seats = row_key_and_seats(headers, cells)
        if not key.strip():
            continue
        detail = " | ".join(f"{h}: {c}" for h, c in zip(headers, cells))
        out[key] = {"seats": seats, "detail": detail}
    return out


def diff(old: dict, new: dict):
    """old/new: {course: {key: {seats, detail}}}. Returns list of message lines."""
    msgs = []
    for course in sorted(set(old) | set(new)):
        o, n = old.get(course, {}), new.get(course, {})
        for k in n.keys() - o.keys():
            msgs.append(f"🆕 NEW batch [{course}]\n{n[k]['detail']}")
        for k in o.keys() - n.keys():
            msgs.append(f"❌ REMOVED batch [{course}]\n{o[k]['detail']}")
        for k in n.keys() & o.keys():
            if n[k]["seats"] != o[k]["seats"]:
                msgs.append(f"💺 SEATS changed [{course}] {k}\nwas: {o[k]['seats'] or '-'}\nnow: {n[k]['seats'] or '-'}")
            elif n[k]["detail"] != o[k]["detail"]:
                msgs.append(f"✏️ DETAILS changed [{course}] {k}\nwas: {o[k]['detail']}\nnow: {n[k]['detail']}")
    return msgs


# ----------------------------------------------------------------- scraping
def find_select(page, wanted_text: str):
    """Locate the <select> that contains an option whose text contains wanted_text."""
    wanted = wanted_text.lower()
    sels = page.locator("select")
    for i in range(sels.count()):
        opts = [t.strip() for t in sels.nth(i).locator("option").all_inner_texts()]
        if any(wanted in o.lower() for o in opts):
            return sels.nth(i), opts
    return None, []


def choose(page, wanted_text: str, exact_first=True):
    sel, opts = find_select(page, wanted_text)
    if sel is None:
        raise RuntimeError(f"No dropdown has an option like '{wanted_text}'")
    label = None
    if exact_first:
        label = next((o for o in opts if o.lower() == wanted_text.lower()), None)
    label = label or next(o for o in opts if wanted_text.lower() in o.lower())
    sel.select_option(label=label)
    # ASP.NET AutoPostBack reloads the page / partial panel
    page.wait_for_load_state("networkidle", timeout=45000)
    page.wait_for_timeout(1500)


def click_submit_if_any(page):
    for name in ["Submit", "Search", "Show", "Get", "View", "Go", "Find"]:
        btn = page.locator(f"input[type=submit][value*='{name}' i], input[type=button][value*='{name}' i], button:has-text('{name}')")
        if btn.count():
            btn.first.click()
            page.wait_for_load_state("networkidle", timeout=45000)
            page.wait_for_timeout(1500)
            return True
    return False


def read_batch_table(page):
    """Return (headers, rows) of the largest data table on the page, or ([], [])
    if the page shows no batch table (e.g. no batches launched)."""
    best = ([], [])
    tables = page.locator("table")
    for t in range(tables.count()):
        tbl = tables.nth(t)
        # skip layout tables that contain other tables
        if tbl.locator("table").count():
            continue
        trs = tbl.locator("tr")
        data = []
        for r in range(trs.count()):
            cells = [c.strip() for c in trs.nth(r).locator("th,td").all_inner_texts()]
            cells = [" ".join(c.split()) for c in cells]
            if any(cells):
                data.append(cells)
        if len(data) >= 2 and len(data[0]) >= 3 and len(data) - 1 > len(best[1]):
            best = (data[0], data[1:])
    return best


def scrape():
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        page = ctx.new_page()
        try:
            for course in COURSES:
                page.goto(URL, wait_until="networkidle", timeout=60000)
                choose(page, REGION)
                choose(page, POU)          # POU list fills after Region is chosen
                choose(page, course)
                click_submit_if_any(page)  # harmless if the form shows results on change
                headers, rows = read_batch_table(page)
                results[course] = table_to_batches(headers, rows) if rows else {}
                print(f"{course}: {len(results[course])} batch(es)")
        except Exception:
            DEBUG_DIR.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
            (DEBUG_DIR / "page.html").write_text(page.content(), encoding="utf-8")
            raise
        finally:
            browser.close()
    return results


# --------------------------------------------------------------------- main
def main():
    new = scrape()
    first_run = not STATE_FILE.exists() or STATE_FILE.read_text().strip() in ("", "{}")
    old = {} if first_run else json.loads(STATE_FILE.read_text())

    if first_run:
        lines = [f"✅ ICAI monitor started ({REGION} / {POU})"]
        for course, batches in new.items():
            lines.append(f"\n{course}: {len(batches)} batch(es)")
            lines += [f"  • {b['detail']}" for b in batches.values()]
        send_telegram("\n".join(lines))
    else:
        msgs = diff(old, new)
        if msgs:
            send_telegram(f"ICAI update ({REGION} / {POU})\n\n" + "\n\n".join(msgs))
            print(f"Sent {len(msgs)} change(s)")
        else:
            print("No changes")

    STATE_FILE.write_text(json.dumps(new, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # job fails -> GitHub emails you; state is untouched
        print(f"ERROR: {e}", file=sys.stderr)
        raise
