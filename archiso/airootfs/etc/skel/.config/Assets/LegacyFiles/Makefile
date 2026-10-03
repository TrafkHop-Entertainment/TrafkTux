CC = gcc
CFLAGS = -O3 $(shell pkg-config --cflags glib-2.0 json-glib-1.0 gio-2.0)
LDFLAGS = $(shell pkg-config --libs glib-2.0 json-glib-1.0 gio-2.0)

TARGET = RofiTrafkBubbleMenus
SRC = RofiTrafkBubbleMenus.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $< -o $@ $(LDFLAGS)

clean:
	rm -f $(TARGET)