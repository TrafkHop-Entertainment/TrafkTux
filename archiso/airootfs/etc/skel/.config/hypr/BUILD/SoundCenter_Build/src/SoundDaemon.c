/*
 * SoundDaemon.c — persistenter Systemsound-Daemon (Ersatz für die
 * pw-play/paplay-Aufrufkette in der alten soundctl.sh).
 *
 * Teil von SoundCenter. Gegenstück: SoundControl.c (der Client).
 *
 * WARUM ein Daemon:
 *
 * Die alte Kette war pro Sound: bash (soundctl.sh) -> [Master-Check: cat,
 * Event-Check: cat] -> setsid -> pw-play (frischer PipeWire-Client:
 * pw_context_connect + Format-Aushandlung + Stream-Verbindungsaufbau, JEDES
 * MAL neu). Dieser Daemon hält stattdessen EINEN einzigen PipeWire-Stream
 * für seine gesamte Lebensdauer offen (kein Neuverbinden pro Sound) und
 * hält ihn PERMANENT aktiv (node.always-process=true, siehe unten) - er
 * "treibt" also durchgehend, auch wenn gerade nichts zu hören ist.
 *
 * WICHTIGER HINWEIS zur eigentlichen Ursache der ursprünglich gemeldeten
 * Verzögerung: die naheliegende Theorie (WirePlumber suspendiert die
 * Senke nach Inaktivität, ein neuer Prozess trifft auf eine schlafende
 * Senke) wurde inzwischen widerlegt - auch ein kalter Erstaufruf im
 * Terminal war nie langsam. Dieser Daemon eliminiert trotzdem JEDEN
 * Kostenpunkt, der im Sound-Dispatch selbst liegen könnte (Prozess-Spawns,
 * PipeWire-Neuverhandlung, Senken-Aufwachen) - schadet also nicht, ist
 * aber laut aktuellem Kenntnisstand vermutlich nicht (mehr) die alleinige
 * Erklärung. Falls nach dem Umstieg im echten Betrieb weiterhin eine
 * Verzögerung wahrnehmbar ist, liegt sie höchstwahrscheinlich VOR dem
 * jeweiligen Hyprland-Hook (Compositor-intern, z.B. Layout/Animation vor
 * "window.open_early") - siehe README.md, Abschnitt "Wenn's nach dem
 * Umstieg immer noch hakt".
 *
 * Alle bekannten .ogg-Dateien werden beim Start (bzw. bei SIGHUP) EINMAL per
 * libvorbisfile zu Float32-PCM dekodiert und im RAM gehalten. Ein
 * "Play"-Request kostet danach nur noch: Socket-Read + Statusdatei-Check
 * + Zeiger in ein freies "Voice"-Slot schreiben. Kein fork(), kein
 * exec(), keine PipeWire-Neuverhandlung.
 *
 * Architektur: BEWUSST single-threaded. Der Socket-Reader (via
 * pw_loop_add_io) und der Audio-process()-Callback laufen beide auf
 * DERSELBEN pw_main_loop-Loop (kein PW_STREAM_FLAG_RT_PROCESS gesetzt).
 * Dadurch teilen sich beide Callbacks den Voice-Array ohne jede
 * Locking-Notwendigkeit.
 *
 * Installation: KEIN fester Pfad vorausgesetzt. Wohin das kompilierte
 * Binary "SoundDaemon" kopiert wird, ist komplett dir überlassen - einzige
 * Voraussetzung: es muss über $PATH auffindbar sein (siehe
 * SoundControl.c, das den Daemon bei Bedarf per execlp("SoundDaemon", ...)
 * nachstartet, und SoundCenter.service, das ihn per bloßem Namen startet).
 *
 * Build: siehe Makefile (braucht libpipewire-0.3-dev + libvorbis-dev,
 * bzw. auf Arch: pipewire + libvorbis).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <dirent.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <limits.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>

#include <vorbis/vorbisfile.h>

#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/utils/defs.h>

#define SAMPLE_RATE   48000u
#define CHANNELS      2u
#define MAX_VOICES    16
#define NUM_EVENTS    13
#define MAX_LINE      256

/* Event-Namen: Englisch, PascalCase, keine "-"/"_"/Anführungszeichen (so
 * gewünscht). Erwartete Dateien in g_sound_dir: <EventName>.ogg exakt
 * gleich geschrieben (z.B. "RightClick.ogg", Groß/Kleinschreibung zählt
 * auf den meisten Dateisystemen).
 *
 * Zuordnung/Entscheidungen beim Übertragen der Wunschliste hierher:
 *  - Click/RightClick/MiddleClick/Open/Close/Pip/Autohide/LayoutSwitch/
 *    Dunst/Error: 1:1 wie gewünscht.
 *  - FocusChange: deckt sowohl "fokuswechsel" als auch das explizit
 *    gleichgesetzte "widgets-wechsel" ab (dieselbe Datei, ein Event) -
 *    UND ersetzt das alte "nav" (Workspace-/Fensterfokus-Wechsel in
 *    hyprland.lua sowie Rofi-Menü-Navigation in RofiTrafkBubbleMenus.c
 *    liefen bisher beide unter "nav"; bis auf Weiteres bleibt das so,
 *    jetzt eben unter dem neuen Namen).
 *  - Dunst: ersetzt das alte "notify" (gleiches Konzept, neuer Name) -
 *    "Gerät verbunden/getrennt" bekommen laut Wunsch KEIN eigenes Event,
 *    sondern laufen "via dunst", spielen also einfach mit ab, sobald
 *    dunstrc mal einen Script-Hook auf Dunst bekommt (aktuell noch nicht
 *    der Fall, siehe README).
 *  - Toggle, Enter: nicht in der neuen Liste genannt, aber bewusst
 *    BEIBEHALTEN (nur PascalCase-umbenannt) statt stillschweigend
 *    entfernt - Toggle wird aktuell noch von keinem der spezifischeren
 *    Events (Pip/Autohide) abgelöst, weil die zugehörigen Skripte das
 *    noch nicht selbst aufrufen (siehe README, "einzeln einbauen"), und
 *    Enter hängt schon aktiv an RofiTrafkBubbleMenus.c (Menü-Bestätigen).
 *    Sag Bescheid, falls die beiden weg sollen. */
