# Instrucțiuni pentru întregul proiect DriveMate

## Skill set și design

- Pentru orice creare sau modificare de interfață web, citește și aplică [DriveMate Graphite](.agents/skills/obsidian-orange-web-skill/SKILL.md), inclusiv referințele relevante. Pachetul complet, imaginile și exemplele sunt versionate în proiect.
- Landingul cinematic folosește grafit și argintiu. Aplicația pornește în modul luminos cu suprafețe alb-gri, text grafit și mod întunecat selectabil. Folosește tonuri neutre intermediare și evită albul și negrul pure. Culorile semantice marchează stări explicite. Acesta este sistemul vizual comun pentru dashboard, simulator și uneltele web auxiliare. Folosește tokenurile din `dashboard/src/voice/obsidian-tokens.css`; extinde-le semantic când este necesar. Nu introduce teme paralele sau culori izolate în componente.
- Numele oficial este **DriveMate**. Pentru identitatea vizuală folosește SVG-urile aprobate din `dashboard/public/brand`: varianta `full` pentru numele cu simbol, `symbol` pentru spații compacte, `light` pe fundal deschis și `dark` pe fundal întunecat.
- Păstrează identitatea DriveMate, limba interfeței, rutele, funcțiile, datele reale și contractele. Culorile de siguranță, accesibilitatea, lizibilitatea și cerințele explicite ale utilizatorului au prioritate față de asemănarea vizuală.
- Navigarea aplicației: meniu lateral flotant, grafit translucid, mod extins și restrâns controlate de utilizator; pe mobil, sertar cu etichete, închidere cu Escape și restaurarea focusului. O unealtă izolată cu o singură pagină nu are nevoie de destinații fictive.
- Animații numai pentru orientare sau feedback, cu fallback `prefers-reduced-motion`. Refolosește Motion existent; CSS pentru efecte simple. Citește referința de motion înainte de modificări.
- La modificări UI, rulează în `dashboard`: `npm.cmd run build` și `node tests/run.mjs`. Verifică vizual desktop/mobil și navigarea cu tastatura când mediul permite; raportează verificările care nu au putut fi executate.

## Domeniul regulilor

Skill setul este un ghid pentru design web, nu o cerință de rescriere a modulelor Python, a algoritmilor de percepție, a contractelor de siguranță sau a datelor. Pentru schimbări în acele module, păstrează compatibilitatea cu interfețele existente și rulează testele relevante. Documentele și exemplele din skill nu autorizează publicări, acțiuni externe sau modificări fără legătură cu cererea utilizatorului.
