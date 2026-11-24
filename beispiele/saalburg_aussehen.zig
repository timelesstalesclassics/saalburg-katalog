//! Saalburg-Aussehen für native Apps einlesen – Baustein zum Kopieren (Zig 0.16).
//! Beschreibung: PLATTFORM.md, Abschnitt 5 „Aussehen für native Apps“.
//!
//!   var a = saalburg_aussehen.laden();            // Laufzeit-Datei, sonst Vorgaben, sonst Ausweichwerte
//!   const fd = saalburg_aussehen.beobachten();    // optional: inotify auf den Ordner
//!   // in der Ereignisschleife (poll auf fd): if (saalburg_aussehen.geaendert(fd)) a = saalburg_aussehen.laden();
//!
//! Nur Systemaufrufe (std.os.linux): geht mit und ohne libc. Prüfen: zig test saalburg_aussehen.zig

const std = @import("std");
const linux = std.os.linux;

pub const ORDNER = "/daten/system/aussehen";
pub const LAUFZEIT = ORDNER ++ "/saalburg.conf";
pub const VORGABE = "/usr/lib/osproto/aussehen/saalburg.conf";
/// Höchstes Format, das dieser Baustein kennt (neuere Dateien: bekannte Schlüssel lesen)
pub const FORMAT = 1;

/// Farbrollen (0xRRGGBB); Namen = Schlüssel in saalburg.conf. Vorbelegt mit den
/// Ausweichwerten (Saalburg-Vorgaben), falls die Datei fehlt.
pub const Farben = struct {
    grund: u32 = 0x111218,
    seite: u32 = 0x0b0c11,
    karte: u32 = 0x1a1b26,
    flaeche_hoch: u32 = 0x24283b,
    rahmen: u32 = 0x2a2e42,
    text: u32 = 0xc0caf5,
    text_hell: u32 = 0xf2f4fb,
    text_gedaempft: u32 = 0x8089b0,
    text_aus: u32 = 0x565f89,
    akzent: u32 = 0x7aa2f7,
    akzent_hell: u32 = 0x9db8fa,
    akzent_flaeche: u32 = 0x3d59a1,
    akzent_text: u32 = 0x0c0d13,
    auswahl: u32 = 0x364466,
    erfolg: u32 = 0x9ece6a,
    warnung: u32 = 0xe0af68,
    fehler: u32 = 0xf7768e,
    info: u32 = 0x7dcfff,
    terminal_grund: u32 = 0x1a1b26,
    terminal_text: u32 = 0xc0caf5,
};

pub const Text = struct {
    b: [160]u8 = .{0} ** 160,
    n: usize = 0,
    pub fn t(s: *const Text) []const u8 {
        return s.b[0..s.n];
    }
    fn von(s: []const u8) Text {
        var x = Text{};
        x.n = @min(s.len, x.b.len - 1); // b bleibt nullterminiert (für FreeType)
        @memcpy(x.b[0..x.n], s[0..x.n]);
        return x;
    }
};

