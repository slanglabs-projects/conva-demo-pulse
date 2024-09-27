from bs4 import BeautifulSoup
from cacheout import lru_memoize
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
import uuid

import asyncio


@lru_memoize()
async def scrape(url: str, contents: dict):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            user_agent = UserAgent().chrome
            context = await browser.new_context(
                user_agent=user_agent,
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            # await page.wait_for_selector("body")
            await page.wait_for_load_state("networkidle")

            previous_height = await page.evaluate("document.body.scrollHeight")
            while True:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                await page.wait_for_timeout(1000)  # Wait to load the page

                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height
            content = await page.content()
            await context.close()

            with open("/tmp/{}.html".format(uuid.uuid4().hex), "w") as f:
                f.write("{}\n\n".format(url))
                f.write(content)

            soup = BeautifulSoup(content, "html.parser")
            for data in soup(["header", "footer", "nav", "script", "style"]):
                data.decompose()
            content = soup.get_text()
            # content = soup.prettify()
            contents[url] = content
    except (Exception,):
        contents[url] = ""


async def scrape_multiple(urls):
    contents = {}
    tasks = [scrape(url, contents) for url in urls]
    await asyncio.gather(*tasks)
    return contents
