# DriveMate — pitch CodeLap 2026

Durată orientativă: 3 minute și 10 secunde, incluzând icebreaker-ul și pauza de două secunde. Notele sunt incluse și în PowerPoint.

## 1. Icebreaker și exercițiul de două secunde · 0:00–0:22

Mașinile noi primesc monitorizarea șoferului prin regulament. Škoda noastră din 2016 o primește prin hackathon.

[PAUZĂ SCURTĂ PENTRU REACȚIE.]

Vă propun un exercițiu. Închideți ochii pentru două secunde.

[PAUZĂ REALĂ DE DOUĂ SECUNDE. Avansați apoi la slide-ul 2.]

Context UE: cerințele pentru noile autoturisme și utilitare se introduc etapizat; avertizarea avansată la distragere se aplică de la 7 iulie 2026. Nu este o obligație de retrofit pentru mașina noastră din 2016. Sursa: https://commission.europa.eu/news-and-media/news/safer-cars-safer-roads-new-rules-take-effect-2026-07-08_en

## 2. 56 de metri · 0:22–0:40

Îi puteți deschide. La 100 de kilometri pe oră, în acest timp ați fi parcurs aproape 56 de metri fără să vedeți drumul. Atât poate dura să citiți un mesaj sau să căutați o melodie. Iar dacă sunteți obosiți, ochii se pot închide fără să vă dați seama. De aici am pornit cu DriveMate.

Calcul propriu, viteză constantă: 100 km/h / 3,6 × 2 s = 55,56 m.

## 3. De ce contează acceptarea · 0:40–1:05

Mașinile pot avertiza când pierdem atenția. Dar contează și cum o fac. Dacă un sistem întrerupe prea des sau intervine nepotrivit, șoferul poate ajunge să-l dezactiveze. Euro NCAP pune accent, în evaluările din 2026, atât pe monitorizarea șoferului, cât și pe fiabilitatea și acceptarea sistemelor în utilizarea reală.

Sursa oficială: https://www.euroncap.com/press-media/euro-ncap-announces-2026-protocol-changes-to-tackle-modern-driving-risks/

Este o actualizare a programului de evaluare Euro NCAP. DriveMate nu este evaluat sau certificat Euro NCAP. Acceptarea DriveMate de către șoferi este un obiectiv de validat cu utilizatori.

## 4. Ideea și funcționalitățile · 1:05–1:40

DriveMate este un copilot care urmărește starea șoferului și adaptează intervenția la context. Analizăm privirea, închiderea ochilor, poziția capului și folosirea telefonului. Combinăm aceste semnale cu informații despre călătorie și cabină, pentru a evalua atenția, oboseala și dezinteresul. O privire spre oglindă, o conversație cu pasagerul și ochii închiși cer reacții diferite. Vrem ca intervenția să aibă sens pentru situația observată. Când observă semne de oboseală, DriveMate poate propune o pauză. Pe un drum monoton poate sugera muzică. Te ajută cu mesaje și mementouri prin voce, iar răspunsurile pot veni și prin gesturi.

## 5. Siguranța are prioritate · 1:40–2:05

Pentru situațiile grave, avem un flux de escaladare. Sistemul avertizează, verifică dacă șoferul răspunde și poate declanșa procedura SOS prin canalele configurate. Regulile critice de siguranță au prioritate față de conversația cu AI-ul.

Procedura SOS depinde de canalele configurate și disponibile. Slide-ul nu afirmă integrare automată cu serviciul 112. Referință implementare: core/safety/sos.py; core/safety/arbiter.py.

## 6. Pipeline-ul · 2:05–2:35

Pipeline-ul nostru pornește de la camere. Modulul de percepție extrage semnalele, motorul de context evaluează starea, regulile decid intervenția, iar asistentul o comunică șoferului. Dashboardul ne permite să urmărim această succesiune și explicația evenimentelor. Simulatorul ne ajută să reproducem trasee și scenarii. Am construit modulele pe un contract comun de date, apoi le-am integrat și verificat prin teste și scenarii demonstrative.

Referințe proiect: shared/contracts.py; perception/; core/; assistant/; dashboard/; simulator/; tests/.

## 7. Configurabil, pentru șofer · 2:35–3:10

Șoferii au și preferințe diferite. Uneori vrei conversație. Alteori vrei liniște. Din setări poți alege cât de des primești sugestii, cât de scurte sunt răspunsurile și dacă asistentul continuă cu întrebări. Îi adaptezi comportamentul la dispoziția ta. Aceasta este miza DriveMate. Să construim un asistent pe care alegi să-l păstrezi activ, pentru că te ajută și îți respectă atenția. DriveMate. Un copilot care are grijă de șofer, în timp ce șoferul are grijă de drum.

Configurarea privește preferințele de confort. Regulile critice de siguranță au prioritate. Retenția și acceptarea utilizatorilor necesită validare. Referință implementare: dashboard/src/driver/SettingsPage.tsx; assistant/preferences.py.

