// YouTube immer im dunklen YouTube-Design zeigen; aussehen.css legt darauf die
// Saalburg-Farben. YouTube merkt sich das Design im Cookie PREF (Feld f6:
// 0x400 = dunkel, 0x80000 = hell). Fehlt „dunkel“, wird es gesetzt und die
// Seite einmal neu geladen – danach nie wieder.
(() => {
  if (location.hostname !== "www.youtube.com" && location.hostname !== "m.youtube.com") return;
  const treffer = document.cookie.match(/(?:^|;\s*)PREF=([^;]*)/);
  const felder = new URLSearchParams(treffer ? treffer[1] : "");
  const alt = parseInt(felder.get("f6") || "0", 16) || 0;
  const neu = (alt | 0x400) & ~0x80000;
  if (neu === alt) return;
  felder.set("f6", neu.toString(16));
  document.cookie = "PREF=" + felder.toString() + "; domain=.youtube.com; path=/; max-age=63072000; secure; samesite=lax";
  // Nur einmal neu laden, auch wenn der Browser das Cookie nicht annimmt
  if (sessionStorage.getItem("saalburg-dunkel") === "1") return;
  sessionStorage.setItem("saalburg-dunkel", "1");
  location.reload();
})();
