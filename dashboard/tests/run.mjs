import {build} from "esbuild";
import {mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {spawnSync} from "node:child_process";

const temporary = await mkdtemp(join(tmpdir(), "drivemate-check-"));
try {
 const outfile=join(temporary,"dashboard.test.mjs");
 await build({entryPoints:["tests/dashboard.test.tsx"],bundle:true,platform:"node",format:"esm",outfile,jsx:"automatic",banner:{js:'import {createRequire} from "node:module"; const require = createRequire(import.meta.url);'},loader:{".css":"empty"},define:{"import.meta.env":"{}","process.env.NODE_ENV":"\"production\""},logLevel:"error"});
 const result=spawnSync(process.execPath,["--test",outfile,"tests/driver.test.mjs"],{stdio:"inherit"});
 process.exitCode=result.status??1;
} finally {
 await rm(temporary,{recursive:true,force:true});
}
