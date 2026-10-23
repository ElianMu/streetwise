'use strict';

const STREETWISE_API_BASE =
  location.hostname === 'elianmu.github.io'
    ? 'https://streetwise-api.onrender.com'
    : '';

function streetwiseFetch(url, options) {
  if (typeof url === 'string' && url.startsWith('/api/')) {
    return fetch(STREETWISE_API_BASE + url, options);
  }
  return fetch(url, options);
}
