import asyncio
from playwright.async_api import async_playwright
import csv
from datetime import datetime
import os
from supabase import create_client, Client
import urllib.parse
import random

# ---------------------------
# Supabase
# ---------------------------
SUPABASE_URL = "https://xkofhaaanyzsdtlnjvwt.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhrb2ZoYWFhbnl6c2R0bG5qdnd0Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MzM2ODI0MywiZXhwIjoyMDc4OTQ0MjQzfQ.kkPYFGBdv9oZUtRE-Fg1I7_lMRf4LDqHhaSEMoz6MN4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------
# Extract SID from URL
# ---------------------------
def extract_sid(job_url):
    # Last part after hyphen is always the job ID
    last_part = job_url.rstrip("/").split("-")[-1]

    # It must be digits (Naukri job IDs are 12 digits)
    if last_part.isdigit():
        return last_part
    return ""

# ---------------------------
# Minimal human-like sleep (1-2s)
# ---------------------------
async def human_sleep(a=0.5, b=1.5):
    await asyncio.sleep(random.uniform(a, b))

# ---------------------------
# Safe goto with small retry (non-invasive)
# ---------------------------
async def safe_goto(page, url, retries=2, timeout=60000):
    last_exc = None
    for attempt in range(retries):
        try:
            # Use the same behavior as your original script (wait until load)
            return await page.goto(url, timeout=timeout)
        except Exception as e:
            last_exc = e
            print(f"[goto retry {attempt+1}/{retries}] failed: {e}")
            await asyncio.sleep(random.uniform(1.0, 2.0))
    # final attempt without raising (let caller handle None)
    try:
        return await page.goto(url, timeout=timeout)
    except Exception as e:
        print(f"[goto final attempt] failed: {e}")
        return None

# ---------------------------
# Scrape one job page (unchanged logic, small goto retry + sleep)
# ---------------------------
async def scrape_job_page(page, job_url):
    await human_sleep()  # 1-2s before visiting job

    nav = await safe_goto(page, job_url)
    if nav is None:
        # still try a direct goto (best-effort, mirrors original behaviour)
        try:
            await page.goto(job_url)
        except Exception as e:
            print("Final navigation attempt failed for", job_url, "->", e)
            raise

    # keep your original wait and selectors
    await page.wait_for_selector("section.styles_job-desc-container__txpYf", timeout=60000)

    title_el = await page.query_selector("h1.styles_jd-header-title__rZwM1, div.styles_jd-header-title__rZwM1")
    title = await title_el.inner_text() if title_el else ""

    comp_el = await page.query_selector("div.styles_jd-header-comp-name__MvqAI > a")
    company = await comp_el.inner_text() if comp_el else ""

    info_labels = await page.query_selector_all("div.styles_details__Y424J")
    info_dict = {}
    for item in info_labels:
        label_el = await item.query_selector("label")
        span_el = await item.query_selector("span")
        if label_el and span_el:
            label = (await label_el.inner_text()).replace(":", "").strip()
            value = (await span_el.inner_text()).strip()
            info_dict[label] = value

    ug_el = await page.query_selector("div.styles_education__KXFkO div.styles_details__Y424J:nth-child(2) > span")
    pg_el = await page.query_selector("div.styles_education__KXFkO div.styles_details__Y424J:nth-child(3) > span")

    edu_ug = await ug_el.inner_text() if ug_el else ""
    edu_pg = await pg_el.inner_text() if pg_el else ""

    skill_els = await page.query_selector_all("div.styles_key-skill__GIPn_ a span")
    key_skills = [await sk.inner_text() for sk in skill_els]

    posted_el = await page.query_selector("div.styles_jhc__jd-stats__KrId0 span:has-text('Posted:') span")
    date_posted = await posted_el.inner_text() if posted_el else ""

    scraped_date = datetime.today().strftime("%Y-%m-%d")

    return {
        "title": title,
        "company": company,
        "role": info_dict.get("Role", ""),
        "industry": info_dict.get("Industry Type", ""),
        "department": info_dict.get("Department", ""),
        "employment_type": info_dict.get("Employment Type", ""),
        "role_category": info_dict.get("Role Category", ""),
        "education_ug": edu_ug,
        "education_pg": edu_pg,
        "key_skills": ", ".join(key_skills),
        "date_posted": date_posted,
        "scraped_date": scraped_date
    }

# ---------------------------
# MAIN SCRAPER (keeps your original structure)
# ---------------------------
async def scrape_naukri_jobs(pages=2, keyword="software-engineer"):

    # rotate user agents per run (minimal, non-invasive)
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ]
    ua = random.choice(user_agents)

    async with async_playwright() as p:
        # keep headless=False like your working version
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-http2",
                "--disable-features=NetworkService",
                "--disable-features=UseChromeCrosNetworking",
                "--disable-features=EnableLazyFrameLoading",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        # create a context with rotated UA (non-invasive)
        context = await browser.new_context(user_agent=ua)

        page_list = await context.new_page()   # <-- listing page
        page_job  = await context.new_page()   # <-- job page (separate)

        today_str = datetime.today().strftime("%Y-%m-%d")
        '''
        file_name = f"{today_str}_{keyword}.csv"

        if not os.path.exists(file_name):
            with open(file_name, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "id", "title", "company", "role", "industry", "department",
                    "employment_type", "role_category", "education_UG",
                    "education_PG", "key_skills", "date_posted", "scraped_date"
                ])
            print(f"Created new CSV: {file_name}")
        '''

        for page_num in range(1, pages + 1):

            url = f"https://www.naukri.com/{keyword}-jobs-{page_num}?jobAge=1"
            print("Opening:", url)

            # use safe_goto to reduce transient navigation failures
            nav_result = await safe_goto(page_list, url)
            if nav_result is None:
                # if navigation fails, mimic original behavior and continue
                print(f" Failed to load page {page_num}, continuing.")
                await human_sleep()
                continue

            # replace fixed sleep 0.5 with randomized 1-2s
            await human_sleep()

            try:
                await page_list.wait_for_selector("div.cust-job-tuple", timeout=60000)
            except Exception:
                print(f" No jobs on page {page_num}")
                continue

            # Extract all job links as TEXT ONLY
            job_links = []
            job_cards = await page_list.query_selector_all("div.cust-job-tuple")

            for job in job_cards:
                link_el = await job.query_selector("a.title")
                if not link_el:
                    continue
                href = await link_el.get_attribute("href")
                if href:
                    job_links.append(href)

            # NOW iterate over links safely (no stale DOM)
            for job_link in job_links:

                job_id = extract_sid(job_link)

                try:
                    data = await scrape_job_page(page_job, job_link)

                    supabase.table("job_scrapes").upsert({
                        "id": job_id,
                        "title": data["title"],
                        "company": data["company"],
                        "role": data["role"],
                        "industry": data["industry"],
                        "department": data["department"],
                        "employment_type": data["employment_type"],
                        "role_category": data["role_category"],
                        "education_ug": data["education_ug"],
                        "education_pg": data["education_pg"],
                        "key_skills": data["key_skills"],
                        "date_posted": data["date_posted"],
                        "scraped_date": data["scraped_date"],
                    }).execute()

                    print(f"Saved {job_id} -> {data['title']}")

                except Exception as e:
                    print("Error scraping job:", e)

                # replace fixed sleep 0.5 with randomized 1-2s
                await human_sleep()

        await browser.close()

        #print(f"\nScraping finished. Data saved to {file_name}.")

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    asyncio.run(scrape_naukri_jobs(pages=100, keyword="software-engineer"))
    asyncio.run(scrape_naukri_jobs(pages=50, keyword="data-analyst"))
