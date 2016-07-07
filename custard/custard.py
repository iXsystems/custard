#!/usr/local/bin/python
from __future__ import print_function
import os, sys
import socket
import re
import subprocess
import json
import copy

"""
Caching Update Server Tsomething And Resource Deployment

The purpose of this script is to administer a FreeNAS caching server.
As such, it makes some assumptions about the system, mostly that it only
has one nic.

The network can either be configured via DHCP, or by setting an address,
netmask, router, and DNS server.  All four must be set in that case.  Setting
the network requires a reboot.

The hostname can be changed.  This also requires a reboot.  The system
also should be running mDNSResponder aka mdnsd, so it'll also respond to
that name .local.

The sync script can be run, or it can be updated.  The system can be
shut down or rebooted.
"""

debug = False
rcconf = "/etc/rc.conf"
resolvconf = "/etc/resolv.conf"
cache_dir = "/usr/local/www/nginx"
cache_tool = "/usr/local/bin/ix-server-sync.py"
# This is a json file
if debug:
    ConfigurationFile = "/tmp/custard.conf"
    rcconf = "/tmp/rc.conf"
    resolvconf = "/tmp/resolv.conf"
    cache_dir = "/tmp/nginx"
else:
    ConfigurationFile = "/usr/local/etc/custard.conf"

class Configuration(object):
    """
    A simple object for configuration.  We care about:
    url_list	-- a list of URLs to use, in order
    projects	-- a list of projects to use, in order
    deep	-- whether or not to do a deep copy
    verbose	-- whether or not to be verbose when syncing
    """
    URL_KEY = "URL"
    PROJECT_KEY = "Projects"
    DEEP_KEY = "FullCopy"
    TRAIN_KEY = "Trains"
    VERBOSE_KEY = "Verbose"
    default_urls = ["http://update.freenas.org", "http://update-master.freenas.org"]
    default_projects = ["FreeNAS", "TrueNAS" ]
    default_trains = []
    default_deep = True
    default_verbose = True
    
    def __init__(self, loadFrom=None):
        if loadFrom:
            self.Load(loadFrom)
        else:
            self.url_list = Configuration.default_urls
            self.projects = Configuration.default_projects
            self.trains = Configuration.default_trains
            self.deep = Configuration.default_deep
            self.verbose = Configuration.default_verbose
        
    def Save(self, fobj):
        """
        Save configuraetion into fobj.  fobj may be
        a file-like object or a pathname.
        """
        outfile = None
        if isinstance(fobj, str):
            outfile = open(fobj, "w")
        else:
            outfile = fobj
            
        tdict = {}
        if self.url_list:
            tdict[self.URL_KEY] = self.url_list
        if self.projects:
            tdict[self.PROJECT_KEY] = self.projects
        if self.trains:
            tdict[self.TRAIN_KEY] = self.trains
        tdict[self.DEEP_KEY] = self.deep
        tdict[self.VERBOSE_KEY] = self.verbose
        
        json.dump(tdict, outfile, sort_keys=True,
                  indent=4, separators=(',', ': '))

        if isinstance(fobj, str):
            outfile.close()
                            
    def Load(self, fobj):
        """
        Load configuration from fobj.  fobj may be
        a file-like object or a pathname.
        """
        
        infile = None
        if isinstance(fobj, str):
            try:
                infile = open(fobj, "r")
            except:
                infile = None
        else:
            infile = fobj

        try:
            tdict = json.load(infile)
        except:
            tdict = {}
                
        self.url_list = tdict.pop(Configuration.URL_KEY, Configuration.default_urls)
        self.projects = tdict.pop(Configuration.PROJECT_KEY, Configuration.default_projects)
        self.trains = tdict.pop(Configuration.TRAIN_KEY, Configuration.default_trains)
        self.deep = tdict.pop(Configuration.DEEP_KEY, Configuration.default_deep)
        self.verbose = tdict.pop(Configuration.VERBOSE_KEY, Configuration.default_verbose)
        
        if isinstance(fobj, str) and infile:
            infile.close()
            
    @property
    def url_list(self):
        return self._url_list
    @url_list.setter
    def url_list(self, urls):
        if isinstance(urls, list):
            self._url_list = urls[:]
        elif isinstance(urls, tuple):
            self._url_list = list(urls)
        elif isinstance(urls, str):
            self._url_list = [urls]
        else:
            raise ValueError("Invalid type for url list")

    @property
    def projects(self):
        return self._projects
    @projects.setter
    def projects(self, project_list):
        if isinstance(project_list, list):
            self._projects = project_list[:]
        elif isinstance(project_list, tuple):
            self._projects = list(project_list)
        elif isinstance(project_list, str):
            self._projects = [project_list]
        else:
            raise ValueError("Inappropriate object type for project list")

    @property
    def trains(self):
        if not self._trains:
            return []
        return self._trains
    @trains.setter
    def trains(self, train_list):
        if isinstance(train_list, list):
            self._trains = train_list[:]
        elif isinstance(train_list, tuple):
            self._trains = list(train_list)
        elif isinstance(train_list, str):
            self._train = [train_list]
        elif train_list is None:
            self._train = None
        else:
            raise ValueError("Inappropriate object type for train list")

    @property
    def deep(self):
        return self._deep
    @deep.setter
    def deep(self, full):
        self._deep = full

    @property
    def verbose(self):
        return self._verbose
    @verbose.setter
    def verbose(self, v):
        self._verbose = v
        
