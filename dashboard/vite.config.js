import {defineConfig} from "vite";
// The dashboard has no backend of its own: all data comes from core (/ws/ui, see src/driver/session.ts).
// /tts and /media are core routes used by the voice player; /simulator takes the route drawn on the map (#/simulator).
const proxy = Object.fromEntries(["/tts","/media","/simulator"].map(path => [path,"http://localhost:8000"]));
export default defineConfig({server:{proxy,fs:{deny:[".env",".env.*","*.{crt,pem}","**/.git/**"]}},preview:{proxy}});
