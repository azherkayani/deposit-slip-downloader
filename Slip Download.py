import os
import time
import traceback
import pandas as pd
from playwright.sync_api import sync_playwright

# ---------- SETTINGS ----------
TEST_COUNT = None          # test with 3 slips first; set to None to run all
DL = os.path.join(os.path.expanduser("~"), "Downloads")   # Chrome's download folder
# ------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "downloads")
os.makedirs(OUT, exist_ok=True)


def load_slips():
    import re
    xlsx = os.path.join(BASE, "slips.xlsx")
    print("Reading:", xlsx)
    df = pd.read_excel(xlsx, dtype=str)          # first row = headers
    print("Columns found:", list(df.columns))
    print(df.head(3).to_string())

    col = None
    # 1) a column whose header looks like slip number
    for c in df.columns:
        name = str(c).strip().lower().replace(" ", "").replace("_", "").replace("#", "")
        if name in ("slipno", "slip", "depositslip", "depositslipno"):
            col = c
            break
    # 2) otherwise the column with the most values like 809-0511225
    if col is None:
        pattern = re.compile(r"^\s*\d+-\d+\s*$")
        scores = {c: df[c].dropna().astype(str).map(lambda v: bool(pattern.match(v))).sum()
                  for c in df.columns}
        col = max(scores, key=scores.get)
        if scores[col] == 0:
            raise Exception("Could not find a slip number column. See the columns printed above.")

    print("Using column:", col)
    slips = df[col].dropna().astype(str).str.strip().tolist()
    return [s for s in slips if s and s.lower() != "nan"]


def new_in_downloads(before):
    now = set(os.listdir(DL))
    return [f for f in now - before if not f.endswith((".crdownload", ".tmp"))]


def download_one(page, slip):
    before = set(os.listdir(DL))

    page.fill("#ContentPlaceHolder1_txtDepositSlipNo", slip)
    page.locator(
        "input[value='Search'], button:text-is('Search'), a:text-is('Search')"
    ).last.click()
    page.wait_for_load_state("networkidle")

    link = page.locator("a", has_text="Challan").first
    link.wait_for(timeout=10000)

    # Method 1: catch the download on the same page
    try:
        with page.expect_download(timeout=15000) as dl:
            link.click()
        d = dl.value
        d.save_as(os.path.join(OUT, f"{slip}_{d.suggested_filename}"))
        return True
    except Exception:
        pass

    # Method 2: find the new file in the Downloads folder
    for _ in range(30):
        found = new_in_downloads(before)
        if found:
            time.sleep(1)
            name = found[0]
            os.replace(os.path.join(DL, name), os.path.join(OUT, f"{slip}_{name}"))
            return True
        time.sleep(0.5)
    return False


def main():
    slips = load_slips()
    if TEST_COUNT:
        slips = slips[:TEST_COUNT]
    print(f"Loaded {len(slips)} slips")
    print("Watching Downloads folder:", DL)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = next(pg for pg in context.pages if "MIS_FinanceSearch" in pg.url)
        print("Found search page")

        failed = []
        for slip in slips:
            try:
                if download_one(page, slip):
                    print(f"Done {slip}")
                else:
                    raise Exception("download not detected")
            except Exception as e:
                print(f"Failed {slip}: {e}")
                failed.append(slip)

        pd.Series(failed, name="slip_no").to_csv(
            os.path.join(BASE, "failed.csv"), index=False)
        print(f"Finished. {len(failed)} failed.")


try:
    main()
except Exception:
    traceback.print_exc()

input("\nPress Enter to close...")