static const char *EVENT_NAMES[NUM_EVENTS] = {
    "Click", "RightClick", "MiddleClick",
    "Open", "Close", "FocusChange",
    "Pip", "Autohide", "LayoutSwitch", "Dunst",
    "Error", "Toggle", "Enter"
};

typedef struct {
    float    *samples;     /* interleaved stereo float32, NULL = nicht geladen */
    uint32_t  num_frames;  /* Frames (nicht Samples - Samples = frames*CHANNELS) */
} SoundBuffer;

typedef struct {
    const SoundBuffer *buf; /* NULL = Slot frei */
    uint32_t pos;           /* aktuelle Position in Frames */
} Voice;

static SoundBuffer g_sounds[NUM_EVENTS];
static Voice       g_voices[MAX_VOICES];
static char        g_home[PATH_MAX];
static char        g_sound_dir[PATH_MAX];
static char        g_sock_path[PATH_MAX];

struct daemon_data {
    struct pw_main_loop *loop;
    struct pw_stream    *stream;
    struct spa_hook       stream_listener;
    int                    sock_fd;
    struct spa_source     *sock_source;
    struct spa_source     *sighup_source;
    struct spa_source     *sigterm_source;
    struct spa_source     *sigint_source;
};

/* ------------------------- Statusdateien (Enable/Disable) ------------------------ */
/*
 * Bewusst IDENTISCHES Format/Speicherort wie im alten soundctl.sh:
 * ~/.cache/hypr/sounds_enabled + ~/.cache/hypr/sound_events/<event>.
 * SoundControl (der Client) macht Enable/Disable/Toggle/Status direkt auf
 * denselben Dateien, ohne den Daemon zu involvieren - beide teilen sich
 * hier einfach dieselbe Quelle der Wahrheit.
 *
 * Semantik (wie bisher): Datei fehlt -> an (Default). Datei existiert ->
 * an genau dann, wenn ihr (getrimmter) Inhalt exakt "1" ist.
 */
