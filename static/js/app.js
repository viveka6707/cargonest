// Shared client-side helpers for CargoNest.
document.addEventListener('submit', function (event) {
  const form = event.target;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) event.preventDefault();
});

let installPrompt;
const installButton = document.querySelector('#install-app');

window.addEventListener('beforeinstallprompt', function (event) {
  event.preventDefault();
  installPrompt = event;
  if (installButton) installButton.hidden = false;
});

installButton?.addEventListener('click', async function () {
  if (!installPrompt) return;
  await installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  installButton.hidden = true;
});

window.addEventListener('appinstalled', function () {
  if (installButton) installButton.hidden = true;
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js')
    .catch(function (error) {
      console.error('CargoNest service worker registration failed:', error);
    });
}