def Ask(prompt, default, use_boolean=False, show_default=True):
    """
    Ask for input from the user.  Checks for default, which
    is chosen for an empty input.  Raises EOFError if control-d
    was given (which usually means cancel by the callers, but they
    need to handle it).
    Format of the prompt is:  "${prompt} [${default}]: ".
    If use_boolean is true, then the default will be "yes/no", and
    will decide which one is capitalized (e.g., "YES/no").  It will
    also then convert the input from text to boolean.
    """

    def ToBool(s):
        if s.lower() in ("y", "yes", "t", "true"):
            return True
        elif s.lower() in ("n", "no", "f", "false"):
            return False
        else:
            raise ValueError("Invalid response")
        
    if sys.version_info[0] < 3:
        asker = raw_input
    else:
        asker = input

    if use_boolean:
        if default:
            default = "yes"
            default_prompt = "YES/no"
        else:
            default = "no"
            default_prompt = "yes/NO"
    else:
        if default is None:
            default_prompt = "NONE"
        else:
            default_prompt = default

    if show_default:
        p = "{0} [{1}]: "
    else:
        p = "{0}: "
    while True:
        response = asker(p.format(prompt, default_prompt)).rstrip()
        if response == "":
            response = default
        if use_boolean:
            try:
                return ToBool(response)
            except ValueError:
                print("Invalid response {0}, try again".format(response))
        else:
            return response
    
def ValidIPAddr(addr):
    """
    Returns a boolean indicating whether the input is a vaid ip address.
    This is a dead-simple RE check
    """
    import re
    result = re.match("^\d+\.\d+\.\d+\.\d+$", addr)
    if result is None:
        return False
    return True

def ParseNetwork(text):
    """
    Given input that may look like "1.2.3.4/12" or
    "1.2.3.4 mask 255.255.255.240" or "1.2.3.4 netmask 255.240.0.0"
    or "1.2.3.4 28", turn it into "1.2.34/24".  Raises ValueError
    if the input doesn't match any of those.
    """
    import re

    def ConvertNetmask(nm):
        """
        Convert something like 255.255.255.240 to a mask length
        """
        mask = None
        masklen = 0
        try:
            mask = int(nm, 0)
            if mask < 32:
                # Just a small integer
                return mask
        except:
            pass
        if not mask:
            fields = nm.split(".")
            if len(fields) != 4:
                raise ValueError("Invalid netmask %" % nm)
            state = 1
            mask = 0
            for f in fields:
                f = int(f)
                if state == 0 and f != 0:
                    raise ValueError("Invalid netmask")
                mask = (mask << 8) + f
                if f != 255:
                    state = 0
        mask = (mask & 0xffffffff)
        masklen = 32
        while (mask & 0x1) == 0:
            masklen -= 1
            mask = (mask >> 1) & 0xffffffff
        return masklen
        
    cidr = re.compile("^(\d+\.\d+\.\d+\.\d+)/(\d+)$")
    legacy_netmask = re.compile("^(\d+\.\d+\.\d+\.\d+)\s+(netmask|mask)\s+(\d+\.\d+\.\d+.\d+)$")
    legacy_hexmask = re.compile("^(\d+\.\d+\.\d+\.\d+)\s+(netmask|mask)\s+(0x[0-9a-fA-F]{8})$")
    simple_netmask = re.compile("^(\d+.\.\d+\.\d+\.\d+) (\d+)$")
    comb_netmask = re.compile("^(\d+\.\d+\.\d+\.\d+)\s+(mask|netmask)\s+(\d+)$")

    searches = [
        (cidr, [1, 2], False),
        (legacy_netmask, [1, 3], True),
        (simple_netmask, [1, 2], False),
        (legacy_hexmask, [1, 3], True),
        (comb_netmask, [1, 3], True),
        ]
    net = None
    mask = None

    for (regexp, nm, conv) in searches:
        result = regexp.match(text)
        if result:
            net = result.group(nm[0])
            mask = result.group(nm[1])
            if conv:
                mask = ConvertNetmask(mask)

            break
    if net and mask:
        return "%s/%s" % (net, mask)
    return None
        
