// Nötig, weil CSS es nicht kann: YouTube zeigt abgemeldet sein helles Design,
// auch wenn Saalburg dunkel will, und aussehen.css greift nur im dunklen
// (html[dark]). YouTube merkt sich das Design im eigenen Cookie PREF, Feld f6
// (0x400 dunkel, 0x80000 hell). Fehlt „dunkel“, wird es gesetzt und die Seite
// einmal neu geladen. Liest nur dieses Cookie, kein Netz, keine Seiteninhalte.
(() => {
  const treffer = document.cookie.match(/(?:^|;\s*)PREF=([^;]*)/);
  const felder = new URLSearchParams(treffer ? treffer[1] : "");
  const alt = parseInt(felder.get("f6") || "0", 16) || 0;
  const neu = (alt | 0x400) & ~0x80000;
  if (neu === alt) return;
  felder.set("f6", neu.toString(16));
  document.cookie = "PREF=" + felder.toString() + "; domain=.youtube.com; path=/; max-age=63072000; secure; samesite=lax";
  // Nur einmal neu laden, auch wenn das Cookie nicht angenommen wird
  if (sessionStorage.getItem("saalburg-dunkel") === "1") return;
  sessionStorage.setItem("saalburg-dunkel", "1");
  location.reload();
})();
