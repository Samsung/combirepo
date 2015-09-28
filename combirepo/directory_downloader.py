#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import re
import logging
import urllib2
from HTMLParser import HTMLParser


re_url = re.compile(r'^(([a-zA-Z_-]+)://([^/]+))(/.*)?$')


def resolve_link(link, url):
    """
    Return the absolute URL to the link which presents at the page with the
    given URL.

    @param link     The link from HTML code.
    @param url      Thr URL of the page being parsed.
    """
    m = re_url.match(link)
    if m is not None:
        if not m.group(4):
            # http://domain -> http://domain/
            return link + '/'
        else:
            return link
    elif link[0] == '/':
        # /some/path
        murl = re_url.match(url)
        return murl.group(1) + link
    else:
        # relative/path
        if url[-1] == '/':
            return url + link
        else:
            return url + '/' + link


class LinkListingHTMLParser(HTMLParser):
    """
    Parses an HTML file and builds a list of links.
    Links are stored into the 'links' set. They are resolved into absolute
    links.
    """
    def __init__(self, url):
        HTMLParser.__init__(self)

        if url[-1] != '/':
            url += '/'
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


def download_directory(url, target, check_rpm_name):
    """
    Downloads the given remote directory to the local directory with the
    given path.

    @param url      The url of the remote HTTP directory.
    @param target   The destination direcotry path.
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

    response = urllib2.urlopen(url)
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
            if not check_rpm_name(link):
                continue
            name = link.rsplit('/', 1)[1]
            if '?' in name:
                continue
            mkdir()
            download_directory(link, os.path.join(target,
                               name), check_rpm_name)
            if not mkdir.done:
                # We didn't find anything to write inside this directory
                # Maybe it's a HTML file?
                if url[-1] != '/':
                    end = target[-5:].lower()
                    if not (end.endswith('.htm') or end.endswith('.html')):
                        target = target + '.html'
                    with open(target, 'wb') as file_target:
                        file_target.write(contents)
    else:
        buffer_size = 4096
        with open(target, 'wb') as file_target:
            chunk = response.read(buffer_size)
            while chunk:
                file_target.write(chunk)
                chunk = response.read(buffer_size)
