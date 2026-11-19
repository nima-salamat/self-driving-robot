/* Shared authentication response handler for every Stream page. */
(function () {
  "use strict";
  if (window.__streamAuthFetchInstalled) return;
  window.__streamAuthFetchInstalled = true;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    return nativeFetch(input, init).then(function (response) {
      if (response.status === 401 && window.location.pathname !== "/login") {
        window.location.replace("/login");
      }
      return response;
    });
  };
})();
