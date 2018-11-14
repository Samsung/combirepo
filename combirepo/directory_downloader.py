#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>

import os
import sys
import re
import logging
import urllib2
import time
from threading import Lock
from urlparse import urlparse
from HTMLParser import HTMLParser
from rpmUtils.miscutils import splitFilename
import files
import hidden_subprocess
import socket


common_authenticator = None
sizes = {}
names = []
sizes_lock = Lock()


def resolve_link(link, url):
    """
    Return the absolute URL to the link which presents at the page with the
    given URL.

    @param link     The link from HTML code.
    @param url      Thr URL of the page being parsed.
    """
    parsed_link = urlparse(link)
    parsed_url = urlparse(url)
    if len(parsed_link.scheme) > 0:
        if len(parsed_link.netloc) > 0:
            if not link.endswith("/"):
                link = link + "/"
        else:
            raise Exception("Net location presents but scheme doe not!")
    elif link.startswith("/"):
        if len(parsed_url.scheme) == 0:
            raise Exception("Given URL does not contain sheme!")
        if len(parsed_url.netloc) == 0:
            raise Exception("Given URL does not contain net location!")
        link = parsed_url.scheme + "://" + parsed_url.netloc + link
    else:
        if not url.endswith("/"):
            link = link + "/"
        link = url + link
    return link


class LinkListingHTMLParser(HTMLParser):
    """
    Parses an HTML file and builds a list of links.
    Links are stored into the 'links' set. They are resolved into absolute
    links.
    """
    def __init__(self, url):
        HTMLParser.__init__(self)

        if not url.endswith("/"):
            url += "/"
        self.__url = url
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for key, value in attrs:
                if key == 'href':
                    if not value:
                        continue
                    if value == "..":
                        continue
                    value = resolve_link(value, self.__url)
                    self.links.add(value)
                    break


def urlopen(url):
    """
    Open the given URL.

    @param url  The URL.
    @return     Opened URL.
    """
    logging.debug("\nOpening {0}\n".format(url))
    response = None
    global common_authenticator
    if common_authenticator is not None:
        request = urllib2.Request(url)
        request.add_header("Authorization",
                           "Basic {0}".format(common_authenticator))
        response = urllib2.urlopen(request, timeout=60)
    else:
        response = urllib2.urlopen(url, timeout=60)
    logging.debug("\nOpening {0} -> done\n".format(url))
    return response


def inspect_directory(url, target, check_url, packages_list = None):
    """
    Inspects the given remote directory to the local directory with the
    given path.

    @param url          The url of the remote HTTP directory.
    @param target       The destination directory path.
    @param check_url    The function that checks whether the file with given
                        URL should be downloaded.
    """
    global names
    global sizes
    logging.debug("=======Downloading {0} to {1}\n".format(url, target))

    def mkdir():
        if not mkdir.done:
            try:
                os.mkdir(target)
            except OSError:
                pass
            mkdir.done = True
    mkdir.done = False

    while True:
        try:
            response = urlopen(url)
        except urllib2.HTTPError as error:
            if error.code == 403:
                logging.info("HTTP error 403 Forbidden for URL: "
                             "{0}".format(url))
                logging.debug("names: {0}".format(names))
                removed_name = url.rsplit('/', 1)[1]
                logging.debug("removed_name = {0}".format(removed_name))
                if removed_name in names:
                    names.remove(removed_name)
                return
        except urllib2.URLError as error:
            logging.debug("Exception happened: (errno {0}) "
                          "{1} while trying url {2}".format(
                              error.errno, error, url))
            time.sleep(0.1)
        except socket.timeout as error:
            logging.error("Connection timed out while trying to open url: " + url)
            sys.exit("Error.")
        else:
            break
    if response.info().type == 'text/html':
        with sizes_lock:
            if target in sizes.keys():
                del sizes[target]
        name = os.path.basename(target)
        if name in names:
            names.remove(os.path.basename(target))

        contents = response.read()
        parser = LinkListingHTMLParser(url)
        parser.feed(contents)
        links_resolved = []
        logging.debug("Links:\n")
        for link in parser.links:
            link = resolve_link(link, url)
            if link[-1] == '/':
                link = link[:-1]
            if not link.startswith(url):
                continue
            if not check_url(link):
                continue
            name = link.rsplit('/', 1)[1]
            if '?' in name:
                continue
            if name.endswith('.rpm'):
                if packages_list is not None:
                    base_name = splitFilename(os.path.basename(name))
                    if base_name:
                        rpm_name = base_name[0]
                        if rpm_name in packages_list:
                            links_resolved.append(link)
                            logging.debug(" * {0}\n".format(link))
                            names.append(name)
            else:
                links_resolved.append(link)
                logging.debug(" * {0}\n".format(link))
        for link in links_resolved:
            mkdir()
            name = link.rsplit('/', 1)[1]
            inspect_directory(link, os.path.join(target, name), check_url, packages_list)
            if not mkdir.done:
                # We didn't find anything to write inside this directory
                # Maybe it's a HTML file?
                if os.path.isdir(target):
                    continue
                if url[-1] != '/':
                    end = target[-5:].lower()
                    if not (end.endswith('.htm') or end.endswith('.html')):
                        target = target + '.html'
                    if not (os.path.isfile(target) and
                            os.path.getsize(target) > 0):
                        logging.debug("Simple download {0}\n".format(target))
                        with open(target, 'wb') as file_target:
                            file_target.write(contents)
    else:
        with sizes_lock:
            sizes[target] = response.info().getheaders("Content-Length")[0]
            logging.debug(
                "Setting size of {0} to {1}\n".format(target, sizes[target]))
            download_file(response, target)


