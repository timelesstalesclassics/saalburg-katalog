# Saalburg – System-Updates

Dieser Zweig enthält die Teile des Systemabbilds (`teile/<sha256>`, im Mittel ~1 MB) und das
noch unsignierte Manifest (`eingang/manifest.txt`). Erzeugt mit `app system veroeffentlichen`.
Der Ablauf „System freigeben“ prüft alle Teile und legt das signierte Manifest als
`system/aktuell.osm` im Zweig `veroeffentlicht` ab. Neue Versionen fügen nur neue Teile hinzu.
