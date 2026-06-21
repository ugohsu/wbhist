function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  // navigator.clipboard is unavailable on plain http origins (no TLS, not
  // localhost) in most browsers, which is how this app is served over the
  // VPN. Fall back to the old execCommand technique in that case.
  return new Promise((resolve, reject) => {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      resolve();
    } catch (err) {
      reject(err);
    } finally {
      document.body.removeChild(textarea);
    }
  });
}

const app = document.querySelector(".app");
const sideNav = document.querySelector(".side-nav");
const contentInner = document.querySelector(".main .content-inner");

// Sidebar navigation (project list / session list) is fetched and swapped
// in place so the chat currently shown in the main area stays put until the
// user actually picks a different session - only then is the main area
// replaced.
async function applyPage(url, push) {
  let doc;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`unexpected status ${res.status}`);
    doc = new DOMParser().parseFromString(await res.text(), "text/html");
  } catch (err) {
    window.location.href = url;
    return;
  }

  const newSideNav = doc.querySelector(".side-nav");
  if (newSideNav) sideNav.innerHTML = newSideNav.innerHTML;

  if (doc.body.dataset.page === "session") {
    const newContent = doc.querySelector(".main .content-inner");
    if (newContent) {
      contentInner.innerHTML = newContent.innerHTML;
      document.querySelector(".main").scrollTo({ top: 0 });
    }
    // Only a session (conversation) pick should auto-close the sidebar on
    // mobile; project/list navigation should leave it open for browsing.
    app.classList.remove("sidebar-open");
  }

  document.title = doc.title;
  if (push) history.pushState(null, "", url);
}

document.addEventListener("click", (event) => {
  const copyButton = event.target.closest(".copy-btn");
  if (copyButton) {
    const text = copyButton.closest(".msg").querySelector(".msg-text").innerText;
    copyText(text).then(() => {
      copyButton.classList.add("copied");
      setTimeout(() => copyButton.classList.remove("copied"), 1200);
    });
    return;
  }

  if (event.target.closest(".menu-toggle")) {
    app.classList.toggle("sidebar-open");
    return;
  }
  if (event.target.closest(".backdrop")) {
    app.classList.remove("sidebar-open");
    return;
  }

  const link = event.target.closest(".sidebar a[href]");
  if (link && link.href && new URL(link.href, location.href).origin === location.origin) {
    event.preventDefault();
    applyPage(link.href, true);
  }
});

window.addEventListener("popstate", () => {
  applyPage(location.href, false);
});
