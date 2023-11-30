# Changelog

## Version 1.2.0 (2023-11-30)

- Download quiz attempt artifacts, if present (e.g., essay file submissions)
- Validate checksums of downloaded Moodle files
- Load attempt HTML via mock request to prevent CORS errors and dynamic JS loading problems
- Catch API version mismatches early to allow proper reporting via Moodle UI
- Refactor backup download code into generic Moodle file download function
- Log Playwright browser console output on debug level
- Update Python dependencies


## Version 1.1.3 (2023-11-21)

- Group attempt data in subdirectories for each attempt
- Update Python dependencies


## Version 1.1.2 (2023-11-08)

- Update Python dependencies


## Version 1.1.1 (2023-08-23)

- Improve performance: Reuse Playwright `BrowserContext` between attempt renderings.
- Fix environment variable override of config. Cast environmental config overrides to the correct types
- Add debug output to request JSON validation
 

## Version 1.1.0 (2023-08-22)

- Ensure full MathJax rendering before the PDF export is generated
- Switch from Playwright screenshot to PDF procedure to native PDF print engine
- Allow configuration of report page margins via `QUIZ_ARCHIVER_REPORT_PAGE_MARGIN` env variable
- Remove img2pdf dependency
- Add additional debug output to Moodle backup download stage
- Update Python dependencies


## Version 1.0.7 (2023-08-16)

- Optimize Docker build
- Provide pre-built Docker images
- Improve setup instructions / documentation
- Update Python dependencies


## Version 1.0.6 (2023-08-02)

- Replace Pillow (PIL) PDF renderer with img2pdf to prevent JPEG conversion of attempt PNGs
- Update Python dependencies


## Version 1.0.5 (2023-07-31)

- Allow to fetch quiz attempt metadata and write it to a CSV file inside the archive
- Add support for conditional report section inclusion
- Add debug output to report HTML tree generation


## Version 1.0.4 (2023-07-27)

- Check Content-Type of Moodle backup file request
- Add debug output to Moodle backup filesize check
