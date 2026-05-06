setInterval(() => {
  const pill = document.querySelector(".pill-running");
  if (pill && !document.hidden) window.location.reload();
}, 5000);

