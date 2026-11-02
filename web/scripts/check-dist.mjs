// Refuses to deploy a page that still points at the sources (/src/main.ts): it would load unstyled.
import { readFileSync } from "node:fs";

for (const page of ["dist/index.html", "dist/live.html"]) {
  const html = readFileSync(page, "utf8");
  if (/src="\/?src\//.test(html) || !html.includes("./assets/")) {
    console.error(`${page} is not a built page (run npm run build)`);
    process.exit(1);
  }
}
const js = readFileSync("dist/index.html", "utf8").match(/assets\/main-[^"]+\.js/);
if (!js || !readFileSync(`dist/${js[0]}`, "utf8").includes(".modal.run")) {
  console.error("the built page has no API URL (VITE_API_URL)");
  process.exit(1);
}
console.log("dist ok");
