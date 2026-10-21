// Runs docs/engine.js on the reforms in a cases file and prints the results
// as JSON. Called by build_explorer.py; not meant to be run by hand.

import { readFileSync } from "node:fs";
import { score } from "../docs/engine.js";

const here = new URL("../docs/data.json", import.meta.url);
const data = JSON.parse(readFileSync(here, "utf-8"));
const { reforms } = JSON.parse(readFileSync(process.argv[2], "utf-8"));

const out = {};
for (const [name, reform] of Object.entries(reforms)) {
  out[name] = score(reform, data.params, data.records, data.groups);
}
process.stdout.write(JSON.stringify(out));