def GetInterfaceName():
    """
    Get the interface name.
    Raise ValueError if there's more than one.
    """
    try:
        ifcs = subprocess.check_output(["/sbin/ifconfig", "-l"]).split()
        ifs = []
        for ifn in ifcs:
            if ifn.startswith("lo"):
                continue
            if ifn.startswith("tun"):
                continue
            ifs.append(ifn)
        if len(ifs) > 1:
            if debug:
                print("Incorrect number of interfaces, going with {0}".format(ifs[0]), file=sys.stderr)
                return ifs[0]
            else:
                raise ValueError("Incorrect number of interfaces")
        if len(ifs) == 0:
            raise ValueError("No interfaces found")
        return ifs[0]
    except BaseException as e:
        raise

def WriteConfiguration(conf):
    """
    Write out /etc/rc.conf, based on the config dictionary passed in.
    This is the output of ParseRC(), obviously.
    """
    import tempfile
    
    nics = conf.get("nics") or {}
        
    print("WriteConfiguration: rcconf = %s" % rcconf)
    try:
        tf = tempfile.NamedTemporaryFile(prefix=rcconf, delete=False)
        print("tmpfile = %s" % tf.name)
        if "content" in conf:
            for line in conf["content"]:
                tf.write(line + "\n")
        for nic in nics.keys():
            tf.write("ifconfig_%s=\"%s\"\n" % (nic, nics[nic]))
        if "resolver" in conf:
            try:
                resolver = conf["resolver"]
                tmp_resolv = None
                tmp_resolv = tempfile.NamedTemporaryFile(prefix=resolvconf, delete=False)
                if "search" in resolver:
                    print("search %s" % resolver["search"], file=tmp_resolv)
                if "nameserver" in resolver:
                    for server in resolver["nameserver"]:
                        print("nameserver %s" % server, file=tmp_resolv)
                if "domain" in resolver:
                    print("domain %s" % resolver["domain"], file=tmp_resolv)
                try:
                    os.rename(tmp_resolv.name, resolvconf)
                except BaseException as e:
                    print("Could not write " + resolvconf, file=sys.stderr)
                finally:
                    if tmp_resolv:
                        tmp_resolv.close
            except BaseException as e:
                print("Could not write new " + resolvconf, file=sys.stderr)
            
        for k in ["hostname", "defaultrouter"]:
            if k in conf:
                tf.write("%s=\"%s\"\n" % (k, conf[k]))
        os.rename(tf.name, rcconf)
        tf.close()
    except BaseException as e:
        print("Unable to write rc.conf")
        if tf:
            os.remove(tf.name)
            tf.close()

    return

