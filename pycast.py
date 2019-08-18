#!/usr/bin/env python3

"""
	This software is part of lazycast, a simple wireless display receiver for Raspberry Pi
	Copyright (C) 2018 Hsun-Wei Cho
	Copyright (C) 2019 Hiroshi Miura

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import errno
import fcntl
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
from time import sleep


class Settings:
    player_select = 2
    # 1: vlc
    # 2: Raspberry-Pi
    sound_output_select = 0
    # 0: HDMI sound output
    # 1: 3.5mm audio jack output
    # 2: alsa


class PlayerManager(object):
    # this class is Borg/Singleton
    _shared_state = {}

    def __new__(cls, *p, **k):
        self = object.__new__(cls)
        self.__dict__ = cls._shared_state
        return self

    def __init__(self):
        self.player = None

    def launchplayer(self):
        command_list = None
        if Settings.player_select == 1:
            command_list = ['vlc', '--fullscreen', 'rtp://0.0.0.0:1028/wfd1.0/streamid=0']
        elif Settings.player_select == 2:
            command_list = ['omxplayer', 'rtp://0.0.0.0:1028', '-n', '-1', '--live']
        self.run(command_list)

    def run(self, command_list):
        self.player = subprocess.Popen(command_list)

    def kill(self):
        if self.player is None:
            return
        self.player.kill()


class WpaCli:
    """
    Wraps the wpa_cli command line interface.
    """

    def __init__(self):
        pass

    def cmd(self, arg):
        command_str = "sudo wpa_cli"
        command_list = command_str.split(" ") + arg.split(" ")
        p = subprocess.Popen(command_list, stdout=subprocess.PIPE)
        stdout = p.communicate()[0]
        return stdout.splitlines()

    def start_p2p_find(self):
        status = self.cmd("p2p_find type=progressive")
        if "OK" not in status:
            raise Exception("Fail to start p2p find.")

    def stop_p2p_find(self):
        status = self.cmd("p2p_stop-find")
        if "OK" not in status:
            raise Exception("Fail to stop p2p find.")

    def set_device_name(self, name):
        status = self.cmd("set device_name {}".format(name))
        if "OK" not in status:
            raise Exception("Fail to set device name {}".format(name))

    def set_device_type(self, type):
        status = self.cmd("set device_type {}".format(type))
        if "OK" not in status:
            raise Exception("Fail to set device type {}".format(type))

    def set_p2p_go_ht40(self):
        status = self.cmd("set p2p_go_ht40 1")
        if "OK" not in status:
            raise Exception("Fail to set p2p_go_ht40")

    def wfd_subelem_set(self, val):
        status = self.cmd("wfd_subelem_set {}".format(val))
        if "OK" not in status:
            raise Exception("Fail to wfd_subelem_set.")

    def p2p_group_add(self, name):
        status = self.cmd("p2p_group_add {}".format(name))

    def set_wps_pin(self, interface, pin, timeout):
        status = self.cmd("-i {} wps_pin any {} {}".format(interface, pin, timeout))
        return status

    def get_interfaces(self):
        selected = None
        interfaces = []
        status = self.cmd("interface")
        for ln in status:
            if str(ln).startswith("Selected interface"):
                selected = re.match("Selected interface \'(([0-9][a-z][A-Z]-)+)\'", ln)
            elif str(ln) == "Available interfaces:":
                interfaces.append(str(ln))
        return selected, interfaces

    def get_p2p_interface(self):
        sel, interfaces = self.get_interfaces()
        for it in interfaces:
            if it.startswith("p2p-wl"):
                return it
        return None

    def check_p2p_interface(self):
        if self.get_p2p_interface() is not None:
            return True
        return False


class D2:

    def __init__(self, playermanager):
        self.player_manager = playermanager

    def uibcstart(self, sock, data):
        messagelist = data.split('\r\n\r\n')
        for entry in messagelist:
            if 'wfd_uibc_capability:' in entry:
                entrylist = entry.split(';')
                uibcport = entrylist[-1]
                uibcport = uibcport.split('\r')
                uibcport = uibcport[0]
                uibcport = uibcport.split('=')
                uibcport = uibcport[1]
                logging.info('uibcport:' + uibcport + "\n")

    def start_server(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_address = ('192.168.173.80', 7236)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        connectcounter = 0
        while True:
            try:
                sock.connect(server_address)
            except socket.error as e:
                connectcounter = connectcounter + 1
                if connectcounter == 20:
                    sock.close()
                    sys.exit(1)
            else:
                break
        idrsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        idrsock_address = ('127.0.0.1', 0)
        idrsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        idrsock.bind(idrsock_address)
        addr, idrsockport = idrsock.getsockname()
        self.idrsockport = str(idrsockport)
        data = (sock.recv(1000))
        return sock, idrsock, data

    def run(self):
        sock, idrsock, data = self.start_server()
        logging.debug("---M1--->\n" + data)
        s_data = 'RTSP/1.0 200 OK\r\nCSeq: 1\r\n\Public: org.wfa.wfd1.0, SET_PARAMETER, GET_PARAMETER\r\n\r\n'
        logging.debug("<--------\n" + s_data)
        sock.sendall(s_data)
        # M2
        s_data = 'OPTIONS * RTSP/1.0\r\nCSeq: 100\r\nRequire: org.wfa.wfd1.0\r\n\r\n'
        logging.debug("<---M2---\n" + s_data)
        sock.sendall(s_data)
        data = (sock.recv(1000))
        logging.debug("-------->\n" + data)
        # M3
        data = (sock.recv(1000))
        logging.debug("---M3--->\n" + data)
        msg = 'wfd_client_rtp_ports: RTP/AVP/UDP;unicast 1028 0 mode=play\r\n'
        if Settings.player_select == 2:
            msg = msg + 'wfd_audio_codecs: LPCM 00000002 00\r\n'
        else:
            msg = msg + 'wfd_audio_codecs: AAC 00000001 00\r\n'

        msg = msg \
              + 'wfd_video_formats: 00 00 02 04 0001FFFF 3FFFFFFF 00000FFF 00 0000 0000 00 none none\r\n' \
              + 'wfd_3d_video_formats: none\r\n' \
              + 'wfd_coupled_sink: none\r\n' \
              + 'wfd_display_edid: none\r\n' \
              + 'wfd_connector_type: 05\r\n' \
              + 'wfd_uibc_capability: input_category_list=GENERIC, HIDC;generic_cap_list=Keyboard, Mouse;hidc_cap_list=Keyboard/USB, Mouse/USB;port=none\r\n' \
              + 'wfd_standby_resume_capability: none\r\n' \
              + 'wfd_content_protection: none\r\n'

        m3resp = 'RTSP/1.0 200 OK\r\nCSeq: 2\r\n' + 'Content-Type: text/parameters\r\nContent-Length: ' + str(
            len(msg)) + '\r\n\r\n' + msg
        logging.debug("<--------\n" + m3resp)
        sock.sendall(m3resp)

        # M4
        data = (sock.recv(1000))
        logging.debug("---M4--->\n" + data)
        s_data = 'RTSP/1.0 200 OK\r\nCSeq: 3\r\n\r\n'
        logging.debug("<--------\n" + s_data)
        sock.sendall(s_data)

        self.uibcstart(sock, data)

        # M5
        data = (sock.recv(1000))
        logging.debug("---M5--->\n" + data)
        s_data = 'RTSP/1.0 200 OK\r\nCSeq: 4\r\n\r\n'
        logging.debug("<--------\n" + s_data)
        sock.sendall(s_data)

        # M6
        m6req = 'SETUP rtsp://192.168.101.80/wfd1.0/streamid=0 RTSP/1.0\r\n' \
                + 'CSeq: 101\r\n' \
                + 'Transport: RTP/AVP/UDP;unicast;client_port=1028\r\n\r\n'
        logging.debug("<---M6---\n" + m6req)
        sock.sendall(m6req)
        data = (sock.recv(1000))
        logging.debug("-------->\n" + data)

        paralist = data.split(';')
        logging.debug(paralist)
        serverport = [x for x in paralist if 'server_port=' in x]
        logging.debug(serverport)
        serverport = serverport[-1]
        serverport = serverport[12:17]
        logging.debug(serverport)

        paralist = data.split()
        position = paralist.index('Session:') + 1
        sessionid = paralist[position]

        # M7
        m7req = 'PLAY rtsp://192.168.101.80/wfd1.0/streamid=0 RTSP/1.0\r\n' \
                + 'CSeq: 102\r\n' \
                + 'Session: ' + str(sessionid) + '\r\n\r\n'
        logging.debug("<---M7---\n" + m7req)
        sock.sendall(m7req)
        data = (sock.recv(1000))
        logging.debug("-------->\n" + data)
        logging.debug("---- Negotiation successful ----")

        self.player_manager.launchplayer()

        fcntl.fcntl(sock, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(idrsock, fcntl.F_SETFL, os.O_NONBLOCK)

        csnum = 102
        watchdog = 0
        while True:
            try:
                data = (sock.recv(1000))
            except socket.error as e:
                err = e.args[0]
                if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
                    try:
                        dontcare = (idrsock.recv(1000))
                    except socket.error as e:
                        err = e.args[0]
                        if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
                            sleep(0.01)
                            watchdog = watchdog + 1
                            if watchdog == 70 / 0.01:
                                self.player_manager.kill()
                                sleep(1)
                                break
                        else:
                            sys.exit(1)
                    else:
                        csnum = csnum + 1
                        msg = 'wfd-idr-request\r\n'
                        idrreq = 'SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0\r\n' \
                                 + 'Content-Length: ' + str(len(msg)) + '\r\n' \
                                 + 'Content-Type: text/parameters\r\n' \
                                 + 'CSeq: ' + str(csnum) + '\r\n\r\n' \
                                 + msg
                        logging.debug(idrreq)
                        sock.sendall(idrreq)

                else:
                    sys.exit(1)
            else:
                logging.debug(data)
                watchdog = 0
                if len(data) == 0 or 'wfd_trigger_method: TEARDOWN' in data:
                    self.player_manager.kill()
                    sleep(1)
                    break
                elif 'wfd_video_formats' in data:
                    self.launchplayer(player_select)
                messagelist = data.split('\r\n\r\n')
                logging.debug(messagelist)
                singlemessagelist = [x for x in messagelist if ('GET_PARAMETER' in x or 'SET_PARAMETER' in x)]
                logging.debug(singlemessagelist)
                for singlemessage in singlemessagelist:
                    entrylist = singlemessage.split('\r')
                    for entry in entrylist:
                        if 'CSeq' in entry:
                            cseq = entry
                    resp = 'RTSP/1.0 200 OK\r' + cseq + '\r\n\r\n';  # cseq contains \n
                    logging.debug(resp)
                    sock.sendall(resp)
                self.uibcstart(sock, data)
        idrsock.close()
        sock.close()


class PyCast:

    def start_udhcpd(self, interface):
        tmpdir = tempfile.mkdtemp()
        conf = "start  192.168.173.80\nend 192.168.173.80\ninterface {}\noption subnet 255.255.255.0\noption lease 60\n".format(
            interface)
        conf_path = os.path.join(tmpdir, "udhcpd.conf")
        with open(conf_path, 'w') as c:
            c.write(conf)
        self.udhcpd_pid = subprocess.Popen(["sudo", "udhcpd", conf_path])

    def start_wifi_p2p(self):
        wpacli = WpaCli()
        if wpacli.check_p2p_interface():
            logging.info("Already on;")
        else:
            wpacli.start_p2p_find()
            wpacli.set_device_name("pycast")
            wpacli.set_device_type("7-0050F204-1")
            wpacli.set_p2p_go_ht40()
            wpacli.wfd_subelem_set("0 00060151022a012c")
            wpacli.wfd_subelem_set("1 0006000000000000")
            wpacli.wfd_subelem_set("6 000700000000000000")
            # fixme: detect existent persisntent group and use it
            # perentry="$(wpa_cli list_networks | grep "\[DISABLED\]\[P2P-PERSISTENT\]" | tail -1)"
            # networkid=${perentry%%D*}
            wpacli.p2p_group_add("persistent")

    def run(self):
        self.start_wifi_p2p()
        wpacli = WpaCli()
        p2p_interface = wpacli.get_p2p_interface()
        os.system("sudo ifconfig {} 192.168.173.1".format(p2p_interface))
        self.start_udhcpd(p2p_interface)
        player_manager = PlayerManager()
        d2 = D2(player_manager)
        while (True):
            wpacli.set_wps_pin(p2p_interface, "12345678", 300)
            d2.run()


if __name__ == '__main__':
    sys.exit(PyCast().run())