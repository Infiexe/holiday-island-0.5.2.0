# Free Invites (mod do Holiday Island 0.5.2.0)

Zapraszanie dziewczyn na wyspę i odsyłanie ich do domu w recepcji nic nie kosztuje,
a wyspa nie ma już limitu dziewczyn. Na liście zaproszeń można wybrać kilka dziewczyn
albo wszystkie naraz.

## Instalacja

Skopiuj plik do folderu `game` gry (tam, gdzie leży `scripts.rpa`):

- `game/hifi_free_invites.rpy`

Gra przy starcie sama go skompiluje. Działa obok Scene Guide i companion moda.

## Co się zmienia

- **Recepcja → „Ask for a new girl to be invited to the island”**
  - bez 100 company favor,
  - bez limitu 10 dziewczyn na wyspie i bez czekania, aż przyjedzie poprzednio
    zaproszona dziewczyna – opcja jest dostępna, dopóki jest kogo zaprosić,
  - lista pozwala zaznaczyć dowolną liczbę dziewczyn; przyciski **Invite all**
    (wszystkie naraz), **Invite selected**, **Select all**, **Clear**, **Cancel**.
- **Recepcja → „Ask for a girl to be sent home, away from the island”**
  - bez 50 company favor,
  - minimum zostaje jak w grze: odesłać można, gdy na wyspie jest co najmniej 8 dziewczyn.
- **Limit dziewczyn na wyspie** jest zdjęty także tam, gdzie gra go sprawdza poza
  recepcją: przy przyjeździe zaproszonej dziewczyny, w biurze Joy po 10 dniach
  (nie trzeba nikogo odsyłać przed zaproszeniem) i przy powrocie Amy.

Bez zmian zostaje to, co nie jest opłatą ani limitem:

- opcje w recepcji pojawiają się od 10. dnia gry, jak w oryginale,
- zaproszone dziewczyny przyjeżdżają następnego dnia, każda ze swoją sceną przyjazdu
  (po jednej przy wejściu do pokoju albo recepcji),
- gra sama nie dosyła losowych dziewczyn ponad swój limit 10 – zapraszasz tylko Ty,
- lista zaproszeń pomija te same dziewczyny co oryginalna (personel, Yvette w trakcie
  questa z siostrą, Amy po zabiegu, dziewczyna odesłana tego samego dnia).

## Jak to działa

Mod nie podmienia skryptów gry. Przy starcie znajduje w załadowanym skrypcie te kilka
instrukcji, które pobierają favor albo sprawdzają limit (`g_max_chars_on_island`),
i zmienia je w pamięci; zamiast jednego wyboru na liście zaproszeń pokazuje swoją listę
z wieloma wyborami. Zapisy gry zostają zgodne – po usunięciu pliku gra wraca do swoich
zasad.