def download_file(response, file_path):
    """
    Downloads the given file URL to the given file path.

    @param response     The urlopen response of file opening.
    @param file_path    The path.
    """
    # Do not repeat the download if file already presents.
    if (os.path.isfile(file_path) and
            os.path.getsize(file_path) > 0):
        return
    num_attempts = 0
    while True:
        buffer_size = 4096
        with open(file_path, 'wb') as file_target:
            chunk = response.read(buffer_size)
            while chunk:
                file_target.write(chunk)
                chunk = response.read(buffer_size)
        size = os.stat(file_path).st_size
        global sizes
        if sizes.get(file_path) is None:
            raise Exception("File {0} is not correct.".format(file_path))
        if int(size) == int(sizes[file_path]):
            break
        else:
            logging.error("File has size {0} while it must be "
                          "{1}".format(size, sizes[file_path]))
            logging.error("Attempt #{0} to download remote file {1} failed, "
                          "retrying...".format(num_attempts, file_path))
            num_attempts += 1
            time.sleep(1)


def download_status_callback():
    """
    Gets the status of downloading process.
    """
    paths = []
    sizes_copy = {}
    with sizes_lock:
        global sizes
        sizes_copy = sizes.copy()
    global names
    logging.debug("Length of sizes is {0}.\n".format(len(sizes)))
    name_current = "unknown"
    for path, size in sizes_copy.iteritems():
        logging.debug("Analyzing {0} that must have size {1}.\n".format(path, size))
        name = os.path.basename(path)
        if os.path.isfile(path):
            size_actual = os.stat(path).st_size
            if (int(size) > 0 and int(size_actual) == int(size) and name in names):
                name_current = name
                paths.append(path)
                logging.debug("   collected!\n")
            elif int(size_actual) != int(size):
                logging.debug("   Size of {0} is {1} while must be {2}.\n".format(
                    path, size_actual, size))
        else:
            logging.debug("   not a file.\n")
    logging.debug("--- Found {0} collected ---\n".format(len(paths)))
    if len(names) > 0:
        num_tasks = len(names)
    else:
        num_tasks = 1
    num_tasks_done = len(paths)
    return ("Downloading", name_current, num_tasks_done, num_tasks)


def download_directory(url, target, check_url, authenticator, packages_list = None):
    """
    Inspects the given remote directory to the local directory with the
    given path.

    @param url              The url of the remote HTTP directory.
    @param target           The destination directory path.
    @param check_url        The function that checks whether the file with
                            given URL should be downloaded.
    @param authenticator    The encoded user:password string for download
                            server.
    """
    if not url.endswith("/"):
        url = url + "/"
    global common_authenticator
    common_authenticator = authenticator
    global sizes
    sizes = {}
    global names
    names = []
    hidden_subprocess.function_call_monitor(
        inspect_directory, (url, target, check_url, packages_list),
        download_status_callback)