def ParseRC():
    """
    Read /etc/rc.conf.  Returns a dictionary with
    contents being the lines, ifconfig being the nic configuration,
    and defaultrouter and hostname being the obvious.  Those lines are then
    removed from the contents.
    """
    rv = {}
    lines = []
    nics = {}
    nic_re = re.compile("^ifconfig_([^=]+)=\"?([^\"]*)\"?")
    try:
        rv["resolver"] = ParseResolveConf()
    except:
        pass
    try:
        with open(rcconf) as conf:
            for line in conf:
                line = line.rstrip()
                if nic_re.match(line):
                    parsed = nic_re.match(line)
                    nics[parsed.group(1)] = parsed.group(2)
                elif line.startswith("hostname="):
                    cfg = line.split("=")[1]
                    if cfg.startswith("\""):
                        cfg = cfg[1:-1]
                    rv["hostname"] = cfg
                elif line.startswith("defaultrouter="):
                    cfg = line.split("=")[1]
                    if cfg.startswith("\""):
                        cfg = cfg[1:-1]
                    rv["defaultrouter"] = cfg
                else:
                    lines.append(line)
    except BaseException as e:
        raise
    # Not part of rc.conf, but we look through the interfaces on the system as well
    try:
        ifcs = subprocess.check_output(["/sbin/ifconfig", "-l"]).split()
        for ifn in ifcs:
            if ifn.startswith("lo"):
                continue
            if ifn.startswith("tun"):
                continue
            if ifn not in nics:
                nics[ifn] = None
    except:
        pass
    
    if nics:
        rv["nics"] = nics
    rv["content"] = lines
    return rv
    
def ParseResolvConf():
    """
    Parsed /etc/resolv.conf
    Only cares about domain, search, and nameserver lines.
    Returns a dictionary with those, or raises an exception.
    """
    rv = {}
    try:
        with open(resolvconf) as res:
            for line in res:
                line = line.rstrip()
                if line.startswith("#"):
                    continue
                if line.startswith("search "):
                    rv["search"] = line[len("search "):]
                elif line.startswith("nameserver"):
                    addr = line.split()[1]
                    if "nameserver" not in rv:
                        rv["nameserver"] = []
                    rv["nameserver"].append(addr)
                elif line.startswith("domain "):
                    rv["domain"] = line[len("domain "):]
    except BaseException as e:
        raise
    if not rv:
        raise ValueError("Invalid resolv.conf")
    return rv

def ConfigInterface(config):
    """
    Prompt to configure the network interface.
    If not using DHCP, also need to configure the router and dns.
    Returns True if a change was made, False otherwise
    To ask for network change:
    
    Enter new values (hit return for default):
    NIC Configuration [DHCP]: 
    if not DHCP:
	    validate input a bit
	    Router [current value if any]: 
	    DNS Servers [current values if any]: 
	    Domain [current value if any]:
    Hostname [current value]: 
    """
    ifname = config["nic"]
    current = config.get("ifconfig")

    if sys.version_info[0] < 3:
        asker = raw_input
    else:
        asker = input

    changes = False
    new_config = config.copy()
    # First ask whether or not to set the address via DHCP
    # Default answer is whether or not it already is
    print("Press enter for default answer; Control-D to exit with no changes.")
    
    dhcp = False
    try:
        if current == "DHCP":
            default = True
        else:
            default = False
        yesno = Ask("Use DHCP", default, use_boolean=True)

        if yesno:
            new_config["ifconfig"] = "DHCP"
            dhcp = True
            try:
                new_config.pop("resolver")
            except:
                pass
        else:
            # Need to ask about address, netmask, and resolver information
            new_if = Ask("""Enter IP address in one of the following formats:
            1.2.3.4/24
            1.2.3.4 24
            1.2.3.4 netmask 24
            1.2.3.4 netmask 255.255.255.0
            1.2.3.4 netmask 0xffffff00
            DHCP
            IP address""", current)
            # Need to validate input
            if new_if != current:
                try:
                    if new_if == "DHCP":
                        new_config["ifconfig"] = "DHCP"
                        dhcp = True
                    else:
                        new_config["ifconfig"] = ParseNetwork(new_if)
                except ValueError as e:
                    print("Invalid IP address format")
                    raise
            if not dhcp:
                # Now need to get the router
                if "defaultrouter" in new_config:
                    current = new_config["defaultrouter"]
                else:
                    current = None
                new_router = Ask("Enter default router address", current)
                if new_router != None:
                    new_config["defaultrouter"] = new_router
                # Now need to get DNS server
                if "resolver" in config:
                    resolver = config["resolver"]
                    if "nameserver" in resolver:
                        current = ", ".join(map(str, resolver["nameserver"]))
                    else:
                        current = None
                else:
                    current = None
                new_dns = Ask("Enter DNS Server", current)
                # Do some validation on the input
                if new_dns != None:
                    # It could be a comma-space separated list
                    for addr in new_dns.split(", "):
                        if ValidIPAddr(addr) is False:
                            print("Invalid IP address for DNS")
                            raise ValueError("Invalid IP address")
                    new_config["resolver"] = {}
                    new_config["resolver"]["nameserver"] = new_dns.split(", ")
            
    except EOFError:
        print("\nNo changes made")
        return config
    
    print("Interface: %s" % GetInterfaceName())
    return new_config