static int flag_enabled(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return 1; /* fehlt -> Default an */
    char buf[16] = {0};
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r' || buf[n-1] == ' '))
        buf[--n] = '\0';
    return strcmp(buf, "1") == 0;
}

static int sounds_master_enabled(void) {
    char p[PATH_MAX];
    snprintf(p, sizeof(p), "%s/.cache/hypr/sounds_enabled", g_home);
    return flag_enabled(p);
}

static int sound_event_enabled(const char *event) {
    char p[PATH_MAX];
    snprintf(p, sizeof(p), "%s/.cache/hypr/sound_events/%s", g_home, event);
    return flag_enabled(p);
}

/* ------------------------------- Ogg->PCM laden ------------------------------- */

/* Simpler linearer Resampler - nur als Absicherung falls mal eine .ogg-Datei
 * mit einer anderen Rate als 48kHz reinrutscht (die ursprünglichen 8
 * mitgelieferten Dateien bereits 48kHz Stereo). */
static void resample_linear(const float *in, uint32_t in_frames, long in_rate,
                             float **out, uint32_t *out_frames, long out_rate) {
    double ratio = (double)out_rate / (double)in_rate;
    uint32_t n = (uint32_t)((double)in_frames * ratio);
    float *buf = malloc((size_t)n * CHANNELS * sizeof(float));
    for (uint32_t i = 0; i < n; i++) {
        double src_pos = (double)i / ratio;
        uint32_t i0 = (uint32_t)src_pos;
        uint32_t i1 = (i0 + 1 < in_frames) ? i0 + 1 : i0;
        double frac = src_pos - (double)i0;
        for (uint32_t c = 0; c < CHANNELS; c++) {
            float s0 = in[(size_t)i0 * CHANNELS + c];
            float s1 = in[(size_t)i1 * CHANNELS + c];
            buf[(size_t)i * CHANNELS + c] = (float)(s0 + (s1 - s0) * frac);
        }
    }
    *out = buf;
    *out_frames = n;
}

/* Dekodiert eine .ogg-Datei komplett zu interleaved Float32-Stereo-PCM bei
 * SAMPLE_RATE. 0 bei Erfolg, <0 bei Fehler (bewusst NICHT fatal fürs
 * Gesamtprogramm - siehe load_all_sounds). */
static int load_ogg(const char *path, SoundBuffer *out) {
    OggVorbis_File vf;
    if (ov_fopen(path, &vf) < 0)
        return -1;

    vorbis_info *vi = ov_info(&vf, -1);
    if (!vi) { ov_clear(&vf); return -1; }
    int  src_channels = vi->channels;
    long src_rate     = vi->rate;

    size_t   cap   = 65536;
    uint32_t count = 0;
    float *buf = malloc(cap * CHANNELS * sizeof(float));

    for (;;) {
        float **pcm;
        int section;
        long ret = ov_read_float(&vf, &pcm, 4096, &section);
        if (ret <= 0) break;

        if ((size_t)count + (size_t)ret > cap) {
            cap = ((size_t)count + (size_t)ret) * 2;
            float *nb = realloc(buf, cap * CHANNELS * sizeof(float));
            if (!nb) { free(buf); ov_clear(&vf); return -1; }
            buf = nb;
        }
        for (long i = 0; i < ret; i++) {
            for (uint32_t c = 0; c < CHANNELS; c++) {
                float s;
                if (src_channels == 1)
                    s = pcm[0][i];
                else if ((int)c < src_channels)
                    s = pcm[c][i];
                else
                    s = pcm[src_channels - 1][i];
                buf[((size_t)count + (size_t)i) * CHANNELS + c] = s;
            }
        }
        count += (uint32_t)ret;
    }
    ov_clear(&vf);

    if (src_rate != (long)SAMPLE_RATE) {
        float *rbuf; uint32_t rcount;
        resample_linear(buf, count, src_rate, &rbuf, &rcount, (long)SAMPLE_RATE);
        free(buf);
        buf = rbuf;
        count = rcount;
    }

    out->samples    = buf;
    out->num_frames = count;
    return 0;
}

