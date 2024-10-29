# Changelog

## Version 2.1.1 (2024-10-29)

- Fix name of `QUIZ_ARCHIVER_PREVENT_REDIRECT_TO_LOGIN` envirnoment variable in documentation
- Update Python dependencies
  - Fix CVE-2024-49766 in `werkzeug` package
  - Fix CVE-2024-49767 in `werkzeug` package


## Version 2.1.0 (2024-10-10)

- Add a demo mode to allow setting up a public quiz archive worker service for testing.
  - In demo mode, a watermark will be added to all generated PDFs, only a
    limited number of attempts will be exported per archive job, and only
    placeholder Moodle backups are included.
  - The demo mode is disabled by default and will only be used to provide a free
    and publicly available quiz archive worker service to the community. This
    allows testing the Moodle plugin without the need to set up a local quiz
    archive worker service right away. Productive instances of the quiz archive
    worker service will remain fully unaffected by this.
- Improve documentation and add reference to official documentation website
- Introduce explicit timeouts for Moodle API request
- Create unit tests for demo mode
- Update Python dependencies
 

## Version 2.0.0 (2024-08-21)

- Switch to semantic versioning (see README.md, Section: "Versioning and Compatibility")
- Add custom readiness probe for GeoGebra applets
- Improve page export readiness detection and add support for multiple readiness probes
- Ignore `.github` and `test` directories in Docker image build
- Dump full app configuration to log on startup if `LOG_LEVEL` is set to `DEBUG`

**Note:** Use of [quiz_archiver](https://github.com/ngandrass/moodle-quiz_archiver) `>= v2.0.0` is required.


## Version 1.6.0 (2024-07-29)

- Implement support for passing additional status values (statusextras) to Moodle
- Periodically report progress of running jobs back to Moodle
- Creation of new job status values:
  - `WAITING_FOR_BACKUP`: All attempt reports are generated and the archive worker service
    is waiting for the Moodle backup to be ready.
  - `FINALIZING`: The archive worker service is finalizing the archive creation process (checksums, compression, ...).
- Update Python dependencies


## Version 1.5.0 (2024-07-18)

- Optionally scale down large images within quiz reports to preserve space and keep PDF files compact
- Optionally compress images within quiz reports to preserve space and keep PDF files compact
- Rename `REPORT_PREVENT_REDIRECT_TO_LOGIN` to `PREVENT_REDIRECT_TO_LOGIN` to reflect the naming of the environment variable
- Reduce noise from 3rd party library loggers on log level `DEBUG`


## Version 1.4.0 (2024-07-08)

- Prevent belated redirects away from attempt report page (e.g. to login page)
- Increase defaults for job and attempt export timeouts
- Improve pytest unit tests
- Improve verbosity of error messages on job timeout due to missing "ready signals"
- Update Python dependencies
  - Address CVE-2024-39689 in `certifi` package


## Version 1.3.10 (2024-06-20)

- Optimize Docker image: Explicitly set run user group and perform additional apt cleanup
- Update Python dependencies
  - Fix CVE-2024-37891 in `urllib3` package


## Version 1.3.9 (2024-06-05)

- Create unit tests for archive creation, attempt rendering, backup storage, basic API logic, and more
- Separate Moodle API logic from `QuizArchiveJob` class
- Automatic execution of all unit tests on new commits and pull requests using GitHub actions
- Optimize Python dependencies. Remove development dependencies from default installation group.
- Update Python dependencies


## Version 1.3.8 (2024-05-29)

- Switch artifact archive format from `PAX_FORMAT` to `USTAR_FORMAT` to prevent
  problems when extracted using the ancient tar implementation within Moodle
- Update Docker container Python base to 3.12
- Update Python dependencies
  - Fix CVE-2024-35195 in `requests` package


## Version 1.3.7 (2024-05-07)

- Update Python dependencies
  - Fix CVE-2024-34069 in `werkzeug` package, a dependency of the `flask` package
   

## Version 1.3.6 (2024-04-23)

- Update Python dependencies
  - Fix CVE-2024-3651 in `idna` package, a dependency of the `requests` package


## Version 1.3.5 (2024-04-09)

- Add configuration option `QUIZ_ARCHIVER_WAIT_FOR_NAVIGATION_TIMEOUT_SEC` to allow for longer page navigation timeouts (#5 - Thanks to @krostas1983)
- Update Python dependencies


## Version 1.3.4 (2024-03-07)

- Add additional debug output (#4 - Thanks to @PM84)
- Update Python dependencies


## Version 1.3.3 (2024-02-20)

- Process quiz attempt metadata in batches to allow archiving of quizzes with a large number of attempts
- Improve error reporting on generic job failures
- Update Python dependencies


## Version 1.3.2 (2024-02-13)

- Refactor project structure to prepare for unit testing and code coverage
- Fix typos and improve logging (#2 #3 - Thanks to @aceArt-GmbH)
- Update Python dependencies


## Version 1.3.1 (2024-01-12)

- Add `QUIZ_ARCHIVER_CONTINUE_AFTER_READY_SIGNAL_TIMEOUT` option to allow jobs to continue even though a PDF generation experienced a timeout (*USE WITH CAUTION!*)
- Update Python dependencies


## Version 1.3.0 (2023-12-14)

- Base archive filename and attempt report names on API parameters
- Allow HTML reports to be excluded from created archives using an API parameter
- Fix render timeout on instances where `filter_mathjaxloader` is enabled but attempt does not contain any MathJax formulas
- Update Python dependencies


## Version 1.2.1 (2023-12-04)

- Fix Moodle 4.3 webservice JSON response parsing


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
