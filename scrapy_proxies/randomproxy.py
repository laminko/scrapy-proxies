# Copyright (C) 2013 by Aivars Kalvans <aivars.kalvans@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import re
import random
import base64
import logging
from collections import defaultdict

log = logging.getLogger("scrapy.proxies")


class Mode:
    (
        RANDOMIZE_PROXY_EVERY_REQUESTS,
        RANDOMIZE_PROXY_ONCE,
        SET_CUSTOM_PROXY,
    ) = range(3)


class RandomProxy(object):
    def __init__(self, settings):
        self.mode = settings.get("PROXY_MODE")
        self.proxy_list = settings.get("PROXY_LIST")
        self.dont_remove_proxy = settings.get("DONT_REMOVE_PROXY")
        self.chosen_proxy = ""
        self.chosen_login = ""

        if (
            self.mode == Mode.RANDOMIZE_PROXY_EVERY_REQUESTS
            or self.mode == Mode.RANDOMIZE_PROXY_ONCE
        ):
            if self.proxy_list is None:
                raise KeyError("PROXY_LIST setting is missing")
            self.proxies = defaultdict(list)
            fin = open(self.proxy_list)
            try:
                for line in fin.readlines():
                    parts = re.match(
                        "(\w+://)([^:]+?:[^@]+?@)?(.+)", line.strip()
                    )
                    if not parts:
                        continue

                    # Cut trailing @
                    if parts.group(2):
                        user_pass = parts.group(2)[:-1]
                    else:
                        user_pass = ""

                    self.proxies[parts.group(1) + parts.group(3)].append(
                        user_pass
                    )
            finally:
                fin.close()
            if self.mode == Mode.RANDOMIZE_PROXY_ONCE:
                self.chosen_proxy = random.choice(list(self.proxies.keys()))
        elif self.mode == Mode.SET_CUSTOM_PROXY:
            custom_proxy = settings.get("CUSTOM_PROXY")
            self.proxies = defaultdict(list)
            parts = re.match(
                "(\w+://)([^:]+?:[^@]+?@)?(.+)", custom_proxy.strip()
            )
            if not parts:
                raise ValueError("CUSTOM_PROXY is not well formatted")

            if parts.group(2):
                user_pass = parts.group(2)[:-1]
            else:
                user_pass = ""

            self.proxies[parts.group(1) + parts.group(3)].append(user_pass)
            self.chosen_proxy = parts.group(1) + parts.group(3)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def get_login_info(self, proxy_address):
        logins = self.proxies[proxy_address]

        if len(logins) > 1:
            self.chosen_login = random.choice(logins)
        else:
            self.chosen_login = logins[-1]

        return self.chosen_login

    def remove_proxy(self, proxy_address):
        if self.dont_remove_proxy:
            log.info(
                "Will not remove proxy {} because don't remove proxy is set to {}.".format(
                    proxy_address, self.dont_remove_proxy
                )
            )
            return

        try:
            logins = self.proxies[proxy_address]
            if logins:
                found_index = logins.index(self.chosen_login)
                removed = logins.pop(found_index)

                log.info(
                    "Removing failed login: {}, {} logins left".format(
                        removed, len(logins)
                    )
                )
            else:
                self.proxies.pop(proxy_address)
                log.info(
                    "Removing failed proxy <%s>, %d proxies left"
                    % (proxy_address, len(self.proxies))
                )
        except KeyError:
            pass

    def process_request(self, request, spider):
        # Don't overwrite with a random one (server-side state for IP)
        if "proxy" in request.meta:
            if request.meta["exception"] is False:
                return
        request.meta["exception"] = False
        if len(self.proxies) == 0:
            raise ValueError("All proxies are unusable, cannot proceed")

        if self.mode == Mode.RANDOMIZE_PROXY_EVERY_REQUESTS:
            proxy_address = random.choice(list(self.proxies.keys()))
        else:
            proxy_address = self.chosen_proxy

        proxy_user_pass = self.get_login_info(proxy_address)

        if proxy_user_pass:
            request.meta["proxy"] = proxy_address
            basic_auth = (
                "Basic " + base64.b64encode(proxy_user_pass.encode()).decode()
            )
            request.headers["Proxy-Authorization"] = basic_auth
        else:
            log.debug("Proxy user pass not found")
        log.debug(
            "Using proxy <%s>, %d proxies left"
            % (proxy_address, len(self.proxies))
        )

    def process_exception(self, request, exception, spider):
        if "proxy" not in request.meta:
            return
        if (
            self.mode == Mode.RANDOMIZE_PROXY_EVERY_REQUESTS
            or self.mode == Mode.RANDOMIZE_PROXY_ONCE
        ):
            proxy = request.meta["proxy"]

            self.remove_proxy(proxy)

            request.meta["exception"] = True
            if self.mode == Mode.RANDOMIZE_PROXY_ONCE:
                self.chosen_proxy = random.choice(list(self.proxies.keys()))
