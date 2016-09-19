#!/bin/sh

rc_halt()
{
  echo "Running: $@"
  ${@}
  if [ $? -ne 0 ] ; then
    echo "Failed running: $@"
    exit 1
  fi
}

# Scary warning to stop somebody who maybe typed 'make install' on
# their desktop / server, not knowing what it does
echo "This will prepare a fresh FreeBSD VM to become a custard image..."
echo "If you've installed this by mistake, hit ctrl-c to cancel now."
echo ""
echo "Will install in 10 seconds..."
read -t 10 tmp

# List of packages
PKGLIST="lang/python2 lang/python27 net/mDNSResponder www/nginx emulators/open-vm-tools-nox11 tmux"

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

# Install our files
rc_halt "install -m 644 files/ttys /etc/ttys"
rc_halt "install -m 644 files/gettytab /etc/gettytab"
rc_halt "install -m 644 files/crontab /etc/crontab"
rc_halt "install -m 755 files/custard.sh /etc/custard.sh"
rc_halt "install -m 755 ix-server-sync/ix-server-sync.py /usr/local/bin/ix-server-sync.py"
rc_halt "install -m 755 custard/custard.py /usr/local/bin/custard.py"
rc_halt "install -m 644 files/rc.conf /etc/rc.conf"

# Make sure /usr/local/bin/python exists
if [ ! -e "/usr/local/bin/python" ] ; then
  ln -s python2 /usr/local/bin/python
fi

# Cleanup resolv.conf for next boot
rm /etc/resolv.conf

exit 0
