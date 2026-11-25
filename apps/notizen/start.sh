#!/bin/sh
# Notizen: nano mit den Farben von Saalburg (PLATTFORM.md, Abschnitt 5).
# Liest /daten/system/aussehen/saalburg.conf (Rückfall /usr/lib/osproto/aussehen/saalburg.conf),
# baut daraus eine nanorc in $HOME und startet nano damit. Fehlen beide Dateien: nano ohne Farben.
# Den Hintergrund des Terminals lässt das Skript stehen.

d="$HOME/Dokumente"
datei="$d/notizen.txt"

# Ältere Versionen legten die Notizen direkt in $HOME ab.
[ -f "$HOME/notizen.txt" ] && [ ! -e "$datei" ] && mkdir -p "$d" && mv "$HOME/notizen.txt" "$d/"

conf=/daten/system/aussehen/saalburg.conf
[ -r "$conf" ] || conf=/usr/lib/osproto/aussehen/saalburg.conf
[ -r "$conf" ] || exec nano "$datei"

# farbe <rolle> <vorgabe>: #rrggbb aus der Datei (sonst Vorgabe) als #rgb für nano
farbe() {
	v=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\(#[0-9A-Fa-f]\{6\}\)[[:space:]]*\$/\1/p" "$conf" | tail -n 1)
	h=${v:-$2}
	h=${h#\#}
	o='#'
	for i in 1 2 3; do
		r=${h#??}
		p=${h%"$r"}
		h=$r
		o="$o$(printf %x $(((0x$p * 15 + 127) / 255)))"
	done
	echo "$o"
}

text=$(farbe text '#c0caf5')
hell=$(farbe text_hell '#f2f4fb')
gedaempft=$(farbe text_gedaempft '#8089b0')
karte=$(farbe karte '#1a1b26')
hoch=$(farbe flaeche_hoch '#24283b')
auswahl=$(farbe auswahl '#364466')
akzent=$(farbe akzent '#7aa2f7')
fehler=$(farbe fehler '#f7768e')

rc="$HOME/.nanorc-saalburg"
cat > "$rc.neu" <<EOF
# Von Notizen beim Start erzeugt (Farben aus $conf) – Änderungen gehen verloren.
set titlecolor $hell,$hoch
set statuscolor $text,$karte
set selectedcolor ,$auswahl
set keycolor $akzent
set functioncolor $gedaempft
set promptcolor $text,$karte
set errorcolor $fehler
EOF
mv -f "$rc.neu" "$rc" || exec nano "$datei"

exec nano --rcfile "$rc" "$datei"
