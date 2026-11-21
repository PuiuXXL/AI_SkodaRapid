import {defineConfig} from "vite";
import {driverPlugin} from "./server/api.mjs";
const proxy = Object.fromEntries(["/tts","/media"].map(path => [path,"http://localhost:8000"]));
export default defineConfig({plugins:[driverPlugin()],server:{proxy,fs:{deny:[".env",".env.*","*.{crt,pem}","**/.git/**","**/profiles/**"]}},preview:{proxy}});
