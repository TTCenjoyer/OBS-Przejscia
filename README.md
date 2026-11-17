# OBS Przejścia scen

Panel do OBS Studio: osobny efekt **wyjścia** z każdej sceny i opcjonalny efekt **wejścia**. Wejście domyślnie dziedziczy efekt oraz czas wyjścia poprzedniej sceny. Własny efekt wejścia ma pierwszeństwo.

To zestaw skryptów Lua i Python oraz lokalny panel przeglądarkowy, bez osobnej biblioteki DLL.

## Funkcje

- Panel „Przejścia scen” zastępuje standardowy panel efektów i podąża za sceną na programie. Można też wybrać inną scenę do edycji.
- Dla każdej sceny: efekt wyjścia, jego czas, nadpisanie efektu wejścia i jego czasu. Zmiany zapisują się automatycznie, osobno dla każdej kolekcji scen.
- Przy efekcie Fade / Zanikanie źródła audio sceny A są wyciszane, a sceny B zgłaśniane równocześnie z obrazem. Wspólne źródła zachowują poziom.
- Scena przerwy: własny GIF lub film w pętli, pierwsze audio raz, następnie drugie audio w pętli. Powrót na scenę ponownie uruchamia początek.
- Wybrany mikrofon jest wyciszany na przerwie i wraca do wcześniejszego stanu po jej zakończeniu.
- Podgląd w trybie studia nie uruchamia muzyki; liczy się scena na programie.

## Wymagania

Sprawdzone na **Windows, OBS Studio 32.0.4 (Qt 6.8.3), Python 3.12 x64**. Integracja panelu używa funkcji Qt dla Windows; inne systemy i wersje Qt nie zostały przetestowane. Zależności panelu są przypięte do Qt 6.8.3.