def RunCacheTool(arg):
    config = Configuration(ConfigurationFile)
    
    ctool = [cache_tool]
    for url in config.url_list:
        ctool.extend(["--url", url])
    for project in config.projects:
        ctool.extend(["--project", project])
    for train in config.trains:
        ctool.extend(["--train", train])
    if config.deep:
        ctool.append("--deep")
    else:
        ctool.append("--no-deep")
    if config.verbose:
        ctool.append("--verbose")
        
    if arg:
        ctool.append(arg)
        
    if debug:
        print(ctool, file=sys.stderr)
        
    import subprocess
    try:
        subprocess.check_call(ctool)
    except:
        pass

def Reboot(how):
    import subprocess
    if debug:
        print("splaaaaaaaaaaaaaaat", file=sys.stderr)
        return
    shutdown = ["/sbin/shutdown"]
    if how == "reboot":
        shutdown.append("-r")
    elif how == "shutdown":
        shutdown.append("-p")
    shutdown.append("now")
    try:
        subprocess.check_call(shutdown)
    except:
        print("Shutdown failed")
        
def ConfigInterface(ifconfig):
    """
    Prompt to configure the given network interface.
    Caller must determine if DHCP is being used, to configure
    DNS and a default router.
    Returns the new interface configuration.

    To ask for network change:
    
    Enter new values (hit return for default):
    NIC Configuration [DHCP]: 
    if not DHCP:
	    validate input a bit
    """
    if sys.version_info[0] < 3:
        asker = raw_input
    else:
        asker = input

    orig = ifconfig
    # First ask whether or not to set the address via DHCP
    # Default answer is whether or not it already is
    print("Press enter for default answer; Control-D to exit with no changes.")
    
    dhcp = False
    try:
        if ifconfig == "DHCP":
            default = True
        else:
            default = False
        yesno = Ask("Use DHCP", default, use_boolean=True)

        if yesno:
            ifconfig = "DHCP"
        else:
            # Need to ask about address, netmask, and resolver information
            new_if = Ask("""Enter IP address in one of the following formats:
            1.2.3.4/24
            1.2.3.4 24
            1.2.3.4 netmask 24
            1.2.3.4 netmask 255.255.255.0
            1.2.3.4 netmask 0xffffff00
            DHCP
            IP address""", ifconfig)
            # Need to validate input
            if new_if != ifconfig:
                try:
                    if new_if == "DHCP":
                        ifconfig = "DHCP"
                    else:
                        ifconfig = ParseNetwork(new_if)
                except ValueError as e:
                    print("Invalid IP address format")
                    raise
            
    except EOFError:
        print("\nNo changes made")
        return orig
    
    return ifconfig

