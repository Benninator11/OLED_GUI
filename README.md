# OLED Control Center – Raspberry Pi 4 / 5

Grafische Anwendung zur Steuerung eines SSD1306-OLED-Displays (128×64, I²C).
Das Installationspaket ist für Raspberry Pi OS auf ARM32/ARM64 vorgesehen. x86-PCs werden vom Installer bewusst abgewiesen.

## Installation

1. ZIP-Datei auf dem Raspberry Pi entpacken.
2. Im entpackten Ordner ein Terminal öffnen.
3. Folgenden Befehl ausführen:

   ```bash
   ./install.sh
   ```

   Alternativ: `bash install.sh`.

Der Installer installiert die benötigten Raspberry-Pi-OS-Pakete, richtet eine eigene Python-Umgebung ein und installiert `luma.oled` sowie `psutil` für ARM. Anschließend legt er automatisch einen Eintrag im Anwendungsmenü und eine Verknüpfung auf dem Desktop an.

**Wichtig:** Das Skript nicht mit `sudo` starten. Es fragt bei Bedarf selbst nach dem Administrator-Passwort.

## Starten

Nach der Installation über **OLED Control Center** im Anwendungsmenü oder über das Desktop-Symbol starten.

## Hardware

- Raspberry Pi 4 oder Raspberry Pi 5
- SSD1306 OLED, 128×64 Pixel, I²C-Adresse üblicherweise `0x3C`
- I²C muss in der Raspberry-Pi-Konfiguration aktiviert sein.

Das Programm kann auch ohne angeschlossenes OLED im virtuellen Modus geöffnet werden. Für die Hardware-Ausgabe müssen I²C aktiviert und die Display-Verkabelung korrekt sein.

## Fehlerprotokoll

Falls sich das Fenster nicht öffnet, steht das Protokoll unter:

`~/.local/state/oled-control-center/app.log`

## Manuell starten

```bash
~/.local/share/oled-control-center/launch.sh
```
