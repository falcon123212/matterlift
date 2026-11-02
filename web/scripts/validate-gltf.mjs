// Khronos glTF-Validator on .glb files: prints one JSON summary per file, exits 1 on any error.
import { readFileSync } from "node:fs";
import validator from "gltf-validator";

let failed = false;
for (const path of process.argv.slice(2)) {
  const report = await validator.validateBytes(new Uint8Array(readFileSync(path)));
  const { numErrors, numWarnings, numInfos } = report.issues;
  const errors = report.issues.messages.filter((m) => m.severity === 0).map((m) => `${m.code} ${m.pointer ?? ""}`);
  console.log(JSON.stringify({ file: path, errors: numErrors, warnings: numWarnings, infos: numInfos, details: errors }));
  failed ||= numErrors > 0;
}
process.exit(failed ? 1 : 0);
