# Moodle Archiving Worker
# Copyright (C) 2026 Niels Gandraß <niels@gandrass.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Activity-agnostic Playwright rendering and PDF post-processing primitives.

These functions are shared by all activity-specific archive jobs (e.g. quiz
attempts, assignment submissions) that need to render an HTML document to a
PDF file and optionally post-process it.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Callable, ContextManager

from PIL.Image import Resampling
from playwright.async_api import Browser, BrowserContext, Page, Route, ViewportSize, Playwright
from pypdf import PdfWriter

from config import Config
from archiveworker.type import PaperFormat, ReportSignal


DEMOMODE_JAVASCRIPT = open(os.path.join(str(os.path.dirname(__file__)), '../res/demomode.js')).read()
READYSIGNAL_JAVASCRIPT = open(os.path.join(str(os.path.dirname(__file__)), '../res/readysignal.js')).read()

SRGB_ICC_COLOR_PROFILE_PATH = Path(os.path.join(Path(os.path.dirname(__file__)).parent, "res", "sRGB_v4_ICC_preference_displayclass.icc"))


async def launch_browser_and_context(playwright: Playwright) -> tuple[Browser, BrowserContext]:
    """
    Launches a new Chromium browser and browser context, configured according
    to the current application settings (proxy, viewport, TLS validation,
    navigation timeout).

    :param playwright: Active Playwright driver instance
    :return: Tuple of (Browser, BrowserContext)
    """
    browser = await playwright.chromium.launch(
        args=['--disable-web-security'],  # Pass --disable-web-security to ignore CORS errors
        proxy={
            'server': Config.PROXY_SERVER_URL,
            'username': Config.PROXY_USERNAME,
            'password': Config.PROXY_PASSWORD,
            'bypass': Config.PROXY_BYPASS_DOMAINS,
        } if Config.PROXY_SERVER_URL else None,
    )
    context = await browser.new_context(
        viewport=ViewportSize(
            width=int(Config.REPORT_BASE_VIEWPORT_WIDTH),
            height=int(Config.REPORT_BASE_VIEWPORT_WIDTH / (16/9))
        ),
        ignore_https_errors=Config.SKIP_HTTPS_CERT_VALIDATION
    )
    context.set_default_navigation_timeout(Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC * 1000)

    return browser, context


