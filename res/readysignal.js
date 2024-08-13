/**
 * This script is injected into the page to check if the page is ready for export.
 */

/**
 * Interval in milliseconds the readiness probe checks are executed after the initial delay.
 * @type {number}
 */
const QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS = 250;

const SIGNAL_PAGE_READY_FOR_EXPORT = "x-quiz-archiver-page-ready-for-export";
const SIGNAL_GEOGEBRA_FOUND = "x-quiz-archiver-geogebra-found";
const SIGNAL_GEOGEBRA_NOT_FOUND = "x-quiz-archiver-geogebra-not-found";
const SIGNAL_GEOGEBRA_READY_FOR_EXPORT = "x-quiz-archiver-geogebra-ready-for-export";
const SIGNAL_MATHJAX_FOUND = "x-quiz-archiver-mathjax-found";
const SIGNAL_MATHJAX_NOT_FOUND = "x-quiz-archiver-mathjax-not-found";
const SIGNAL_MATHJAX_NO_FORMULAS_ON_PAGE = "x-quiz-archiver-mathjax-no-formulas-on-page";
const SIGNAL_MATHJAX_READY_FOR_EXPORT = "x-quiz-archiver-mathjax-ready-for-export";

/**
 * Global object to store readiness signals for different components.
 *
 * @type {{readySignals: {geogebra: null, mathjax: null}}}
 */
window.MoodleQuizArchiver = {
    initialized: false,
    readySignals: {
        mathjax: null,
        geogebra: null
    }
};

/**
 * Detects and prepares readiness signals for all tracked components.
 * This function must be called prior to checkReadiness().
 */
function detectAndPrepareReadinessComponents() {
    // MathJax
    if (typeof window.MathJax !== 'undefined') {
        window.MoodleQuizArchiver.readySignals.mathjax = false;
        console.log(SIGNAL_MATHJAX_FOUND);

        if (document.getElementsByClassName('filter_mathjaxloader_equation').length === 0) {
            window.MoodleQuizArchiver.readySignals.mathjax = true;
            console.log(SIGNAL_MATHJAX_NO_FORMULAS_ON_PAGE);
            console.log(SIGNAL_MATHJAX_READY_FOR_EXPORT);
        } else {
            window.MathJax.Hub.Queue(function () {
                window.MoodleQuizArchiver.readySignals.mathjax = true;
                console.log(SIGNAL_MATHJAX_READY_FOR_EXPORT);
            });
            window.MathJax.Hub.processSectionDelay = 0;
        }
    } else {
        console.log(SIGNAL_MATHJAX_NOT_FOUND);
    }

    // GeoGebra
    if (typeof window.GGBApplet !== 'undefined') {
        window.MoodleQuizArchiver.readySignals.geogebra = false;
        console.log(SIGNAL_GEOGEBRA_FOUND);

        detectGeogebraFinishedRendering();
    } else {
        console.log(SIGNAL_GEOGEBRA_NOT_FOUND);
    }

    window.MoodleQuizArchiver.initialized = true;
}

/**
 * Detects when GeoGebra applets have finished rendering. This function calls
 * itself periodically until all applets are rendered.
 *
 * Results are stored inside window.MoodleQuizArchiver.readySignals.geogebra.
 */
function detectGeogebraFinishedRendering() {
    // Detect GeoGebraFrames
    let ggbFrames = document.getElementsByClassName('GeoGebraFrame');
    let numLoadingFrames = 0;

    // Count the number of loading images in each GeoGebra frame
    ggbFrames.forEach(ggbFrame => {
        numLoadingFrames += ggbFrame.querySelectorAll("img.gwt-Image").length;
    })

    // Declare GeoGebra to be ready for export if all GeoGebraFrames appear loaded
    if (ggbFrames.length > 0 && numLoadingFrames === 0) {
        window.MoodleQuizArchiver.readySignals.geogebra = true;
        console.log(SIGNAL_GEOGEBRA_READY_FOR_EXPORT);
    } else {
        setTimeout(detectGeogebraFinishedRendering, QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS);
    }
}

/**
 * Checks if all components are ready for export. If not, this function will
 * call itself periodically until all components are ready.
 */
function checkReadiness() {
    if (!window.MoodleQuizArchiver.initialized) {
        console.error("Failed to check component export readiness before initialization.");
        setTimeout(checkReadiness, QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS);
        return;
    }

    for (const [component, ready] of Object.entries(window.MoodleQuizArchiver.readySignals)) {
        if (ready === null) {
            continue;
        }
        if (ready !== true) {
            setTimeout(checkReadiness, QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS);
            return;
        }
    }

    console.log(SIGNAL_PAGE_READY_FOR_EXPORT);
}

// Ignite the readiness detection process.
setTimeout(function() {
    detectAndPrepareReadinessComponents();
    checkReadiness();
}, 1000);