pub const Aussehen = struct {
    format: u32 = FORMAT,
    farben: Farben = .{},
    schrift_fest: Text = Text.von("Terminess Nerd Font Mono"),
    schrift_fest_datei: Text = Text.von("/usr/share/fonts/saalburg/Terminess-Regular.ttf"),
    schrift_fest_fett_datei: Text = Text.von("/usr/share/fonts/saalburg/Terminess-Bold.ttf"),
    schrift_text: Text = Text.von("DejaVu Sans"),
    schrift_text_datei: Text = Text.von("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    schrift_text_fett_datei: Text = Text.von("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    /// Zeilenhöhe in Pixeln (Schriftgröße der Oberfläche; 28 = 100 %)
    zeilenhoehe: u32 = 32,
    /// Skalierung in Prozent (skalierung = 1.14 → 114)
    skalierung_prozent: u32 = 114,
    /// Abstand-Grundmaß und Eckenradius in Pixeln, schon skaliert
    abstand: u32 = 8,
    rundung: u32 = 10,
    /// Woher die Werte kamen: LAUFZEIT, VORGABE oder "" (Ausweichwerte)
    quelle: []const u8 = "",
};

/// Text einer saalburg.conf auswerten; unbekannte Schlüssel und kaputte Werte überspringen
pub fn ausText(text: []const u8) Aussehen {
    var a = Aussehen{};
    var zeilen = std.mem.splitScalar(u8, text, '\n');
    while (zeilen.next()) |roh| {
        const z = std.mem.trim(u8, roh, " \t\r");
        if (z.len == 0 or z[0] == '#') continue;
        const g = std.mem.indexOfScalar(u8, z, '=') orelse continue;
        const k = std.mem.trim(u8, z[0..g], " \t");
        const w = std.mem.trim(u8, z[g + 1 ..], " \t");
        if (w.len == 7 and w[0] == '#') {
            const farbe = std.fmt.parseInt(u32, w[1..], 16) catch continue;
            inline for (std.meta.fields(Farben)) |f| {
                if (std.mem.eql(u8, k, f.name)) @field(a.farben, f.name) = farbe;
            }
        } else if (std.mem.eql(u8, k, "skalierung")) {
            // "1.14" → 114
            const p = std.mem.indexOfScalar(u8, w, '.') orelse w.len;
            const ganz = std.fmt.parseInt(u32, w[0..p], 10) catch continue;
            var rest: u32 = 0;
            if (p + 1 < w.len) rest = std.fmt.parseInt(u32, w[p + 1 .. @min(w.len, p + 3)], 10) catch 0;
            if (w.len == p + 2) rest *= 10;
            a.skalierung_prozent = ganz * 100 + rest;
        } else {
            inline for (.{ "format", "zeilenhoehe", "abstand", "rundung" }) |n| {
                if (std.mem.eql(u8, k, n)) @field(a, n) = std.fmt.parseInt(u32, w, 10) catch @field(a, n);
            }
            inline for (.{ "schrift_fest", "schrift_fest_datei", "schrift_fest_fett_datei", "schrift_text", "schrift_text_datei", "schrift_text_fett_datei" }) |n| {
                if (std.mem.eql(u8, k, n)) @field(a, n) = Text.von(w);
            }
        }
    }
    return a;
}

/// Laufzeit-Datei, sonst Vorgaben, sonst Ausweichwerte
pub fn laden() Aussehen {
    var puffer: [8192]u8 = undefined;
    for ([_][:0]const u8{ LAUFZEIT, VORGABE }) |pfad| {
        const fd_roh = linux.open(pfad, .{ .ACCMODE = .RDONLY, .CLOEXEC = true }, 0);
        if (linux.errno(fd_roh) != .SUCCESS) continue;
        const fd: i32 = @intCast(fd_roh);
        defer _ = linux.close(fd);
        var n: usize = 0;
        while (n < puffer.len) {
            const r = linux.read(fd, puffer[n..].ptr, puffer.len - n);
            if (linux.errno(r) != .SUCCESS or r == 0) break;
            n += r;
        }
        if (n == 0) continue;
        var a = ausText(puffer[0..n]);
        a.quelle = pfad;
        return a;
    }
    return .{};
}

/// inotify auf den Ordner (nicht auf die Datei: sie wird per rename ersetzt).
/// null, wenn es den Ordner nicht gibt (älteres Saalburg) – dann gilt laden() beim Start.
pub fn beobachten() ?i32 {
    const fd_roh = linux.inotify_init1(linux.IN.NONBLOCK | linux.IN.CLOEXEC);
    if (linux.errno(fd_roh) != .SUCCESS) return null;
    const fd: i32 = @intCast(fd_roh);
    const wd = linux.inotify_add_watch(fd, ORDNER, linux.IN.MOVED_TO | linux.IN.CLOSE_WRITE);
    if (linux.errno(wd) != .SUCCESS) {
        _ = linux.close(fd);
        return null;
    }
    return fd;
}

/// Ereignisse lesen (fd ist nicht blockierend); true, wenn saalburg.conf neu ist
pub fn geaendert(fd: i32) bool {
    var puffer: [1024]u8 align(@alignOf(linux.inotify_event)) = undefined;
    var neu = false;
    while (true) {
        const n = linux.read(fd, &puffer, puffer.len);
        if (linux.errno(n) != .SUCCESS or n == 0) break;
        var pos: usize = 0;
        while (pos + @sizeOf(linux.inotify_event) <= n) {
            const e: *const linux.inotify_event = @ptrCast(@alignCast(&puffer[pos]));
            const name_roh = puffer[pos + @sizeOf(linux.inotify_event) ..][0..e.len];
            if (std.mem.eql(u8, std.mem.sliceTo(name_roh, 0), "saalburg.conf")) neu = true;
            pos += @sizeOf(linux.inotify_event) + e.len;
        }
    }
    return neu;
}

/// Farbe als RGBA-Bytes, z. B. für OpenGL (a = 255)
pub fn rgba(farbe: u32) [4]u8 {
    return .{ @truncate(farbe >> 16), @truncate(farbe >> 8), @truncate(farbe), 255 };
}

test "auswerten, Ausweichwerte, Unbekanntes überspringen" {
    const a = ausText(
        \\# Kommentar
        \\format = 1
        \\schrift_text = Open Sans
        \\zeilenhoehe = 24
        \\skalierung = 0.85
        \\abstand = 6
        \\grund = #101010
        \\neu_in_format_2 = #123456
        \\akzent = kaputt
    );
    try std.testing.expectEqual(@as(u32, 0x101010), a.farben.grund);
    try std.testing.expectEqual(@as(u32, 0x7aa2f7), a.farben.akzent);
    try std.testing.expectEqualStrings("Open Sans", a.schrift_text.t());
    try std.testing.expectEqual(@as(u32, 24), a.zeilenhoehe);
    try std.testing.expectEqual(@as(u32, 85), a.skalierung_prozent);
    try std.testing.expectEqual(@as(u32, 6), a.abstand);
    try std.testing.expectEqual(@as(u32, 10), a.rundung);
    try std.testing.expectEqual(@as(u32, 100), ausText("skalierung = 1.00").skalierung_prozent);
    try std.testing.expectEqual(@as(u32, 120), ausText("skalierung = 1.2").skalierung_prozent);
    _ = laden(); // ohne Saalburg: Ausweichwerte
    if (beobachten()) |fd| {
        _ = geaendert(fd);
        _ = linux.close(fd);
    }
    try std.testing.expectEqual([4]u8{ 0x7a, 0xa2, 0xf7, 255 }, rgba(0x7aa2f7));
}