/* Sucht die tatsächliche Datei zu einem Event: erst der exakte erwartete
 * Name ("<Event>.ogg"), und WENN der nicht existiert, als Fallback ein
 * kompletter, case-insensitiver Scan von g_sound_dir. Grund: bei der
 * Umbenennungs-Geschwindigkeit in diesem Projekt (siehe z.B. "click.ogg"
 * vs. erwartetes "Click.ogg" - genau das ist real aufgetreten) ist ein
 * Case-Mismatch ein wiederkehrender, aber trivial vermeidbarer
 * Stolperstein. out_path muss mindestens PATH_MAX groß sein. Gibt 1
 * zurück, wenn irgendeine passende Datei gefunden wurde, sonst 0. */
static int resolve_sound_file(const char *event_name, char *out_path, size_t out_len) {
    char exact[PATH_MAX];
    snprintf(exact, sizeof(exact), "%s/%s.ogg", g_sound_dir, event_name);

    struct stat st;
    if (stat(exact, &st) == 0) {
        snprintf(out_path, out_len, "%s", exact);
        return 1;
    }

    char want[PATH_MAX];
    snprintf(want, sizeof(want), "%s.ogg", event_name);

    DIR *dir = opendir(g_sound_dir);
    if (!dir) return 0;

    struct dirent *entry;
    int found = 0;
    while ((entry = readdir(dir)) != NULL) {
        if (strcasecmp(entry->d_name, want) == 0) {
            snprintf(out_path, out_len, "%s/%s", g_sound_dir, entry->d_name);
            found = 1;
            break;
        }
    }
    closedir(dir);
    return found;
}

/* Lädt (bzw. bei Reload: ersetzt) alle bekannten Event-Sounds aus
 * g_sound_dir. Vor dem Freigeben alter Buffer werden alle Voices gestoppt,
 * die gerade auf sie zeigen. */
static void load_all_sounds(int is_reload) {
    for (int i = 0; i < NUM_EVENTS; i++) {
        char path[PATH_MAX];
        int have_path = resolve_sound_file(EVENT_NAMES[i], path, sizeof(path));

        SoundBuffer nb = {0};
        int rc = have_path ? load_ogg(path, &nb) : -1;

        if (is_reload) {
            for (int v = 0; v < MAX_VOICES; v++)
                if (g_voices[v].buf == &g_sounds[i])
                    g_voices[v].buf = NULL;
            free(g_sounds[i].samples);
        }

        if (rc == 0) {
            g_sounds[i] = nb;
            /* fprintf(stderr, ...) statt pw_log_info: PipeWires eigener
             * Log-Level filtert Info standardmäßig weg (nur Warn/Error
             * kommen ungefiltert im journal an) - fuer "hab ich das
             * überhaupt geladen" wollen wir das aber IMMER sehen. */
            fprintf(stderr, "SoundDaemon: '%s' geladen (%u frames, %s)\n",
                    EVENT_NAMES[i], nb.num_frames, path);
        } else {
            g_sounds[i].samples    = NULL;
            g_sounds[i].num_frames = 0;
            char expected[PATH_MAX];
            snprintf(expected, sizeof(expected), "%s/%s.ogg", g_sound_dir, EVENT_NAMES[i]);
            fprintf(stderr, "SoundDaemon: '%s' konnte nicht geladen werden "
                    "(erwartet: %s, auch case-insensitiv im Verzeichnis nichts "
                    "gefunden) - Event bleibt bis zum naechsten Reload stumm\n",
                    EVENT_NAMES[i], expected);
        }
    }
}

