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
 * This script is injected if the archive worker is in demo mode. It inserts a
 * "Demo Mode" watermark into the PDF pages.
 */

// "DEMO MODE" watermark
const wrapper = document.createElement('div');
const watermark = document.createElement('div');

watermark.innerHTML = 'DEMO  MODE';
Object.assign(watermark.style, {
    width: 'calc(1.414*100vw)',
    transformOrigin: 'center',
    transform: 'rotate(45deg)',
    fontSize: '186px',
    color: 'rgba(0, 0, 0, 0.3)',
    fontWeight: 'bold',
    pointerEvents: 'none'
});

Object.assign(wrapper.style, {
    position: 'fixed',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    zIndex: '9999',
    textAlign: 'center'
});

wrapper.appendChild(watermark);
document.body.appendChild(wrapper);

// Demo mode information
const info = document.createElement('div');

info.innerHTML = 'This PDF was generated in <strong>demo mode</strong>. The watermark will not be present when using a ' +
                 'productive quiz archive worker service.<br>For more information visit: ' +
                 '<a href="https://quizarchiver.gandrass.de">https://quizarchiver.gandrass.de</a>';

Object.assign(info.style, {
    position: 'fixed',
    bottom: '0',
    left: '0',
    zIndex: '9999',
    width: '100%',
    padding: '10px',
    backgroundColor: 'rgba(220, 220, 220, 0.9)',
});

document.body.appendChild(info);