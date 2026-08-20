/* wb-power-helper.c — minimaler SUID-root-Helfer NUR fürs Auslesen des
 * CPU-Package-Watt-Verbrauchs über RAPL (/sys/class/powercap/intel-rapl/
 * intel-rapl:0/energy_uj).
 *
 * WARUM DAS ÜBERHAUPT ALS SUID-BINARY LAUFEN MUSS:
 * Seit Linux 5.10 ist energy_uj wegen der PLATYPUS-Sicherheitslücke
 * (CVE-2020-8694/8695/12912 - Energiemessung als Seitenkanal gegen
 * AES-NI/KASLR) grundsätzlich nur noch für root lesbar. Eine udev-Regel
 * hilft hier NICHT zuverlässig (der Pfad ist ein Symlink, keine
 * geeignete Device-Node-Struktur für OWNER/GROUP/MODE). Der
 * AMD-spezifische "amd_energy"-Treiber, der das früher für Ryzen ohne
 * root ermöglicht hätte, wurde vom Kernel-Maintainer selbst wieder
 * entfernt ("for all practical purposes unusable"). btop löst exakt
 * dasselbe Problem identisch: "sudo make setuid" installiert btop
 * selbst mit SUID-root. Dieser Helfer hier macht dasselbe, aber
 * beschränkt auf GENAU EINE, eng begrenzte Aufgabe - der restliche
 * wb-daemon läuft weiterhin komplett als normaler User.
 *
 * SICHERHEITSDESIGN (wichtig für ein SUID-root-Binary):
 *   - Feste, einkompilierte Pfade - NIE ein Pfad/Argument vom Aufrufer
 *   - Keine Kommandozeilen-Argumente werden ausgewertet
 *   - Kein system()/exec()/popen() - nur open()/read()
 *   - Droppt Privilegien NICHT extra, weil nur zwei read()-Aufrufe auf
 *     feste sysfs-Pfade passieren, sonst nichts - kein Angriffsfläche
 *     für Argument-Injection, da keine Argumente existieren
 *   - Gibt NUR eine einzelne Fließkommazahl (Watt) auf stdout aus,
 *     sonst nichts - minimale Angriffsfläche für den aufrufenden Python-
 *     Code beim Parsen der Ausgabe
 *
 * MESSPRINZIP:
 * RAPL liefert einen monoton steigenden Energiezähler in Mikrojoule
 * (energy_uj), keinen direkten Watt-Wert. Watt = Energie-Differenz /
 * Zeit-Differenz zwischen zwei Messungen. SAMPLE_MS bestimmt das
 * Zeitfenster - 200ms ist ein guter Kompromiss zwischen Genauigkeit
 * (zu kurz -> Rauschen durch Zähler-Granularität) und Reaktions-
 * geschwindigkeit (zu lang -> Helper braucht spürbar lange).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>

#define RAPL_PATH "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
#define SAMPLE_MS 200

static long read_energy_uj(void) {
    int fd = open(RAPL_PATH, O_RDONLY);
    if (fd < 0) return -1;
    char buf[64];
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;
    buf[n] = '\0';
    return strtol(buf, NULL, 10);
}

int main(void) {
    long e1 = read_energy_uj();
    if (e1 < 0) {
        /* Kein Fehlertext auf stdout - der Python-Aufrufer erkennt
         * einen fehlgeschlagenen Lesevorgang am leeren/nicht-
         * parsbaren stdout und behandelt das als "Watt nicht
         * verfügbar", statt eine Fehlermeldung als Zahl misszuverstehen. */
        return 1;
    }

    struct timespec ts = { .tv_sec = 0, .tv_nsec = SAMPLE_MS * 1000000L };
    nanosleep(&ts, NULL);

    long e2 = read_energy_uj();
    if (e2 < 0) return 1;

    /* RAPL-Zähler laufen bei Erreichen von max_energy_range_uj über
     * und beginnen wieder bei 0 - bei einem negativen Diff (Wraparound
     * während der kurzen Messpause) lieber "nicht verfügbar" melden
     * als eine falsche/negative Watt-Zahl auszugeben. Bei einem
     * 200ms-Fenster ist das extrem selten, aber ein Sicherheitsnetz
     * kostet hier nichts. */
    long diff_uj = e2 - e1;
    if (diff_uj < 0) return 1;

    double watts = (double)diff_uj / 1e6 / (SAMPLE_MS / 1000.0);
    printf("%.2f\n", watts);
    return 0;
}
