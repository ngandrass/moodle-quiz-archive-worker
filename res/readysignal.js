/*
 * Moodle Quiz Archive Worker
 * Copyright (C) 2024 Niels Gandraß <niels@gandrass.de>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/**
 * This script is injected into each page to check if the page is ready for export.
 */

/**
 * Interval in milliseconds the readiness probe checks are executed after the initial delay.
 * @type {number}
 */
const QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS = 250;

/**
 * Number of milliseconds to wait after the last mutation of a GeoGebra applet before
 * considering it stable and ready for export.
 * @type {number}
 */
const QUIZ_ARCHIVER_GEOGEBRA_MUTATION_STABLE_PERIOD_MS = 2000;

const SIGNAL_PAGE_READY_FOR_EXPORT = "x-quiz-archiver-page-ready-for-export";
const SIGNAL_GEOGEBRA_FOUND = "x-quiz-archiver-geogebra-found";
const SIGNAL_GEOGEBRA_NOT_FOUND = "x-quiz-archiver-geogebra-not-found";
const SIGNAL_GEOGEBRA_MUTATED = "x-quiz-archiver-geogebra-mutated";
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
    initialized: false,         // True if the readiness detection process has been initialized
    readySignals: {
        mathjax: null,          // True if MathJax is ready for export, null if MathJax is not found
        geogebra: null          // True if GeoGebra is ready for export, null if GeoGebra is not found
    },
    states: {                   // Optional stateful data for different components
        geogebra: {
            last_mutation: null // Timestamp of the last mutation of a GeoGebra applet
        }
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

        // Check if MathJax is not just loaded but the page also has formulas on it
        if (document.getElementsByClassName('filter_mathjaxloader_equation').length === 0) {
            window.MoodleQuizArchiver.readySignals.mathjax = true;
            console.log(SIGNAL_MATHJAX_NO_FORMULAS_ON_PAGE);
            console.log(SIGNAL_MATHJAX_READY_FOR_EXPORT);
        } else {
            // Formulas found. Wait for MathJax to process them.
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
        window.MoodleQuizArchiver.states.geogebra.last_mutation = new Date(9999, 1, 1);  // Far future
        console.log(SIGNAL_GEOGEBRA_FOUND);

        // Attach mutation observer to GeoGebra frames once available
        attachGeogebraMutationObserver();
    } else {
        console.log(SIGNAL_GEOGEBRA_NOT_FOUND);
    }

    window.MoodleQuizArchiver.initialized = true;
}

/**
 * Waits for GeoGebra to be initialized to the point where it rendered its final
 * applet frames and attach mutation observers to them.
 *
 * This also ignites the readiness detection process for GeoGebra.
 */
function attachGeogebraMutationObserver() {
    // Check if GeoGebra is initialized to the point where it created its target applet frames
    try {
        if (typeof window.GGBApplet().getAppletObject === 'function') {
            if (typeof window.GGBApplet().getAppletObject().getFrame === 'function') {
                if (window.GGBApplet().getAppletObject().getFrame().classList.contains('jsloaded')) {
                    // Attach mutation listener to GeoGebra frames
                    var mutationObserver = new (window.MutationObserver || window.WebKitMutationObserver)(() => {
                        window.MoodleQuizArchiver.states.geogebra.last_mutation = new Date();
                        console.log(SIGNAL_GEOGEBRA_MUTATED);
                    });

                    document.getElementsByClassName('GeoGebraFrame').forEach(ggbFrame => {
                        mutationObserver.observe(ggbFrame, {childList: true, subtree: true});
                        console.log("Attached mutation observer to GeoGebra frame.");
                    });
                    window.MoodleQuizArchiver.states.geogebra.last_mutation = new Date();

                    // Ignite periodic readiness check
                    setTimeout(detectGeogebraFinishedRendering, QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS);
                    return;
                } else {
                    console.log("GeoGebra frame not fully initialized yet. Waiting ...");
                }
            } else {
                console.log("GeoGebra frame object not yet ready. Waiting ...");
            }
        } else {
            console.log("GeoGebra applet object not yet ready. Waiting ...");
        }
    } catch (e) {
        if (e instanceof TypeError) {
            console.log("GeoGebra applet/frames not yet ready. Waiting ...");
        } else {
            console.log("Failed to attach mutation observer to GeoGebra frames: " + e);
        }
    }

    // If we got here, GeoGebra is not ready yet. Retry in a bit.
    setTimeout(attachGeogebraMutationObserver, QUIZ_ARCHIVER_READINESS_PROBE_INTERVAL_MS);
}

/**
 * Detects when GeoGebra instances have finished rendering. This function calls
 * itself periodically until all applets are rendered.
 *
 * Results are stored inside window.MoodleQuizArchiver.readySignals.geogebra.
 */
function detectGeogebraFinishedRendering() {
    // Declare GeoGebra to be ready for export if no mutation has occurred since the given time
    const lastMutationMs = window.MoodleQuizArchiver.states.geogebra.last_mutation.getTime();
    if (new Date().getTime() >= lastMutationMs + QUIZ_ARCHIVER_GEOGEBRA_MUTATION_STABLE_PERIOD_MS) {
        window.MoodleQuizArchiver.readySignals.geogebra = true;
        console.log(SIGNAL_GEOGEBRA_READY_FOR_EXPORT);
    } else {
        window.MoodleQuizArchiver.readySignals.geogebra = false;
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