/* --------------------------------- Play-Logik --------------------------------- */

static void handle_play(const char *event) {
    int idx = -1;
    for (int i = 0; i < NUM_EVENTS; i++) {
        if (strcmp(EVENT_NAMES[i], event) == 0) { idx = i; break; }
    }
    if (idx < 0) {
        fprintf(stderr, "SoundDaemon: '%s' angefragt - unbekannter Event-Name "
                "(nicht in EVENT_NAMES[])\n", event);
        return;
    }
    if (g_sounds[idx].samples == NULL) {
        fprintf(stderr, "SoundDaemon: '%s' angefragt - keine Audiodatei geladen, "
                "bleibt stumm\n", EVENT_NAMES[idx]);
        return;
    }
    if (!sounds_master_enabled()) {
        fprintf(stderr, "SoundDaemon: '%s' angefragt - Sounds global deaktiviert "
                "(--status ohne Event zeigt das)\n", EVENT_NAMES[idx]);
        return;
    }
    if (!sound_event_enabled(EVENT_NAMES[idx])) {
        fprintf(stderr, "SoundDaemon: '%s' angefragt - für dieses Event deaktiviert\n",
                EVENT_NAMES[idx]);
        return;
    }

    for (int v = 0; v < MAX_VOICES; v++) {
        if (g_voices[v].buf == NULL) {
            g_voices[v].buf = &g_sounds[idx];
            g_voices[v].pos = 0;
            fprintf(stderr, "SoundDaemon: spiele '%s' (Voice-Slot %d, %u frames)\n",
                    EVENT_NAMES[idx], v, g_sounds[idx].num_frames);
            return;
        }
    }
    g_voices[0].buf = &g_sounds[idx];
    g_voices[0].pos = 0;
    fprintf(stderr, "SoundDaemon: spiele '%s' (alle Voice-Slots voll, kapere Slot 0)\n",
            EVENT_NAMES[idx]);
}

/* ------------------------------- Unix-Socket ------------------------------- */

static int setup_socket(const char *path) {
    unlink(path); /* Leiche von einem abgestürzten vorherigen Lauf entfernen */

    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) { perror("socket"); return -1; }

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(fd);
        return -1;
    }
    chmod(path, 0600); /* nur der eigene User (Multi-User-System!) */
    return fd;
}

static void on_socket_data(void *data_ptr, int fd, uint32_t mask) {
    (void)data_ptr;
    if (!(mask & SPA_IO_IN)) return;

    char msg[MAX_LINE];
    for (;;) {
        ssize_t n = recv(fd, msg, sizeof(msg) - 1, 0);
        if (n <= 0) break;
        msg[n] = '\0';

        if (strncmp(msg, "PLAY ", 5) == 0) {
            handle_play(msg + 5);
        }
    }
}

/* --------------------------------- PipeWire --------------------------------- */

