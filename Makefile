#############################################################################
# Makefile for building: custard
#############################################################################

####### Install

all: install_doinstall

install_doinstall:
	sh install.sh

install: install_doinstall
