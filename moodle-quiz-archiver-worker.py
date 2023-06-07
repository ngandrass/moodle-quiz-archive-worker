#!/usr/bin/env python3
import asyncio
import io

from PIL import Image
from playwright.async_api import async_playwright, ViewportSize


async def foo():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport=ViewportSize(width=1920, height=1080))
        await page.goto("http://viamint.de")
        print(await page.title())
        screenshot = await page.screenshot(
            full_page=True,
            caret="hide",
            type="png"
        )
        await browser.close()

        img = Image.open(io.BytesIO(screenshot))
        img.convert(mode='RGB', palette=Image.ADAPTIVE).save(
            fp="out.pdf",
            format='PDF',
            dpi=(300, 300),
            quality=96
        )


def main():
    asyncio.run(foo())


if __name__ == "__main__":
    main()
