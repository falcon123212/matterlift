// Refuses to deploy a page that is not built: a raw index.html (/src/main.ts) once went live and the
// page lost its CSS. The API is on the same site (Vercel), so no URL is baked in.
import { readFileSync } from "node:fs";

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
if (!js || !read(js[0]).includes("/health")) {
  console.error("dist/index.html does not load the MatterLift page script");
  process.exit(1);
}
console.log("dist ok");
