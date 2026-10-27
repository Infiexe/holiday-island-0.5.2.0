# Scene Guide (mod do Holiday Island 0.5.2.0)

Mod dodaje do telefonu (Character data → Scenes / Events / Appointments) małą ikonkę ▶ na
każdym kafelku, obok kamerki replay z gry. Ikonka otwiera kartę obok telefonu z informacją,
co gra wymaga do danej sceny, i z przyciskami **Play** oraz **Replay**.

## Instalacja

Skopiuj dwa pliki do folderu `game` gry (tam, gdzie leży `scripts.rpa`):

- `game/hisg_scene_guide.rpy`
- `game/hisg_core.py`

Gra przy starcie sama je skompiluje. Działa obok companion moda.

## Jak to działa

Mod niczego nie ma wpisanego na sztywno dla postaci. Przy pierwszym otwarciu karty (ok. 2 s)
czyta skrypt gry załadowany w pamięci i znajduje:

- miejsca, w których gra oznacza scenę / event / appointment jako zobaczone,
- miejsca, w których startuje albo posuwa się quest,
- drogę od głównej pętli gry do tej sceny: wszystkie `if`, wybory w menu i „strażniki”
  (np. cooldown, złość, check affection), które po drodze ją blokują.

Karta pokazuje te warunki ze statusem:

| Ikona | Znaczenie |
|---|---|
| ✔ | spełnione |
| ✘ | niespełnione |
| ⚙ | mod to ustawi (lokacja, strój, bycie sam na sam) albo wymusi (tryb Guided) |
| ? | losowe albo zależne od wcześniejszego wyboru |
| ➜ | opcja w menu, którą trzeba wybrać – w grze będzie oznaczona żółtą strzałką |

Warunki są opisane zwykłymi słowami (np. „it's 17:00 or earlier (now 00:00)”, „Amy's lust at least 65
(now 52)”, „at least 14 days since Mercedes appointment “Nightbar titfight” (now 6)”), a obok małym
szarym drukiem jest oryginalny warunek z gry.

Brakujące sceny i questy mają link „Show how to get it”, który otwiera ich kartę (np. kolejny
krok questa z opisem z dziennika questów gry i przyciskiem „Play next step”).

## Tryby

- **Honest** (domyślny): mod tylko przenosi Ciebie i postać we właściwe miejsce, przebiera ją
  (jeśli zgodziłaby się w zwykłym dialogu zmiany stroju) i odsyła inne osoby. Statystyki,
  questy i wcześniejsze sceny są tylko pokazywane. Zamknięte lokacje (bar, spa, gabinet,
  restauracja) działają w swoich godzinach. Scena zużywa czas gry jak normalnie.
- **Guided**: dodatkowo wymusza warunki na drodze do sceny (losowania, checki, cooldowny,
  erekcja), przekazuje grze „auto succeed”, ignoruje godziny otwarcia. Wymuszenie dotyczy
  tylko tej jednej sceny i znika po jej zakończeniu.

**Replay** odtwarza już zobaczoną scenę w trybie replay gry, a po jej zakończeniu przywraca
grę dokładnie do stanu sprzed replayu (mod robi przed nim ukryty zapis `hisg_replay`).

Kafelek „Special actions” otwiera tabelkę interakcji (flash / grope / pose) dla każdego stroju.

## Ograniczenia

- Ok. 6% wpisów nie ma drogi, którą da się odtworzyć automatycznie (np. pokazy mody w studiu,
  część eventów na basenie, eventy z dwiema postaciami naraz). Karta pokazuje wtedy hinty z gry.
- Sceny po wygranej w pokera (nagrody, rozbieranie do końca itd.) startują od intro, a potem
  mod od razu daje Ci wygraną i pomija samą partię. Przy innych aktywnościach (np. hotshots)
  mod uruchamia aktywność; wynik zależy od jej przebiegu.