static void on_process(void *userdata) {
    struct daemon_data *d = userdata;
    struct pw_buffer *b = pw_stream_dequeue_buffer(d->stream);
    if (!b) return;

    struct spa_buffer *buf = b->buffer;
    float *dst = buf->datas[0].data;
    if (!dst) { pw_stream_queue_buffer(d->stream, b); return; }

    uint32_t stride   = CHANNELS * sizeof(float);
    uint32_t n_frames = buf->datas[0].maxsize / stride;
    if (b->requested)
        n_frames = SPA_MIN(n_frames, (uint32_t)b->requested);

    memset(dst, 0, (size_t)n_frames * stride);

    for (int v = 0; v < MAX_VOICES; v++) {
        Voice *voice = &g_voices[v];
        if (!voice->buf) continue;

        if (voice->pos == 0) {
            /* Allererster Frame dieser Voice - genau HIER wird real
             * Sample-Material in den PipeWire-Puffer geschrieben. Wenn das
             * hier auftaucht, aber trotzdem nichts zu hoeren ist, liegt
             * das NICHT mehr an SoundDaemon, sondern an PipeWire/
             * WirePlumber-Routing bzw. Lautstaerke/Mute auf der Senke -
             * siehe README, Abschnitt Fehlersuche. */
            int idx = (int)(voice->buf - g_sounds);
            float peak = 0.0f;
            uint32_t check = voice->buf->num_frames < 100 ? voice->buf->num_frames : 100;
            for (uint32_t i = 0; i < check * CHANNELS; i++) {
                float a = voice->buf->samples[i] < 0 ? -voice->buf->samples[i] : voice->buf->samples[i];
                if (a > peak) peak = a;
            }
            fprintf(stderr, "SoundDaemon: mische '%s' in Ausgabepuffer (Peak erste %u "
                    "Frames: %.3f, insgesamt %u Frames)\n",
                    (idx >= 0 && idx < NUM_EVENTS) ? EVENT_NAMES[idx] : "?",
                    check, (double)peak, voice->buf->num_frames);
        }

        uint32_t remaining = voice->buf->num_frames - voice->pos;
        uint32_t n = (remaining < n_frames) ? remaining : n_frames;
        const float *src = voice->buf->samples + (size_t)voice->pos * CHANNELS;

        for (uint32_t i = 0; i < n * CHANNELS; i++)
            dst[i] += src[i];

        voice->pos += n;
        if (voice->pos >= voice->buf->num_frames)
            voice->buf = NULL;
    }

    for (uint32_t i = 0; i < n_frames * CHANNELS; i++) {
        if (dst[i] > 1.0f) dst[i] = 1.0f;
        else if (dst[i] < -1.0f) dst[i] = -1.0f;
    }

    buf->datas[0].chunk->offset = 0;
    buf->datas[0].chunk->stride = stride;
    buf->datas[0].chunk->size   = n_frames * stride;

    pw_stream_queue_buffer(d->stream, b);
}

/* Macht sichtbar, ob der Stream überhaupt bei "streaming" ankommt (=
 * erfolgreich mit einer Senke verlinkt) oder z.B. bei "connecting"
 * hängenbleibt/auf "error" geht - IMMER via stderr, nicht pw_log, aus
 * demselben Sichtbarkeits-Grund wie beim Laden der Sounds. Wenn hier
 * "streaming" nie auftaucht, liegt das Problem VOR unserem Code (PipeWire/
 * WirePlumber/Routing auf dem jeweiligen Rechner), nicht in SoundDaemon
 * selbst. */
static void on_stream_state_changed(void *userdata, enum pw_stream_state old,
                                     enum pw_stream_state state, const char *error) {
    (void)userdata; (void)old;
    fprintf(stderr, "SoundDaemon: Stream-Status -> %s%s%s\n",
            pw_stream_state_as_string(state),
            error ? " Fehler: " : "", error ? error : "");
}

static const struct pw_stream_events stream_events = {
    PW_VERSION_STREAM_EVENTS,
    .state_changed = on_stream_state_changed,
    .process = on_process,
};

/* ------------------------------- Signale ------------------------------- */

static void on_sighup(void *data_ptr, int signal_number) {
    (void)data_ptr; (void)signal_number;
    fprintf(stderr, "SoundDaemon: SIGHUP -> lade alle Sounds aus %s neu\n", g_sound_dir);
    load_all_sounds(1);
}

static void on_quit_signal(void *data_ptr, int signal_number) {
    (void)signal_number;
    struct daemon_data *d = data_ptr;
    fprintf(stderr, "SoundDaemon: Beende sauber (Socket wird aufgeräumt).\n");
    pw_main_loop_quit(d->loop);
}

