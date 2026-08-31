APP := TrafkTuxBar

PKGS := gtk+-3.0 gtk-layer-shell-0 json-glib-1.0 gio-unix-2.0

CFLAGS += -std=gnu11 -Wall -Wextra -O2 $(shell pkg-config --cflags $(PKGS))
LDLIBS += -lm $(shell pkg-config --libs $(PKGS))

.PHONY: all clean

all: $(APP)

$(APP): $(APP).c
	$(CC) $(CFLAGS) $(APP).c -o $(APP) $(LDLIBS)

clean:
	rm -f $(APP)