Potrzebne są OBS z obsługą skryptów Python i źródeł przeglądarkowych oraz Python 3.12 x64 z pip. Dla efektu Move zainstaluj dodatkowo [Move Transition](https://github.com/exeldro/obs-move-transition) i dodaj go do listy przejść OBS przed instalacją. Bez niego instalator wybierze dostępne Zanikanie jako domyślne przejście.

OBS WebSocket nie jest wymagany. Panel komunikuje się wyłącznie z lokalnym adresem `127.0.0.1:17863`, z losowym tokenem tworzonym przy instalacji. Port musi być wolny; obsługiwana jest jedna instancja panelu naraz.

## Instalacja

1. Pobierz repozytorium przez **Code → Download ZIP** i rozpakuj.
2. Zamknij OBS. Instalator zapisuje konfigurację aktywnej kolekcji; nie zamyka programu samodzielnie.
3. Otwórz terminal w rozpakowanym folderze i uruchom:

   ```powershell
   py -3.12 install.py
   ```

4. Uruchom OBS. Pojawią się panel „Przejścia scen” i scena „Przerwa — Beyond the Sea”. Jeśli system zapyta o dostęp serwera do sieci, nie jest on potrzebny do działania panelu na localhost.
5. W **Narzędzia → Skrypty → przerwa.lua** wybierz własne pliki „Początek — jeden raz” i „Muzyka — pętla”. Właściwości źródła **„Przerwa | GIF — wybierz plik”** służą do wskazania GIF-a lub filmu.

Pliki trafiają do `%LOCALAPPDATA%\OBS-Przejscia`. Instalator dodaje trzy skrypty i panel do aktywnej kolekcji, zachowując istniejące sceny, źródła, filtry i inne skrypty. Przed zmianą zapisuje kopię `user.ini` i pliku kolekcji w podfolderze `backups`. Instalacja nie zmienia konfiguracji WebSocket ani ustawień istniejącego efektu Move.

Domyślnie wyciszany jest pierwszy globalny mikrofon OBS; jeśli go nie wykryto, używana jest nazwa „Mikrofon/Wejście liniowe”. Możesz wskazać dokładną nazwę swojego źródła:

```powershell
py -3.12 install.py --microphone "Mój mikrofon"
```

Pozostałe opcje:

```powershell
py -3.12 install.py --intro "D:\Audio\poczatek.wav" --loop "D:\Audio\petla.mp3"
py -3.12 install.py --config-dir "D:\OBS\config\obs-studio" --collection "MojaKolekcja.json"
py -3.12 install.py --destination "D:\DodatkiOBS\Przejscia"
```

Ponowne uruchomienie instalatora aktualizuje skrypty, zachowując zapisane reguły i token panelu. Aby dodać obsługę kolejnej kolekcji, uruchom ją w OBS, zamknij OBS i ponów instalację.

## Ustawienie przejść

W panelu ustaw **Wyjście z tej sceny**. Dla wejścia pozostaw **Wyjście poprzedniej sceny** albo wybierz własny efekt. Czas wejścia `0` oznacza odziedziczenie czasu wyjścia poprzedniej sceny.

Przykład: wyjście sceny głównej = Move, wyjście przerwy = Zanikanie. Przy braku nadpisania wejścia przejście główna → przerwa użyje Move, a przerwa → główna użyje Zanikania. Jeśli przerwa ma zawsze pojawiać się przez Zanikanie, ustaw również jej własny efekt wejścia na Zanikanie.

Scena przerwy musi zachować nazwę **„Przerwa — Beyond the Sea”**. Nazwa jest historyczna; można użyć dowolnej własnej muzyki. Repozytorium nie zawiera utworów, GIF-ów, nagrań ani konfiguracji użytkownika.

Przy ciężkim GIF-ie warto użyć własnego krótkiego MP4 z zapętlaniem. Jeśli kamera pojawia się dopiero po przejściu, sprawdź opcję jej dezaktywowania, gdy nie jest widoczna. W konfiguracji Move nie wybieraj Move jako jego własnego przejścia pomocniczego.

## Rozwiązywanie problemów i usuwanie

- Panel pokazuje „Łączenie”: sprawdź dziennik **Narzędzia → Skrypty**, Python 3.12 x64, wersję Qt OBS oraz wolny port `17863`.
- Panel nie jest widoczny: sprawdź **Panele → Przejścia scen**. Adres panelu to plik `panel.html` w katalogu instalacji.
- Brak wyciszania mikrofonu: uruchom instalator z `--microphone` i dokładną nazwą źródła z miksera.
- Brak muzyki: wskaż oba pliki audio w ustawieniach `przerwa.lua`. Zmiana pliku bezpośrednio w źródle audio zostanie nadpisana przez skrypt.
- Muzyka odtwarza się, ale jej nie słychać: po zakończeniu przejścia sprawdź głośność źródła „Przerwa | 1. Początek” oraz źródła pętli. Poziom `−∞ dB` oznacza całkowitą ciszę mimo odtwarzania. W **Zaawansowanych ustawieniach dźwięku** przywróć żądany poziom, np. `0 dB`, a następnie wyjdź z przerwy i wróć na nią. Sprawdź też urządzenie monitorowania, jeśli słuchasz dźwięku przez odsłuch OBS.
- Aby usunąć dodatek, usuń jego trzy pozycje w **Narzędzia → Skrypty**, usuń własny panel przeglądarkowy „Przejścia scen” i włącz standardowy panel efektów. Scenę przerwy można usunąć osobno.
- Aby przywrócić konfigurację z kopii, zamknij OBS i skopiuj `user.ini` do katalogu konfiguracji, a plik kolekcji do `basic/scenes`. Kopia odtwarza stan z momentu instalacji, więc późniejsze zmiany w tych plikach zostaną zastąpione.

## Kod i sprawdzanie instalatora

| Plik | Rola |
| --- | --- |
| `plugin/przejscia-scen.lua` | Reguły przejść, wyciszanie mikrofonu i obwiednie audio |
| `plugin/przerwa.lua` | Scena przerwy i kolejność odtwarzania muzyki |
| `plugin/panel-przejsc.py` | Integracja panelu z OBS i lokalne API |
| `plugin/panel.html` | Interfejs panelu |
| `install.py` | Instalacja, zależności i kopia konfiguracji |

```powershell
py -3.12 -m unittest discover -s tests -v
```

Testy instalatora korzystają z tymczasowych plików i przykładowej kolekcji. Nie uruchamiają OBS ani nie zmieniają jego konfiguracji. Działanie scen, przejść, dźwięku i panelu było sprawdzane osobno w OBS 32.0.4 na Windows; po instalacji sprawdź własne źródła przed transmisją.

Pliki `panel-access.json`, `panel-config.js`, `przejscia-ustawienia.json`, `runtime` i `backups` powstają lokalnie i są wykluczone z Git. Nie publikuj tokenu panelu ani kopii własnej konfiguracji OBS.

Licencja MIT. Move Transition, OBS, Python i biblioteki Qt mają własne licencje.