/* --------------------------------- main() --------------------------------- */

int main(int argc, char *argv[]) {
    pw_init(&argc, &argv);

    const char *home = getenv("HOME");
    if (!home || !*home) { fprintf(stderr, "HOME nicht gesetzt\n"); return 1; }
    snprintf(g_home, sizeof(g_home), "%s", home);

    /* Sound-Verzeichnis: per Env überschreibbar, sonst
     * ~/.config/hypr/Sounds (passend zu deinem bereits vorhandenen Ordner -
     * bei dir laut deiner Struktur groß geschrieben, nicht mehr wie in der
     * alten soundctl.sh). */
    const char *sound_dir_env = getenv("SOUNDCENTER_SOUND_DIR");
    if (sound_dir_env && *sound_dir_env)
        snprintf(g_sound_dir, sizeof(g_sound_dir), "%s", sound_dir_env);
    else
        snprintf(g_sound_dir, sizeof(g_sound_dir), "%s/.config/hypr/Sounds", g_home);

    const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
    if (runtime_dir && *runtime_dir)
        snprintf(g_sock_path, sizeof(g_sock_path), "%s/SoundCenter.sock", runtime_dir);
    else
        snprintf(g_sock_path, sizeof(g_sock_path), "/tmp/SoundCenter-%d.sock", getuid());

    load_all_sounds(0);

    struct daemon_data d = {0};
    d.loop = pw_main_loop_new(NULL);
    struct pw_loop *loop = pw_main_loop_get_loop(d.loop);

    d.sock_fd = setup_socket(g_sock_path);
    if (d.sock_fd < 0) {
        fprintf(stderr, "SoundDaemon: konnte Socket %s nicht anlegen\n", g_sock_path);
        return 1;
    }
    d.sock_source = pw_loop_add_io(loop, d.sock_fd, SPA_IO_IN, false,
                                    on_socket_data, &d);

    d.sighup_source  = pw_loop_add_signal(loop, SIGHUP,  on_sighup, &d);
    d.sigterm_source = pw_loop_add_signal(loop, SIGTERM, on_quit_signal, &d);
    d.sigint_source  = pw_loop_add_signal(loop, SIGINT,  on_quit_signal, &d);

    struct pw_properties *props = pw_properties_new(
        PW_KEY_MEDIA_TYPE,        "Audio",
        PW_KEY_MEDIA_CATEGORY,    "Playback",
        PW_KEY_MEDIA_ROLE,        "event",
        PW_KEY_NODE_NAME,         "SoundDaemon",
        PW_KEY_NODE_DESCRIPTION,  "SoundCenter Systemsounds",
        PW_KEY_APP_NAME,          "SoundDaemon",
        PW_KEY_NODE_LATENCY,      "256/48000",
        PW_KEY_NODE_ALWAYS_PROCESS, "true",
        NULL);

    d.stream = pw_stream_new_simple(loop, "SoundDaemon", props,
                                     &stream_events, &d);

    uint8_t pod_buffer[1024];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(pod_buffer, sizeof(pod_buffer));
    struct spa_audio_info_raw info = {0};
    info.format   = SPA_AUDIO_FORMAT_F32;
    info.channels = CHANNELS;
    info.rate     = SAMPLE_RATE;
    const struct spa_pod *params[1];
    params[0] = spa_format_audio_raw_build(&b, SPA_PARAM_EnumFormat, &info);

    pw_stream_connect(d.stream, PW_DIRECTION_OUTPUT, PW_ID_ANY,
                       PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS,
                       params, 1);

    fprintf(stderr, "SoundDaemon: bereit. Socket=%s SoundDir=%s\n", g_sock_path, g_sound_dir);
    pw_main_loop_run(d.loop);

    pw_stream_destroy(d.stream);
    pw_main_loop_destroy(d.loop);
    close(d.sock_fd);
    unlink(g_sock_path);
    pw_deinit();
    return 0;
}
