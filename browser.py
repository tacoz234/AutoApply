import asyncio
import os
from typing import Optional, List, Any
from playwright.async_api import async_playwright

class BrowserController:
    def __init__(self, user_data_dir: str = ".automation_session"):
        # Use a hidden folder to avoid project root interference
        self.user_data_dir = os.path.abspath(user_data_dir)
        if not os.path.exists(self.user_data_dir):
            os.makedirs(self.user_data_dir)
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        # Force kill any hanging chrome processes that might be locking the folder
        try:
            os.system('taskkill /F /IM chrome.exe /T /FI "CPUTIME gt 00:00:00" >nul 2>&1')
        except:
            pass

        self.playwright = await async_playwright().start()
        
        # Try to launch. If locked, wait and try one more time.
        for attempt in range(2):
            try:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    headless=False,
                    slow_mo=500,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage"
                    ]
                )
                break
            except Exception as e:
                if attempt == 0:
                    print(f"Browser lock detected, retrying... ({e})")
                    await asyncio.sleep(2)
                else:
                    raise e
        
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

    async def navigate(self, url: str):
        await self.page.goto(url)

    async def find_form_fields(self):
        # Logic to find input fields and their labels
        # This is a placeholder for more complex field detection
        inputs = await self.page.query_selector_all("input, select, textarea")
        fields = []
        for input_el in inputs:
            # Try to find associated label
            id_val = await input_el.get_attribute("id")
            name_val = await input_el.get_attribute("name")
            placeholder_val = await input_el.get_attribute("placeholder")
            
            label_text = ""
            if id_val:
                label_el = await self.page.query_selector(f"label[for='{id_val}']")
                if label_el:
                    label_text = await label_el.inner_text()
            
            if not label_text and placeholder_val:
                label_text = placeholder_val
            elif not label_text and name_val:
                label_text = name_val
                
            if label_text:
                fields.append({"element": input_el, "label": label_text.strip(), "id": id_val, "name": name_val})
        return fields

    async def fill_field(self, element, value: str):
        await element.fill(value)

    async def get_linkedin_job_cards(self) -> list:
        # Navigate to LinkedIn Jobs
        url = "https://www.linkedin.com/jobs/collections/recommended/"
        print(f"Navigating to {url}...")
        await self.navigate(url)
        await asyncio.sleep(5)
        
        await self.screenshot("linkedin_debug.png")

        selectors = [".jobs-search-results-list__item", ".job-card-container", ".horizontal-job-card"]
        job_cards = []
        for selector in selectors:
            job_cards = await self.page.query_selector_all(selector)
            if job_cards:
                print(f"Found {len(job_cards)} jobs using selector: {selector}")
                break
        
        urls = []
        for card in job_cards[:10]:
            try:
                # Try to find the link to the job
                link_el = await card.query_selector("a.job-card-list__title, a.job-card-container__link")
                if not link_el:
                    link_el = await card.query_selector("a")
                
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        if href.startswith('/'): href = "https://www.linkedin.com" + href
                        # Clean up URL (remove tracking params)
                        clean_url = href.split('?')[0]
                        urls.append(clean_url)
            except:
                continue
                
        return urls

    async def scrape_job_card_details(self, job_url: str) -> Optional[dict]:
        try:
            print(f"Scraping details for: {job_url}")
            await self.navigate(job_url)
            await asyncio.sleep(3)
            
            details_pane = await self.page.query_selector(".jobs-search__job-details--container, .jobs-unified-top-card, .job-view-layout")
            if not details_pane:
                # Fallback to body if details pane selector changed
                details_pane = await self.page.query_selector("body")

            title_el = await details_pane.query_selector(".jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title, h1")
            
            company_selectors = [
                ".jobs-unified-top-card__company-name",
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__subtitle-grid-item a",
                ".jobs-unified-top-card__primary-description a"
            ]
            company_el = None
            for selector in company_selectors:
                company_el = await details_pane.query_selector(selector)
                if company_el: break
            
            desc_el = await details_pane.query_selector(".jobs-description-content__text, #job-details")
            
            title = await title_el.inner_text() if title_el else "Unknown Title"
            company = await company_el.inner_text() if company_el else "Unknown Company"
            description = await desc_el.inner_text() if desc_el else "No description"
            
            company = company.split('·')[0].strip()
            title = title.split('\n')[0].strip()
            
            if title == "Unknown Title" or "notification" in title.lower():
                fallback_title = await details_pane.query_selector("h2")
                if fallback_title:
                    title = await fallback_title.inner_text()

            return {
                "title": title.strip(),
                "company": company.strip(),
                "description": description.strip(),
                "url": self.page.url,
                "platform": "LinkedIn"
            }
        except Exception as e:
            print(f"Error scraping a job card: {e}")
            return None

    async def scrape_handshake_jobs(self) -> list:
        await self.navigate("https://app.joinhandshake.com/stu/postings")
        await asyncio.sleep(2)
        
        job_items = await self.page.query_selector_all("[data-hook='search-result-card']")
        urls = []
        for item in job_items[:10]:
            try:
                link = await item.query_selector("a")
                if link:
                    href = await link.get_attribute("href")
                    if href:
                        if href.startswith('/'): href = "https://app.joinhandshake.com" + href
                        urls.append(href)
            except:
                pass
        return urls

    async def scrape_handshake_job_details(self, job_url: str) -> Optional[dict]:
        await self.navigate(job_url)
        await asyncio.sleep(2)
        try:
            title = await self.page.inner_text("h1")
            # Handshake typically has a #job-description or similar
            desc_el = await self.page.query_selector(".job-description, [data-hook='job-description']")
            description = await desc_el.inner_text() if desc_el else "No description"
            
            return {
                "title": title.strip(),
                "description": description.strip(),
                "platform": "Handshake",
                "url": job_url
            }
        except:
            return None

    async def click_apply(self) -> str:
        # Look for any Apply button (Easy Apply or external Apply)
        buttons = await self.page.query_selector_all("button, a.jobs-apply-button")
        for btn in buttons:
            text = await btn.inner_text()
            if "Apply" in text:
                await btn.click()
                await asyncio.sleep(4) # More time for external redirects
                return "Easy Apply" if "Easy" in text else "External Apply"
        return "None"

    async def get_form_questions(self) -> list:
        # Check if we are on LinkedIn or an external site
        is_linkedin = "linkedin.com" in self.page.url
        
        container = None
        if is_linkedin:
            container = await self.page.query_selector(".jobs-easy-apply-modal, .artdeco-modal, .jobs-search-two-pane__details")
        
        # If external or no modal found, use the whole body
        if not container:
            container = await self.page.query_selector("body")

        questions = []
        # Search for common question patterns: labels, spans, or direct text near inputs
        labels = await container.query_selector_all("label, .fb-dash-form-element__label, p, span")
        
        # Limit the number of elements to scan for performance
        labels = labels[:100]
        
        blacklist = ["search", "filter", "sign in", "post a job", "policy", "terms", "cookies"]
        
        for label in labels:
            try:
                text = (await label.inner_text()).strip()
                if not text or len(text) < 3 or len(text) > 200: continue
                if any(word in text.lower() for word in blacklist): continue
                if text.endswith(":") or "?" in text or "name" in text.lower() or "email" in text.lower():
                    # Find associated input
                    parent = await label.query_selector("xpath=..")
                    # Try parent or parent of parent
                    input_el = await parent.query_selector("input, select, textarea")
                    if not input_el:
                        grandparent = await parent.query_selector("xpath=..")
                        input_el = await grandparent.query_selector("input, select, textarea")

                    if input_el:
                        q_id = await input_el.get_attribute("id") or await input_el.get_attribute("name") or text[:20]
                        # Don't add duplicate inputs
                        if any(q["id"] == q_id for q in questions): continue
                        
                        questions.append({
                            "id": q_id,
                            "text": text,
                            "element": input_el
                        })
            except:
                continue
        return questions

    async def submit_application_step(self):
        # Look for 'Next', 'Review', or 'Submit'
        buttons = await self.page.query_selector_all("button")
        for btn in buttons:
            text = await btn.inner_text()
            if any(w in text for w in ["Next", "Review", "Submit application"]):
                await btn.click()
                await asyncio.sleep(2)
                return text.strip()
        return None

    async def screenshot(self, path: str = "current_screen.png"):
        await self.page.screenshot(path=path)
        return path
