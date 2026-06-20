document.addEventListener("click", (event) => {
  const button = event.target.closest(".copy-btn");
  if (!button) return;

  const text = button.closest(".msg").querySelector(".msg-text").innerText;
  navigator.clipboard.writeText(text).then(() => {
    button.classList.add("copied");
    setTimeout(() => button.classList.remove("copied"), 1200);
  });
});
