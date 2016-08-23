#!/bin/sh

# Scary warning to stop somebody who maybe typed 'make install' on
# their desktop / server, not knowing what it does
echo "This will prepare a fresh FreeBSD VM to become a custard image..."
echo "If you've installed this by mistake, hit ctrl-c to cancel now."
echo ""
echo "Will install in 10 seconds..."
read -t 10 tmp

# List of packages
PKGLIST="lang/python27 net/mDNSResponder www/nginx emulators/open-vm-tools-nox11"

# Install our files
install -m 644 files/ttys /etc/ttys
install -m 644 files/gettytab /etc/gettytab
install -m 755 files/custard.sh /etc/custard.sh
install -m 755 ix-server-sync/ix-server-sync.py /usr/local/bin/
install -m 755 custard/custard.py /usr/local/bin/
install -m 644 files/rc.conf /etc/rc.conf

# Prep the VM with packages we need
for i in $PKGLIST
do
  pkg info -e ${i}
  if [ $? -eq 0 ] ; then continue ; fi
  
  echo "Installing: $i"
  pkg install -y $i
  if [ $? -ne 0 ] ; then
    echo "Failed installing: $i"
    exit 1
  fi
done

exit 0