def DoConfigInterface(old_config):
    new_config = copy.deepcopy(old_config)
    
    nics = new_config.get("nics") or {}

    use_dhcp = False
    for iface in nics.keys():
        if Ask("Enable interface {0}".format(iface), nics[iface] is not None, use_boolean=True):
            new_ifconfig = ConfigInterface(nics[iface])
            if new_ifconfig == "DHCP":
                use_dhcp = True
            if new_ifconfig != nics[iface]:
                print("%s changed %s -> %s" % (iface, nics[iface], new_ifconfig))
                nics[iface] = new_ifconfig
        else:
            nics[iface] = None
        print("{0}=\"{1}\"".format(iface, nics[iface]), file=sys.stderr)
    
    if use_dhcp is True:
        new_config.pop("resolver", None)
        new_config.pop("defaultrouter", None)
    else:    
        new_router = Ask("Enter default router address", new_config.get("defaultrouter"))
        if new_router != new_config.get("defaultrouter"):
            new_config["defaultrouter"] = new_router
        resolver = new_config.get("resolver")
        current_resolver = None
        if resolver:
            current_resolver = resolver.get("nameserver")
        if current_resolver:
            current_resolver = ", ".join(map(str, current_resolver))
        new_resolver = Ask("Enter DNS Server", current_resolver)
        if new_resolver:
            for addr in new_resolver.split(", "):
                if ValidIPAddr(addr) is False:
                    print("Invalid IP address for DNS {0}".format(addr), file=sys.stderr)
                    raise ValueError("Invalid IP address {0}".format(addr))
            new_config["resolver"] = {}
            new_config["resolver"]["nameserver"] = new_resolver.split(", ")

    if new_config != old_config:
        try:
            yesno = Ask("Confirm reboot (changes will not be written unless reboot is confirmed", False, use_boolean=True)
            if yesno:
                print("*** WRITING CONFIGURATION ***")
                WriteConfiguration(new_config)
                Reboot("reboot")
        except:
            pass
    return

def RunShell(arg):
    return os.system("/usr/bin/su -l root")

def SetHostname(config):
    """
    Change the hostname
    """
    try:
        old_hostname = config["hostname"]
    except:
        old_hostname = None
    try:
        answer = Ask("Enter hostname", old_hostname)
        if answer and answer != old_hostname:
            config["hostname"] = answer
            WriteConfiguration(conf)
            Reboot("reboot")
    except:
        pass
        
def ConfigureCacheTool(unsued=None):
    """
    Configure the cache tool.
    We can set the following things:
    1) URL list
    2) Projects (FreeNAS and/or TrueNAS)
    3) Full copy (deep)
    4) Verbose
    """
    config = Configuration(ConfigurationFile)
    try:
        new_projects = Ask("Projects to cache", ", ".join(config.projects))
        for project in new_projects.split(", "):
            if project not in ("FreeNAS", "TrueNAS"):
                print("{0} is not a valid project -- must be TrueNAS and/or FreeNAS".format(project),
                      file=sys.stderr)
                return
        config.projects = new_projects.split(", ")
        
        new_urls = Ask("URL for update server", ", ".join(config.url_list))
        url_list = []
        for url in new_urls.split(", "):
            url_list.append(url)
        if url_list:
            config.url_list = url_list

        config.deep = Ask("Perform full copy", config.deep, use_boolean=True)
        config.verbose = Ask("Verbose copy", config.verbose, use_boolean=True)
    except EOFError:
        print("\nNo changes made")
        return

    try:
        config.Save(ConfigurationFile)
    except BaseException as e:
        print("Unable to save configuration file: {0}".format(str(e)), file=sys.stderr)
    return

def main():
    """
    Present the menu, and handle all the operations
    """
    system_config = ParseRC()
    
    menu_items = [
        ("Configure Networking", DoConfigInterface, system_config),
        ("Set hostname", SetHostname, system_config),
        ("Update cache", RunCacheTool, cache_dir),
        ("Check for cache-tool update", RunCacheTool, "--check-for-update"),
        ("Configure cache tool settings", ConfigureCacheTool, None),
        ("Shell", RunShell, None),
        ("Reboot", Reboot, "reboot"),
        ("Shutdown", Reboot, "shutdown"),
        ("Exit", sys.exit, 0),
        ]
    
    while True:
        count = 0
        for item in menu_items:
            print("%d) %s" % (count, item[0]))
            count = count + 1
            
        if "hostname" in system_config:
            print("System name {0}s (http://{0}.local/)".format(system_config["hostname"]))
        if "ifconfig" in system_config and system_config["ifconfig"] != "DHCP":
            print("Interface {0} {1}".format(system_config["nic"], system_config["ifconfig"]))
        try:
            selection = Ask("Enter item", None, show_default=False)
            x = menu_items[int(selection)]
            x[1](x[2])
        except SystemExit:
            raise
        except BaseException as e:
            print("exception %s" % str(e))

if __name__ == "__main__":
    main()
