document.addEventListener("click", (event) => {
  const copyButton = event.target.closest(".copy-btn");
  if (copyButton) {
    const text = copyButton.closest(".msg").querySelector(".msg-text").innerText;
    navigator.clipboard.writeText(text).then(() => {
      copyButton.classList.add("copied");
      setTimeout(() => copyButton.classList.remove("copied"), 1200);
    });
    return;
  }

  const app = document.querySelector(".app");
  if (event.target.closest(".menu-toggle")) {
    app.classList.toggle("sidebar-open");
    return;
  }
  if (event.target.closest(".backdrop")) {
    app.classList.remove("sidebar-open");
  }
});
