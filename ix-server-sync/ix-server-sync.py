#!/usr/local/bin/python
from __future__ import print_function
import os, sys
import json

debug = False
verbose = False

Projects = [ "FreeNAS", "TrueNAS" ]

Version = "1.0"
url_list = []

def CheckForUpdate():
    """
    Okay, this is a dubious function.
    Check the web server to see if a new version of ourself is available.
    We do this by trying to download the file.  If we can't, then no update
    is available.  If we do, then we compare, and attempt to overwrite the
    sys.argv[0] if they're different.  We should also probably try to confirm
    with the user before doing so.
    """
    script_name = os.path.basename(sys.argv[0])
    new_data = GetNetworkFile(script_name)
    if new_data:
        try:
            with open(sys.argv[0], "r") as f:
                old_data = f.read()
        except:
            if debug or verbose:
                print("Unable to open old version for comparison, no update possible")
            return

        if old_data != new_data:
            print("Update is available")
            try:
                pstr = "Perform update? (yes/NO) "
                if sys.version_info[0] > 2:
                    answer = input(pstr)
                else:
                    answer = raw_input(pstr)
                yesno = bool(answer.rstrip())
            except:
                yesno = False
            
            if yesno:
                with open(sys.argv[0], "w") as f:
                    f.write(new_data)
    return


def GetNetworkFile(path, out=None, resume=False):
    if out and resume:
        try:
            outfile = open(out, "r+b")
            nread = os.fstat(outfile.fileno()).st_size
            outfile.seek(nread)
            if debug or verbose:
                print("Continuing download of %s at %d bytes" % (path, nread), file=sys.stderr)
        except:
            nread = 0
            outfile = None
    else:
        nread = 0
        outfile = None
        
    if sys.version_info[0] < 3:
        from urllib2 import Request, urlopen, HTTPError
        from httplib import REQUESTED_RANGE_NOT_SATISFIABLE as HTTP_RANGE
    else:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from http.client import REQUESTED_RANGE_NOT_SATISFIABLE as HTTP_RANGE

    chunk_size = 1024 * 1024
    furl = None
    completed = False
    for base_url in url_list:
        try:
            req = Request(os.path.join(base_url, path))
            req.add_header("User-Agent", "ix-server-sync=%s" % Version)
            if nread:
                req.add_header("Range", "bytes=%d-" % nread)
            furl = urlopen(req, timeout=30)
        except HTTPError as error:
            if error.code == HTTP_RANGE:
                # This means we've reached the end of the file
                if resume:
                    completed = True
                break
            if debug or verbose:
                print("Got exception trying to fetch %s" % os.path.join(base_url, path), file=sys.stderr)
            continue
        except BaseException as e:
            print("Could not get URL %s" % os.path.join(base_url, path), file=sys.stderr)
        if furl or completed:
            break
    if completed:
        return None
    if not furl and not completed:
        raise

    if verbose:
        if out:
            print("Fetching %s -> %s" % (os.path.join(base_url, path), out), file=sys.stderr)
        else:
            print("Fetching %s" % (os.path.join(base_url, path)), file=sys.stderr)

    if out is None:
        retval = furl.read()
        return retval
    else:
        if outfile is None:
            outfile = open(out, "wb")
        try:
            while True:
                data = furl.read(chunk_size)
                nread += len(data)
                if not data:
                    break
                outfile.write(data)
        except:
            if not resume:
                os.remove(out)
            else:
                print("Unable to complete download of file %s" % path, file=sys.stderr)
            raise
        finally:
            if furl:
                furl.close()
            if outfile:
                outfile.close()
    return None

def GetTrains(trains_data):
    """
    Return a list of trains for the given project.
    """
    retval = []
    for train in trains_data.split("\n"):
        s = train.split("\t")
        if len(s) > 1:
            retval.append(s[0])

    return retval

def GetLatest(project, train):
    """
    Return the LATEST file for the given project/train.
    Note that this returns the contents of the file, so it
    can be written out.
    """
    try:
        latest_data = GetNetworkFile(os.path.join(project, train, "LATEST"))
    except BaseException as e:
        # If the trains.txt file is out of date, we can
        # get not-founds for this train.  So just log it and continue
        if debug or verbose:
            print("Got exception %s trying to get %s/%s/LATEST" % (str(e), project, train), file=sys.stderr)
        latest_data = None
    return latest_data

def IterateManifestComponents(manifest, deep=False):
    """
    Iterate through a manifest (as a dictionary), yielding the filenames related
    to it.
    """
    if manifest:
        train = manifest["Train"]
        if "Notes" in manifest:
            notes = manifest["Notes"]
            for note_file in notes.itervalues():
                yield os.path.join(train, "Notes", note_file)
        for checker in ["InstallCheckProrgam", "UpdateCheckProgram"]:
            if checker in manifest:
                update_check = manifest[checker]
                yield os.path.join("Validators", update_check["Name"])
        if "Packages" in manifest:
            pkgs = manifest["Packages"]
            for pkg in pkgs:
                yield "Packages/%s-%s.tgz" % (pkg["Name"], pkg["Version"])
                if deep and "Upgrades" in pkg:
                    for upgrade in pkg["Upgrades"]:
                        yield "Packages/%s-%s-%s.tgz" % (
                            pkg["Name"],
                            upgrade["Version"],
                            pkg["Version"])