async def render_html_to_pdf(
        bctx: BrowserContext,
        base_url: str,
        html: str,
        paper_format: PaperFormat,
        output_path: Path,
        logger: logging.Logger,
) -> None:
    """
    Renders the given HTML document to a PDF file using a Playwright browser
    context.

    :param bctx: Playwright BrowserContext to render the page in
    :param base_url: Base URL of the Moodle instance the HTML originates from.
    Used to construct a same-origin mock URL to serve the HTML from (avoids
    CORS / requireJS issues) and to scope the login-redirect workarounds.
    :param html: HTML document to render
    :param paper_format: Paper format to use for the PDF (e.g. 'A4')
    :param output_path: Path to write the resulting PDF file to
    :param logger: Logger to use for diagnostic output
    :return: None
    """
    await bctx.clear_cookies()
    page = await bctx.new_page()
    if Config.LOG_LEVEL == logging.DEBUG:
        page.on('console', lambda msg: logger.debug(f'Playwright console message: {msg.text}'))
        page.on('pageerror', lambda msg: logger.debug(f'Playwright page error: {msg}'))
        page.on('crash', lambda msg: logger.debug(f'Playwright page crash: {msg}'))
        page.on('requestfailed', lambda req: logger.debug(f'Playwright request failed: {req.url}'))
        page.on('domcontentloaded', lambda _: logger.debug('Playwright DOM content loaded'))
        # page.on('requestfinished', lambda req: logger.debug(f'Playwright request finished: {req.url}'))

    async def __mock_responder(route: Route):
        """
        Create mock responder to serve the HTML document.

        This is done to avoid CORS errors when loading the HTML and to
        prevent errors when dynamically loading JavaScript modules via
        RequireJS. Using the base URL of the corresponding Moodle LMS seems to
        work absolutely fine for now.

        :param route: Playwright route to respond to
        :return: None
        """
        await route.fulfill(body=html, content_type='text/html')

    async def __login_redirection_interceptor(route: Route):
        """
        Aborts navigations to login page

        :param route: Playwright route to intercept
        :return: None
        """
        logger.warning(f'Prevented belated redirection to: {route.request.url}')
        await route.abort('blockedbyclient')

    async def __javascript_redirection_patcher(route: Route):
        """
        Removes JavaScript code that redirects to the login page.

        This can happen if AJAX requests fail with permission errors due to missing sessions.
        We alter the JavaScript code because we cannot prevent the redirection event once it is fired.
        Intercepting the request after it fired may lead to situations where the HTML DOM of the page
        is already destructed, leading to empty pages and thus to blank PDF files.

        :param route: Playwright route to intercept
        :return: None
        """
        try:
            # Perform request
            response = await route.fetch(timeout=Config.REQUEST_TIMEOUT_SEC if not Config.UNIT_TESTS_RUNNING else 0.1)

            # Remove code that redirects to the login page
            body_original = await response.text()
            body_patched = re.sub(
                r'window\.location\s*=\s*URL\.relativeUrl\(\"/login/index.php\"\)',
                'console.warn("Prevented redirect to /login/index.php")',
                body_original
            )

            if body_patched != body_original:
                logger.debug(f'Disabled javascript login page redirection code in {route.request.url}')

            # Return the patched response
            await route.fulfill(response=response, body=body_patched)
        except Exception as e:
            if Config.UNIT_TESTS_RUNNING:
                logger.info(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')
                await route.abort()
            else:
                logger.error(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')
                raise RuntimeError(f'Failed to fetch and patch javascript resource {route.request.url}: {e}')

    try:
        # Flush and re-register custom route handlers as required
        await bctx.unroute_all()
        await bctx.route(f"{base_url}/mock/attempt", __mock_responder)
        if Config.PREVENT_REDIRECT_TO_LOGIN:
            await bctx.route('**/login/*.php', __login_redirection_interceptor)
            await bctx.route('**/*.js', __javascript_redirection_patcher)

        # Load HTML
        await page.goto(f"{base_url}/mock/attempt")
    except Exception:
        logger.error(f'Page did not load after {Config.REPORT_WAIT_FOR_NAVIGATION_TIMEOUT_SEC} seconds. Aborting ...')
        raise

    # If in demo mode, inject watermark JS
    if Config.DEMO_MODE:
        await page.evaluate(DEMOMODE_JAVASCRIPT)

    # Wait for the page to report that is fully rendered, if enabled
    if Config.REPORT_WAIT_FOR_READY_SIGNAL:
        try:
            await _wait_for_page_ready_signal(page, logger)
        except Exception:
            if Config.REPORT_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT:
                logger.warning(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Continuing ...')
            else:
                logger.error(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds. Aborting ...')
                raise RuntimeError(f'Ready signal not received after {Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC} seconds.')
    else:
        logger.debug('Not waiting for ready signal. Export immediately ...')

    # Save page as PDF
    await page.pdf(
        path=output_path,
        format=paper_format,
        print_background=True,
        display_header_footer=False,
        margin={
            'top': Config.REPORT_PAGE_MARGIN,
            'right': Config.REPORT_PAGE_MARGIN,
            'bottom': Config.REPORT_PAGE_MARGIN,
            'left': Config.REPORT_PAGE_MARGIN,
        }
    )

    await page.close()


async def _wait_for_page_ready_signal(page: Page, logger: logging.Logger) -> None:
    """
    Waits for the page to report that it is ready for export

    :param page: Page object
    :param logger: Logger to use for diagnostic output
    :return: None
    """
    async with page.expect_console_message(
            lambda msg: msg.text == ReportSignal.READY_FOR_EXPORT.value,
            timeout=Config.REPORT_WAIT_FOR_READY_SIGNAL_TIMEOUT_SEC * 1000
    ) as cmsg_handler:
        logger.debug('Injecting JS to wait for page rendering ...')
        await page.evaluate(READYSIGNAL_JAVASCRIPT)
        logger.debug(f'Waiting for ready signal: {ReportSignal.READY_FOR_EXPORT}')

        cmsg = await cmsg_handler.value
        logger.debug(f'Received signal: {cmsg}')


async def compress_pdf(
        file: Path,
        pdf_compression_level: int,
        image_maxwidth: int,
        image_maxheight: int,
        image_quality: int,
        logger: logging.Logger,
) -> None:
    """
    Compresses a PDF file by resizing/compressing images and compressing content streams.
    Replaces the given file.

    :param file: Path to the PDF file to compress
    :param pdf_compression_level: Compression level for content streams (0-9)
    :param image_maxwidth: Maximum width of images in pixels
    :param image_maxheight: Maximum height of images in pixels
    :param image_quality: JPEG2000 compression quality (0-100)
    :param logger: Logger to use for diagnostic output
    :return: None
    """

    # Dev notes:
    # (1) Page content stream compression did not much in our tests, but it's basically free, so we keep it without
    # making it configurable to the user for now.
    # (2) Re-writing the whole file after compression, as suggested by pypdf, does change nothing for us, since it
    # is already re-written during the image processing step.
    # (3) By far the greatest size reduction is achieved scaling down huge images, if people upload high-res images.

    old_filesize = os.path.getsize(file)
    logger.debug(f"Compressing PDF file: {file} (size: {old_filesize} bytes)")
    writer = PdfWriter(clone_from=file)

    img_idx = 0
    for page in writer.pages:
        for img in page.images:
            img_idx += 1

            # Do not touch images with transparency data (mode=RGBA).
            # See: https://github.com/python-pillow/Pillow/issues/8074
            if img.image.has_transparency_data:
                logger.debug(f"  -> Skipping image {img_idx} on page {page.page_number} because it contains transparency data")
                continue

            # Scale down large images
            if img.image.width > image_maxwidth or img.image.height > image_maxheight:
                logger.debug(f"  -> Resizing image {img_idx} on page {page.page_number} from {img.image.width}x{img.image.height} px to fit into {image_maxwidth}x{image_maxheight} px")
                img.image.thumbnail(size=(image_maxwidth, image_maxheight), resample=Resampling.LANCZOS)

            # Compress images
            logger.debug(f"  -> Replacing image {img_idx} on page {page.page_number} with quality {image_quality}")
            img.replace(
                img.image,
                quality=image_quality,
                optimize=True,
                progressive=False
            )

        logger.debug(f" -> Compressing PDF content streams on page {page.page_number} with level {pdf_compression_level}")
        page.compress_content_streams(level=pdf_compression_level)

    with open(file, "wb") as f:
        writer.write(f)
        new_filesize = os.path.getsize(file)
        size_percent = round((new_filesize / old_filesize) * 100, 2)
        logger.debug(f"  -> Saved compressed PDF as: {file} (size: {os.path.getsize(file)} bytes, {size_percent}% of original)")


async def convert_pdf_to_pdfa(
        input_pdf_file: Path,
        tmp_dir_factory: Callable[[], ContextManager],
        logger: logging.Logger,
) -> None:
    """
    Converts given PDF file to the PDF/A-3b format by invoking a ghostscript subprocess.
    Replaces the given file.

    :param input_pdf_file: Path to the PDF file to convert to PDF/A
    :param tmp_dir_factory: Callable returning a context manager that yields a
    temporary working directory (e.g. `workspace.tmp_dir`)
    :param logger: Logger to use for diagnostic output

    :return: None

    :raises RuntimeError: If the conversion process failes with status code != 0
    :raises TimeoutError: If the conversion process takes longer then allowed
    """

    def __generate_ghostscript_command_arguments(
            working_dir: Path,
            input_postscript_file: Path,
            input_pdf_file: Path,
            output_pdf_file: Path
    ) -> list[str]:
        """
        Generates a list of ghostscript command arguments for PDF/A conversion.

        :param working_dir: Path to the conversion working directory
        :param input_postscript_file: Path of the conversion postscript file
        :param input_pdf_file: Path to the input PDF that should be converted
        :param output_pdf_file: Path to store the converted output PDF to

        :return: List of command arguments as strings
        """
        return [
            # Allow required file reads and writes
            f'--permit-file-read="{working_dir.absolute()}"',
            f'--permit-file-read="{input_postscript_file.absolute()}"',
            f'--permit-file-read="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',
            f'--permit-file-write="{working_dir.absolute()}"',

            # Output to file instead of rendering
            '-sDEVICE=pdfwrite',

            # Configure PDF/A color conversion
             '-sColorConversionStrategy=RGB',
             '-dProcessColorModel=/DeviceRGB',
            f'-sOutputICCProfile="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',
            f'-sDefaultRGBProfile="{SRGB_ICC_COLOR_PROFILE_PATH.absolute()}"',

            # Set output file and PDF/A version
            '-dCompatibilityLevel=1.7',
            '-dPDFA=3',
            '-dPDFACompatibilityPolicy=0',

            # Configure compression and embedding
            '-dEmbedAllFonts=true',
            '-dSubsetFonts=true',
            '-dCompressFonts=true',
            '-dNOSUBSTFONTS=false',

            # Prevent halting on user input
            '-dNOPAUSE',
            '-dBATCH',
            '-dNOOUTERSAVE',

            # File I/O
            f'-sOutputFile="{output_pdf_file.absolute()}"',
            f'"{input_postscript_file.absolute()}"',
            f'"{input_pdf_file.absolute()}"'
        ]

    def __generate_postscript_file(
            working_dir: Path,
            color_profile_path: Path,
            title:str|None=None,
    ) -> Path:
        """
        Generates postscript file contents required for PDF/A conversion and writes them to disk.
        (Based on https://github.com/ArtifexSoftware/ghostpdl/blob/19820f3ae748450f5943fdd679d97b3ecd6d12c5/lib/PDFA_def.ps)

        :param working_dir: Path to the conversion working directory
        :param color_profile_path:  Path of the icc color profile
        :param title: Title metadata of the converted PDF file (optional)

        :return: Path to the generated postscript file within the working directory
        """

        pdf_metadata = {
            'MoodleQuizArchiveWorkerVersion': Config.VERSION,
        }
        if title is not None and title != "":
            pdf_metadata["Title"] = title

        file_content = "\n\r".join([
            '%!PS',

            # PDF file metadata
            f'[ {"\n\r  ".join(["/"+k+" ("+v+")" for k,v in pdf_metadata.items()])}',
             '  /DOCINFO pdfmark',
             '',

            # Configure icc profile
             '[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark',
             '[{icc_PDFA} << /N 3 >> /PUT pdfmark', # NOTE: N is always 3 because of sRGB profile
            f'[{{icc_PDFA}} ({color_profile_path.absolute()}) (r) file /PUT pdfmark',
             '',

            # Configure output intent
            '[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark',
            '[{OutputIntent_PDFA} <<',
            '  /Type /OutputIntent',
            '  /S /GTS_PDFA1',
            '  /DestOutputProfile {icc_PDFA}',
            '  /OutputConditionIdentifier (sRGB)',
            '>> /PUT pdfmark',
            '[{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark',
            ''
            # EOF
        ])

        file_path = Path(os.path.join(working_dir, "PDFA_def.ps"))

        with open(file=file_path, mode="w") as f:
            f.write(file_content)
            f.flush()
            f.close()

        return file_path

    logger.debug(f"Converting '{input_pdf_file.absolute()}' to PDF/A")

    with tmp_dir_factory() as tmpdir:
        tmpdir = Path(tmpdir)
        logger.debug(f"Using temporary directory for PDF/A conversion: '{tmpdir.absolute()}'.")

        # NOTE: Ghostscript can not convert the PDF file in place, therefore
        #       we write to a designated output file and replace the input
        #       file with it when the subprocess finished successfully.
        output_pdf_file = Path(os.path.join(tmpdir, "output.pdf"))

        postscript_file = __generate_postscript_file(
            working_dir=tmpdir,
            color_profile_path=SRGB_ICC_COLOR_PROFILE_PATH
        )

        command = " ".join([
            Config.PDFA_CONVERSION_GHOSTSCRIPT_BINARY_PATH,
            *__generate_ghostscript_command_arguments(
                working_dir=tmpdir,
                input_postscript_file=postscript_file,
                input_pdf_file=input_pdf_file,
                output_pdf_file=output_pdf_file
            )
        ])

        logger.debug(f'Creating ghostscript subprocess as `{command}`.')
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                Config.PDFA_CONVERSION_TIMEOUT_SEC,
            )
            logger.debug(f"ghostscript subprocess stdout was: `{stdout.decode().strip()}`")
            logger.debug(f"ghostscript subprocess stderr was: `{stderr.decode().strip()}`")

            if proc.returncode != 0:
                raise RuntimeError("ghostscript subprocess failed with status code != 0")

            os.replace(output_pdf_file.absolute(), input_pdf_file.absolute())
        except TimeoutError as te:
            logger.error("PDF/A conversion timed out")
            raise te
        except Exception as e:
            logger.error(f"PDF/A conversion failed: '{e}'")
            raise e
