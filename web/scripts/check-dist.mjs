// Refuses to deploy a page that still points at the sources (/src/main.ts): it would load unstyled.
import { readFileSync } from "node:fs";

// web/dist, wherever this runs from (web/ for npm run deploy, the repository root for Cloudflare)
const dist = new URL("../dist/", import.meta.url);
const read = (path) => readFileSync(new URL(path, dist), "utf8");

for (const page of ["index.html", "live.html"]) {
  const html = read(page);
  if (/src="\/?src\//.test(html) || !html.includes("./assets/")) {
    console.error(`dist/${page} is not a built page (run npm run build)`);
    process.exit(1);
  }
}
const js = read("index.html").match(/assets\/main-[^"]+\.js/);
if (!js || !read(js[0]).includes(".modal.run")) {
  console.error("the built page has no API URL (VITE_API_URL)");
  process.exit(1);
}
console.log("dist ok");
