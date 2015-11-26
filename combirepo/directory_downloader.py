#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import re
import logging
import urllib2
import time
from urlparse import urlparse
from HTMLParser import HTMLParser
import files
import hidden_subprocess


common_authenticator = None
sizes = {}


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
    response = None
    global common_authenticator
    if common_authenticator is not None:
        request = urllib2.Request(url)
        request.add_header("Authorization",
                           "Basic {0}".format(common_authenticator))
        response = urllib2.urlopen(request)
    else:
        response = urllib2.urlopen(url)
    return response


def inspect_directory(url, target, check_url):
    """
    Inspects the given remote directory to the local directory with the
    given path.

    @param url          The url of the remote HTTP directory.
    @param target       The destination directory path.
    @param check_url    The function that checks whether the file with given
                        URL should be downloaded.
    """
    def mkdir():
        if not mkdir.done:
            try:
                os.mkdir(target)
            except OSError:
                pass
            mkdir.done = True
    mkdir.done = False

    logging.debug("Downloading {0} to {1}".format(url, target))

    while True:
        try:
            response = urlopen(url)
        except urllib2.URLError as error:
            logging.debug("Exception happened: (errno {0}) "
                          "{1}".format(error.errno, error.strerror))
            time.sleep(0.1)
        else:
            break
    if response.info().type == 'text/html':
        contents = response.read()
        parser = LinkListingHTMLParser(url)
        parser.feed(contents)
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
            mkdir()
            inspect_directory(link, os.path.join(target, name), check_url)
            if not mkdir.done:
                # We didn't find anything to write inside this directory
                # Maybe it's a HTML file?
                if url[-1] != '/':
                    end = target[-5:].lower()
                    if not (end.endswith('.htm') or end.endswith('.html')):
                        target = target + '.html'
                    if not (os.path.isfile(target) and
                            os.path.getsize(target) > 0):
                        with open(target, 'wb') as file_target:
                            file_target.write(contents)
    else:
        if not os.path.isfile(target):
            open(target, 'a').close()
            global sizes
            sizes[target] = response.info().getheaders("Content-Length")[0]


def download_file(file_url, file_path):
    """
    Downloads the given file URL to the given file path.

    @param file_url     The URL.
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
            response = urlopen(file_url)
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
                          "retrying...".format(num_attempts, file_url))
            num_attempts += 1
            time.sleep(1)


def download_directory(url, target, check_url, authenticator):
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
    hidden_subprocess.function_call("Inspecting remote directory "
                                    "{0}".format(url), inspect_directory, url,
                                    target, check_url)

    file_paths = files.find_fast(target, ".*")
    tasks = []
    for file_path in file_paths:
        file_url = url + os.path.relpath(file_path, target)
        file_name = os.path.basename(file_path)
        tasks.append((file_name, file_url, file_path))
    hidden_subprocess.function_call_list("Downloading", download_file, tasks)
