import {defineConfig} from "vite";
const proxy = Object.fromEntries(["/tts","/media"].map(path => [path,"http://localhost:8000"]));
export default defineConfig({server:{proxy},preview:{proxy}});
