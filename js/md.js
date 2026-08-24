/*
  md.js
  Markdown / link cleanup for Hope chat bubbles
*/
function mdToHTML(s) {
  if (!s) return "";
  let text = String(s);

  // Real HTML anchors → Label (url)
  text = text.replace(
    /<a\s+[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi,
    (_, href, label) => {
      const cleanHref = String(href).trim().replace(/["']/g, "");
      const cleanLabel = String(label).replace(/<[^>]+>/g, "").trim();
      if (cleanLabel && cleanLabel !== cleanHref) {
        return `${cleanLabel} (${cleanHref})`;
      }
      return cleanHref;
    }
  );

  // Strip leaked attribute junk
  text = text.replace(
    /["']?\s*target\s*=\s*["']?_blank["']?\s*rel\s*=\s*["'][^"']*["']\s*>/gi,
    " "
  );

  // Quotes stuck to URLs
  text = text.replace(/(https?:\/\/[^\s]+?)["']+/g, "$1");

  // Escape
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Markdown links
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Bare URLs — skip if already inside href=
  html = html.replace(/https?:\/\/[^\s<]+/gi, (match, offset, full) => {
    const before = full.slice(Math.max(0, offset - 12), offset).toLowerCase();
    if (
      before.includes('href="') ||
      before.includes("href='") ||
      before.includes("href=")
    ) {
      return match;
    }
    const trailing = match.match(/[.,!?);:"'\]]+$/);
    let clean = trailing ? match.slice(0, -trailing[0].length) : match;
    clean = clean.replace(/["']/g, "");
    const end = trailing ? trailing[0].replace(/["']/g, "") : "";
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer">${clean}</a>${end}`;
  });

  // Plain domains
  html = html.replace(
    /\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz|info|biz))\b/gi,
    (domain, _1, offset, full) => {
      const before = full.slice(Math.max(0, offset - 15), offset).toLowerCase();
      if (
        before.includes("href=") ||
        before.includes("://") ||
        before.includes("<a ")
      ) {
        return domain;
      }
      return `<a href="https://${domain}" target="_blank" rel="noopener noreferrer">${domain}</a>`;
    }
  );

  return html.replace(/\n\n/g, "<br><br>").replace(/\n/g, "<br>");
}

window.mdToHTML = mdToHTML;
