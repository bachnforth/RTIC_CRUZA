'use strict';
// Paces the dashboard's status checks. Timers in a worker keep running on time
// when the dashboard tab is in the background; the page's own timers do not.
setInterval(() => postMessage('tick'), 1500);