def GetProject(project, destination, train=None, current_files=None, deep=False):
    """
    Get all of the LATEST for project.
    If train is set, then only get for that train
    """

    if train is None:
        train_data = GetNetworkFile(os.path.join(project, "trains.txt"))
        if destination:
            # trains.txt is small, and may change, so we always over-write it.
            try:
                os.makedirs(destination)
            except:
                pass
            with open(os.path.join(destination, "trains.txt"), "w") as f:
                f.write(train_data)
        trains = GetTrains(train_data)
    else:
        trains = train

    if current_files is None:
        curset = {}
    else:
        curset = current_files

    for t in trains:
        manifest_data = GetLatest(project, t)
        if not manifest_data:
            print("Could not get sane manifest for %s/%s" % (project, t), file=sys.stderr)
            continue
        try:
            manifest = json.loads(manifest_data)
        except BaseException as e:
            print("Could not load JSON from manifest %s/%s/LATEST: %s" % (project, t, str(e)), file=sys.stderr)
            continue
        for file in IterateManifestComponents(manifest, deep=deep):
            resumable = False
            if file.startswith("Packages/"):
                resumable = True
            if os.path.exists(os.path.join(destination, file)) and not resumable:
                if debug or verbose:
                    print("Not downloading %s because it already exists" % file, file=sys.stderr)
                try:
                    curset.pop(os.path.join(destination, file))
                except:
                    pass
            else:
                dirname = os.path.dirname(os.path.join(destination, file))
                try:
                    os.makedirs(dirname)
                except BaseException as e:
                    if debug:
                        print("Did not mkdir %s: %s" % (dirname, str(e)), file=sys.stderr)
                if debug:
                    print("Downloading SERVER/%s -> %s" % (os.path.join(project, file),
                                                           os.path.join(destination, file)),
                          file=sys.stderr)
                else:
                    GetNetworkFile(os.path.join(project, file),
                                   os.path.join(destination, file),
                                   resume = resumable
                                   )
                try:
                    curset.pop(os.path.join(destination, file))
                except:
                    pass

            # Need to save manifest as os.path.join(destination, t, "LATEST")
            try:
                os.makedirs(os.path.join(destination, t))
            except:
                pass
            with open(os.path.join(destination, t, "LATEST"), "w") as latest:
                latest.write(manifest_data)
            try:
                curset.pop(os.path.join(destination, t, "LATEST"))
            except:
                pass
            try:
                GetNetworkFile(os.path.join(project, t, "ChangeLog.txt"),
                               os.path.join(destination, t, "ChangeLog.txt"))
            except:
                pass
            
def LoadManifest(path):
    import json

    try:
        with open(path) as f:
            retval = json.load(f)
    except BaseException as e:
        print("Could not load manifest from %s: %s" % (path, str(e)), file=sys.stderr)
        return None
    return retval

def FindExistingFiles(archive, train=None, deep=False):
    """
    Find all of the files in the archive and train.
    If train is None, then it will look for trains.txt and use that
    to list the trains.  Note that trains.txt will be included in the file.
    Files are relative to archive.
    """
    retval = { }
    if train is None:
        print("archive = %s" % archive)
        try:
            train_data = open(os.path.join(archive, "trains.txt")).read()
            trains = GetTrains(train_data)
        except BaseException as e:
            # No trains.txt, so no files to look at
            if debug or verbose:
                print("Could not open trains.txt: %s" % str(e), file=sys.stderr)
            return {}
    else:
        trains = [train]

    for t in trains:
        # We only care about LATEST in each train
        man_path = os.path.join(archive, t, "LATEST")
        manifest = LoadManifest(man_path)
        if manifest:
            for file in IterateManifestComponents(manifest, deep=deep):
                if debug:
                    print("Found existing file %s" % os.path.join(archive, file), file=sys.stderr)
                retval[os.path.join(archive, file)] = True
        else:
            print("Hm, %s was not a manifest?" % man_path, file=sys.stderr)

    return retval

def main():
    import getopt
    global debug, verbose
    global url_list
    default_urls = ["http://update.freenas.org", "http://update-master.freenas.org"]

    def Usage():
        print("""Usage:\t{0} [-T train] [-P project] [--deep|--no-deep] [-U server_url] destination
or\t{0} [-U server_url] --check-for-update""".format(sys.argv[0]),
              file=sys.stderr)
        sys.exit(1)

    try:
        short_options = "T:P:dv"
        long_options = [ "train=",
                         "project=",
                         "debug",
                         "verbose",
                         "check-for-update",
                         "url=",
                         "deep",
                         "no-deep",
                         ]
        opts, arguments = getopt.getopt(sys.argv[1:], short_options, long_options)
    except getopt.GetoptError as err:
        print(str(err), file=sys.stderr)
        Usage()

    trains = []
    projects = []
    deep = False
    do_update = False

    for o, a in opts:
        if o in ("-T", "--train"):
            train.append(a)
        elif o in ("-P", "--project"):
            projects.append(a)
        elif o in ("-d", "--debug"):
            debug = True
        elif o in ("-v", "--verbose"):
            verbose = True
        elif o in ("--check-for-update"):
            do_update = True
        elif o in ("-U", "--url"):
            url_list.append(a)
        elif o in ("--deep"):
            deep = True
        elif o in ("--no-deep"):
            deep = False
        else:
            Usage()

    if not projects:
        projects = Projects

    if not trains:
        trains = None

    if not url_list:
        url_list = default_urls

    if do_update:
        CheckForUpdate()
        sys.exit(0)

    if len(arguments) == 1:
        destination = arguments[0]
    else:
        Usage()

    for project in projects:
        existing_files = None
        if destination:
            archive = os.path.join(destination, project)
            existing_files = FindExistingFiles(archive, trains, deep=deep)
        else:
            archive = None
        GetProject(project, archive, trains, current_files=existing_files, deep=deep)
        if destination and existing_files:
            for stale in existing_files.keys():
                if debug or verbose:
                    print("rm %s" % stale, file=sys.stderr)
                    if debug:
                        continue
                try:
                    os.remove(stale)
                except:
                    pass

if __name__ == "__main__":
    main()
    sys.exit(0)
