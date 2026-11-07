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
(now 52)”, „Random: 35% chance right now”). Oryginalny warunek ze skryptu gry pokazuje się po
najechaniu myszką na wiersz.

- Zmienne, które scena ustawia sama (`option3`, `l_tease`, `l_horny`…), nie są pokazywane
  wprost: karta zamienia je na wybór, który trzeba zrobić wcześniej w tej scenie (➜, w grze
  oznaczony strzałką), albo na test, który o tym decyduje (np. lust dziewczyny).
- Procent przy „Random” jest liczony z kostki i z aktualnego stanu gry (np. „100%”, gdy jej
  lust i tak przesądza wynik). Losowy wyzwalacz eventu też jest na karcie z procentem
  („Random trigger: 40% chance … – the guide skips the roll”).
- Spotkania (appointments) mówią, kto je aranżuje: SMS od niej, który trzeba przyjąć,
  scena, w której się z Tobą umawia, albo zaproszenie z recepcji na konkurs. Link otwiera
  kartę „Arrange” / „Message” z warunkami, kiedy gra to robi (np. „the day is over” +
  „it's Wednesday” dla konkursu), i przyciskiem „Arrange it now” / „Get the message now”.

Mod ogarnia też sceny, w których gra coś losuje albo składa w locie:

- losowanie wersji sceny (np. `Pool_distraction1`…`5`, strój Joy w biurze) i tego, co się
  dzieje przy wizycie w pokoju (prysznic / noc / …) – mod sprawia, że wylosuje się ta właściwa;
- losowanie dziewczyny z grupy (basen, prysznic na siłowni, konkursy) razem z filtrami, które
  gra stosuje przy losowaniu (cooldown, strój, na który gra ma obrazki);
- sceny dwóch dziewczyn, które gra startuje od tej drugiej (prysznic Alice z Amy, drink Faye
  z Natashą, Desire z Jessicą, ciężary na siłowni z Amy) – karta pisze, z kim startuje scena,
  a mod przyprowadza obie;
- sceny przy barmance na zmianie (Honest: musi mieć zmianę, Guided: przejmuje ją).

Brakujące sceny i questy mają link „Show how to get it”, który otwiera ich kartę (np. kolejny
krok questa z opisem z dziennika questów gry i przyciskiem „Play next step”). Quest otwiera
się dla dziewczyny, której dotyczy (quest z sesją zdjęciową u Jennifer – dla barmanki, nie dla
Evy), a krok, który dzieje się w scenie z inną dziewczyną (Alice opowiada o Amy, Joy daje
zadanie), jest planowany z nią.

Przed startem mod sprawdza, czy gra ma obrazki tej dziewczyny do wybranej drogi. Jeśli nie
ma (scena tylko dla innej dziewczyny), wybiera inną drogę albo pisze dlaczego – zamiast
grać na czarnym ekranie.

## Tryby

- **Honest** (domyślny): Play działa tylko wtedy, gdy wszystkie warunki są spełnione i mod umiał je
  sprawdzić. Mod tylko przenosi Ciebie i postać we właściwe miejsce, przebiera ją
  (jeśli zgodziłaby się w zwykłym dialogu zmiany stroju) i odsyła inne osoby. Statystyki,
  questy i wcześniejsze sceny są tylko pokazywane. Zamknięte lokacje (bar, spa, gabinet,
  restauracja) działają w swoich godzinach. Scena zużywa czas gry jak normalnie.
- **Guided**: dodatkowo wymusza warunki na drodze do sceny (losowania, checki, cooldowny,
  erekcja), przekazuje grze „auto succeed”, ignoruje godziny otwarcia i nieumówione
  spotkania. Każdy wpis da się odpalić: części konkursów, w których gra losuje uczestniczki,
  startują od razu z nią, a gdy gra w ogóle nie ma drogi – używana jest jej własna etykieta
  replay. Wymuszenie dotyczy tylko tej jednej sceny i znika po jej zakończeniu.

**Replay** odtwarza już zobaczoną scenę w trybie replay gry, a po jej zakończeniu przywraca
grę dokładnie do stanu sprzed replayu (mod robi przed nim ukryty zapis `hisg_replay`).

Kafelek „Special actions” otwiera tabelkę interakcji (flash / grope / pose) dla każdego stroju.

## Ograniczenia

- Kilka wpisów gra w tej wersji robi tylko dla innych dziewczyn (np. zdjęcie 505 tylko dla
  Yvette) – karta to mówi, Honest ich nie odpala, Guided tak.
- Sceny po wygranej w pokera (nagrody, rozbieranie do końca itd.) startują od intro, a potem
  mod od razu daje Ci wygraną i pomija samą partię. Przy innych aktywnościach (np. hotshots)
  mod uruchamia aktywność; wynik zależy od jej przebiegu.
