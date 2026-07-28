.PHONY: all clean

CC = gcc
CFLAGS = -Wall -Wextra

all: program

program: main.o
	$(CC) $(CFLAGS) -o program main.o

main.o: main.c
	$(CC) $(CFLAGS) -c main.c

clean:
	rm -f *.o program
