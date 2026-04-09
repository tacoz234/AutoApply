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
        
        print(f"[BROWSER] Launching context with user_data_dir: {self.user_data_dir}")
        for attempt in range(3):
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
                print("[BROWSER] Launch successful.")
                break
            except Exception as e:
                print(f"[BROWSER] Launch attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(3)
                else:
                    raise e
        
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        print(f"[BROWSER] Page initialized. Current URL: {self.page.url}")

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
        try:
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
            for card in job_cards[:15]: # Increased to 15
                try:
                    # Try to find the link to the job
                    link_el = await card.query_selector("a.job-card-list__title, a.job-card-container__link, .job-card-list__title")
                    if not link_el:
                        link_el = await card.query_selector("a")
                    
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href:
                            if href.startswith('/'): href = "https://www.linkedin.com" + href
                            clean_url = href.split('?')[0]
                            urls.append(clean_url)
                except:
                    continue
                    
            return urls
        except Exception as e:
            print(f"Error during job discovery: {e}")
            return []

    async def scrape_job_card_details(self, job_url: str) -> Optional[dict]:
        try:
            print(f"Scraping details for: {job_url}")
            await self.navigate(job_url)
            await asyncio.sleep(3)
            
            details_pane = await self.page.query_selector(".jobs-search__job-details--container, .jobs-unified-top-card, .job-view-layout")
            if not details_pane:
                # Fallback to body if details pane selector changed
                details_pane = await self.page.query_selector("body")

            # Aggressive title extraction for direct job views
            title_selectors = [
                "h1.t-24", "h1", # Primary headings on direct view
                ".jobs-unified-top-card__job-title", 
                ".job-details-jobs-unified-top-card__job-title",
                ".top-card-layout__title",
                "h2.t-24"
            ]
            
            title = "Unknown Title"
            for selector in title_selectors:
                elements = await details_pane.query_selector_all(selector)
                for el in elements:
                    text = (await el.inner_text()).strip().split('\n')[0]
                    if text and len(text) > 3 and "notification" not in text.lower() and "message" not in text.lower():
                        title = text
                        break
                if title != "Unknown Title": break

            company_selectors = [
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__subtitle-grid-item a",
                ".top-card-layout__link",
                "a[href*='/company/']",
                ".topcard__org-name-link"
            ]
            company_el = None
            for selector in company_selectors:
                company_el = await details_pane.query_selector(selector)
                if company_el: break
            
            desc_el = await details_pane.query_selector(".jobs-description-content__text, #job-details, .description__text, .show-more-less-html__markup")
            
            company = await company_el.inner_text() if company_el else "Unknown Company"
            description = await desc_el.inner_text() if desc_el else "No description"
            
            # Clean up company (often has multiple lines or ' · ')
            company = company.split('\n')[0].split('·')[0].strip()
            
            # Cleaning up title and company
            if title == "Unknown Title":
                # FINAL FALLBACK: Use browser tab title which usually has the job title
                page_title = await self.page.title()
                if " | " in page_title:
                    title = page_title.split(" | ")[0].strip()
                elif " - " in page_title:
                    title = page_title.split(" - ")[0].strip()
                else:
                    title = page_title.strip()

            # Double check title isn't still junk
            if "notifications" in title.lower() or not title or title == "LinkedIn":
                fallback = await details_pane.query_selector(".jobs-unified-top-card__job-title")
                if fallback: title = await fallback.inner_text()

            return {
                "title": title.strip(),
                "company": company.strip(),
                "description": description.strip(),
                "url": job_url,
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
        print(f"[DEBUG] Scanning for Apply buttons on {self.page.url}...")
        selectors = [
            "button.jobs-apply-button", 
            "button.jobs-s-apply",
            "a.jobs-apply-button",
            "button:has-text('Easy Apply')", 
            "button:has-text('Apply')",
            ".jobs-search-two-pane__details button"
        ]
        
        btn_to_click = None
        for selector in selectors:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    btn_to_click = btn
                    print(f"[DEBUG] Found Apply button via selector '{selector}'")
                    break
            except:
                continue
                
        if not btn_to_click:
            buttons = await self.page.query_selector_all("button, a")
            for btn in buttons:
                try:
                    text = (await btn.inner_text()).strip()
                    if "Apply" in text and await btn.is_visible():
                        print(f"[DEBUG] Found generic Apply button with text: '{text}'")
                        btn_to_click = btn
                        break
                except:
                    continue

        if btn_to_click:
            text = await btn_to_click.inner_text()
            is_external = "Easy" not in text
            
            if is_external:
                # Handle potential new tab
                print("[BROWSER] Clicking External Apply. Waiting for new tab...")
                try:
                    async with self.context.expect_page(timeout=10000) as new_page_info:
                        await btn_to_click.click()
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state()
                    self.main_page = self.page # Save main page
                    self.page = new_page       # Switch to external
                    print(f"[BROWSER] Switched to new tab: {self.page.url}")
                except Exception as e:
                    print(f"[BROWSER] No new tab opened or timeout. Staying on same page. {e}")
                    await btn_to_click.click()
                    await asyncio.sleep(4)
                return "External Apply"
            else:
                await btn_to_click.click()
                await asyncio.sleep(4)
                return "Easy Apply"
                
        print("[DEBUG] No Apply buttons found.")
        return "None"

    async def finish_application(self):
        """Clean up by closing external tabs and returning to main page."""
        if hasattr(self, 'main_page') and self.main_page:
            print("[BROWSER] Application cycle finished. Closing external tab...")
            if self.page != self.main_page:
                await self.page.close()
            self.page = self.main_page
            await self.page.bring_to_front()
        else:
            print("[BROWSER] Application finished. No extra tabs to close.")

    async def submit_with_llm(self, llm, prompt: str):
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()

    async def get_form_questions(self) -> list:
        print(f"[DEBUG] Analyzing page for form questions: {self.page.url}")
        is_linkedin = "linkedin.com" in self.page.url
        
        container = None
        if is_linkedin:
            container = await self.page.query_selector(".jobs-easy-apply-modal, .artdeco-modal, .jobs-search-two-pane__details")
        
        if not container:
            container = await self.page.query_selector("body")

        questions = []
        labels = await container.query_selector_all("label, .fb-dash-form-element__label, p, span, h3")
        print(f"[DEBUG] Scanned {len(labels)} potential question labels.")
        
        blacklist = ["search", "filter", "sign in", "post a job", "policy", "terms", "cookies", "learn more"]
        
        for label in labels:
            try:
                text = (await label.inner_text()).strip()
                if not text or len(text) < 3 or len(text) > 250: continue
                if any(word in text.lower() for word in blacklist): continue
                
                # Broad markers for questions
                if text.endswith(":") or "?" in text or any(w in text.lower() for w in ["name", "email", "phone", "resume", "experience", "education"]):
                    # Find associated input
                    parent = await label.query_selector("xpath=..")
                    input_el = await parent.query_selector("input, select, textarea")
                    if not input_el:
                        grandparent = await parent.query_selector("xpath=..")
                        input_el = await grandparent.query_selector("input, select, textarea")

                    if input_el:
                        q_id = await input_el.get_attribute("id") or await input_el.get_attribute("name") or text[:20]
                        q_type = await input_el.get_attribute("type") or input_el.tag_name()
                        
                        if any(q["id"] == q_id for q in questions): continue
                        
                        print(f"[DEBUG] Question detected: '{text}' (ID: {q_id}, Type: {q_type})")
                        questions.append({
                            "id": q_id, 
                            "text": text, 
                            "element": input_el,
                            "type": q_type.lower()
                        })
            except:
                continue
        
        print(f"[DEBUG] Total questions found: {len(questions)}")
        return questions

    async def submit_application_step(self, llm=None):
        print(f"[DEBUG] Searching for navigation/submit buttons on {self.page.url}")
        # Search for buttons, links, search-inputs, or anything with a pointer cursor
        selectors = [
            "button", "input[type='submit']", "a.btn", "[role='button']",
            ".btn", ".button", "a[href*='apply']", "div.clickable", "li.clickable",
            "div:has-text('Apply')", "div:has-text('Upload')", "a:has-text('Resume')"
        ]
        
        buttons = []
        for selector in selectors:
            try:
                els = await self.page.query_selector_all(selector)
                buttons.extend(els)
            except: continue
            
        found_buttons = []
        seen_texts = set()
        
        for btn in buttons:
            try:
                if not await btn.is_visible(): continue
                text = (await btn.inner_text()).strip()
                if not text: text = await btn.get_attribute("value") or ""
                if not text: text = await btn.get_attribute("aria-label") or ""
                if not text: text = await btn.get_attribute("title") or ""
                
                # Check for image alt text inside button
                if not text:
                    img = await btn.query_selector("img")
                    if img: text = await img.get_attribute("alt") or ""

                if text and text not in seen_texts:
                    seen_texts.add(text)
                    found_buttons.append({"element": btn, "text": text})
                    targets = [
                        "Next", "Review", "Submit", "Continue", "Apply", 
                        "Save and continue", "Agree", "Apply Now", "Start Application",
                        "Accept", "Proceed", "Register", "Apply for this Job",
                        "Apply With LinkedIn", "Upload a resume", "Upload your resume",
                        "Use my last application", "Apply Now"
                    ]
                    if any(w.lower() in text.lower() for w in targets):
                        print(f"[DEBUG] Found navigation button: '{text}' - Clicking...")
                        await btn.click()
                        await asyncio.sleep(4)
                        return text.strip()
            except:
                continue

        # LLM Text Fallback first (faster)
        if llm and found_buttons:
            print(f"[DEBUG] Rule-based search failed. Asking LLM for assistance with {len(found_buttons)} buttons...")
            btn_texts = [b["text"] for b in found_buttons[:30]]
            prompt = f"""I am an automated job application agent. I am on a career site and I need to find the button that moves the application to the next step, registers me, or submits it.
            Based on these button labels, which one is most likely the 'Continue', 'Apply Now', or 'Submit' button?
            Respond with ONLY the exact text of the best button. If none fit, respond with 'NONE'.
            Buttons: {', '.join(btn_texts)}"""
            
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            choice = response.content.strip()
            print(f"[DEBUG] LLM chose: '{choice}'")
            
            if choice != "NONE":
                for b in found_buttons:
                    if b["text"] == choice or choice in b["text"]:
                        print(f"[DEBUG] Clicking LLM-chosen button: '{b['text']}'")
                        await b["element"].click()
                        await asyncio.sleep(4)
                        return b["text"]

        # Vision Fallback if LLM provided and text failed
        if llm:
            print("[DEBUG] Rule and Text analysis failed. Attempting Multimodal Vision...")
            screenshot_path = "vision_temp.png"
            await self.screenshot(screenshot_path)
            
            import base64
            with open(screenshot_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
                
            prompt = """Look at this screenshot of a job application page. 
            I am looking for a button to 'Apply', 'Continue', 'Next', or 'Submit'. 
            Does such a button exist? Explain exactly what it says and where it is.
            If you find it, start your response with 'TARGET_TEXT: [exact button text]'."""
            
            from langchain_core.messages import HumanMessage
            
            # Message with image context
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_data}"}}
                ]
            )
            
            try:
                response = await llm.ainvoke([msg])
                vision_res = response.content
                print(f"[DEBUG] Vision Analysis: {vision_res}")
                
                if "TARGET_TEXT:" in vision_res:
                    target = vision_res.split("TARGET_TEXT:")[1].strip().split('\n')[0].strip()
                    print(f"[DEBUG] Vision found target: '{target}'")
                    # Try to find an element matching this visual text
                    for b in found_buttons:
                        if target.lower() in b["text"].lower() or b["text"].lower() in target.lower():
                            print(f"[DEBUG] Clicking vision-matched button: '{b['text']}'")
                            await b["element"].click()
                            await asyncio.sleep(4)
                            return b["text"]
            except Exception as e:
                print(f"[DEBUG] Vision check failed: {e}")
                    
        print("[DEBUG] No navigation buttons found.")
        return None

    async def screenshot(self, path: str = "current_screen.png"):
        await self.page.screenshot(path=path)
        return path
