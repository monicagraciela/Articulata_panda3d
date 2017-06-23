import sys
import logging
from argparse import ArgumentParser

from panda3d.core import *

ConfigVariableString("window-type", "none").setValue("none")

from direct.showbase.ShowBase import ShowBase
from direct.task.TaskManagerGlobal import taskMgr
from direct.distributed.PyDatagramIterator import PyDatagramIterator
from direct.distributed.PyDatagram import PyDatagram
from direct.showbase.DirectObject import DirectObject
from direct.task.Task import Task

from helper import find_class, iter_class_attr

__author__ = "Adam Vandervorst"
__email__ = "adam.vandervorst@articulatagame.com"
__status__ = "Internal Alpha"

parser = ArgumentParser()
parser.add_argument("--debug", help="Set debug logging level")
parser.add_argument("--mp", help="Allow Multiplayer", default=False)
args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

base = ShowBase()


class Server(QueuedConnectionManager):
    def __init__(self, p, b):
        self.cManager = QueuedConnectionManager()
        self.cListener = QueuedConnectionListener(self.cManager, 0)
        self.cReader = QueuedConnectionReader(self.cManager, 0)
        self.cWriter = ConnectionWriter(self.cManager, 0)
        self.port = p
        self.backlog = b
        self.socket = self.cManager.openTCPServerRendezvous(self.port, self.backlog)
        self.cListener.addConnection(self.socket)
        self.num_count = 0

    def tskReaderPolling(self, regClass):
        # This function listens for any data coming on already established functions
        if self.cReader.dataAvailable():
            datagram = NetDatagram()  # catch the incoming data in this instance
            # Check the return value; if we were threaded, someone else could have
            # snagged this data before we did
            if self.cReader.getData(datagram):
                regClass.updateData(datagram.getConnection(), datagram, self)

        return Task.cont

    def tskListenerPolling(self, reg_class):
        # This Function checks to see if there are any new clients and adds their connection
        # if theres a new connection add it to our listener
        if self.cListener.newConnectionAvailable():
            rendezvous = PointerToConnection()
            net_address = NetAddress()
            new_connection = PointerToConnection()
            if self.cListener.getNewConnection(rendezvous, net_address, new_connection):
                reg_class.active_players += 1
                new_connection = new_connection.p()
                reg_class.player_list.append(player(self.num_count))
                find_class(reg_class.player_list, "player_id", self.num_count).conn_id = new_connection
                logging.debug(reg_class.active_players)
                reg_class.sendInitialInfo(reg_class.active_players, self)
                self.num_count += 1
                self.cReader.addConnection(new_connection)  # Begin reading connection
                logging.info('connection received')
        return Task.cont


class PlayerReg(DirectObject):
    def __init__(self):
        self.player_list = []
        self.num_count = self.active_players = self.Δt_update = self.Δt = 0

    def updatePlayers(self, server_class, data, msg_type):  # send
        if msg_type == "positions":
            # keep players updated on their position
            self.Δt = globalClock.getDt()
            self.Δt_update += self.Δt
            if self.Δt_update > 0.05:
                if self.active_players > 1:
                    datagram = PyDatagram()
                    datagram.addString("update")
                    datagram.addInt8(self.active_players)

                    for p in self.player_list:
                        datagram.addString(p.username)
                        datagram.addFloat64(p.pos_and_or['x'])
                        datagram.addFloat64(p.pos_and_or['y'])
                        datagram.addFloat64(p.pos_and_or['z'])
                        datagram.addFloat64(p.pos_and_or['h'])
                        datagram.addFloat64(p.pos_and_or['p'])
                        datagram.addFloat64(p.pos_and_or['r'])

                    for p in self.player_list:
                        server_class.cWriter.send(datagram, p.conn_id)
                self.Δt_update = 0
            return Task.cont
        elif msg_type == "chat":
            datagram = PyDatagram()
            text = data.getString()

            datagram.addString("chat")
            datagram.addString(text)

            logging.info(f"{text} {server_class}")
            for p in self.player_list:
                server_class.cWriter.send(datagram, p.conn_id)

    def updateData(self, connection, datagram, server_class):
        iterator = PyDatagramIterator(datagram)
        msg_type = iterator.getString()
        if msg_type == "position":
            pos_and_or = find_class(self.player_list, "conn_id", connection).pos_and_or
            pos_and_or['x'] = iterator.getFloat64()
            pos_and_or['y'] = iterator.getFloat64()
            pos_and_or['z'] = iterator.getFloat64()
            pos_and_or['h'] = iterator.getFloat64()
            pos_and_or['p'] = iterator.getFloat64()
            pos_and_or['r'] = iterator.getFloat64()
        elif msg_type == "chat":
            self.updatePlayers(server_class, iterator, "chat")
        elif msg_type == "introduce":
            username = iterator.getString()
            logging.info(f"User {username} introduced himself")
            cls = find_class(self.player_list, "conn_id", connection)
            cls.username = username
        elif msg_type == "quit":
            self.active_players -= 1
            player_num = iterator.getInt8()
            player_id = self.player_list.index(find_class(self.player_list, "player_id", player_num))
            del self.player_list[player_id]

    def sendInitialInfo(self, num_players, server):  # Initialize the new Player
        conn = self.player_list[-1].conn_id  # set the connection to the player's connection
        
        datagram = PyDatagram()  # create a datagram instance
        datagram.addString("init")  # specify to the assets that this is an init type packet
        newest = self.player_list[-1].player_id
        datagram.addUint8(newest)
        logging.debug(f"{num_players} players and {newest} is the newest player")
        datagram.addUint8(num_players)

        if len(self.player_list) > 1:
            for k in self.player_list:  # Add the current position of everyone in the game world and send it
                datagram.addString(k.username)
                datagram.addFloat64(k.pos_and_or['x'])
                datagram.addFloat64(k.pos_and_or['y'])
                datagram.addFloat64(k.pos_and_or['z'])

        server.cWriter.send(datagram, conn)


class player(DirectObject):
    def __init__(self, player_id):
        self.player_id = player_id
        self.conn_id = 0
        self.username = ""
        self.pos_and_or = {'x': 0, 'y': 0, 'z': 0, 'h': 0, 'p': 0, 'r': 0}  # also stores rotation
        self.moving = False  # if its moving the clients will need to know to animate it it (not implemented yet)


# receive connection > create Player > send Player initializing info > receive updates from Player and adjust data accordingly > send update to all Players(all positions)

# Create the server
worldServer = Server(9099, 1000)

Active = PlayerReg()

taskMgr.add(worldServer.tskListenerPolling, "Poll the connection listener", extraArgs=[Active])
taskMgr.add(worldServer.tskReaderPolling, "Poll the connection reader", extraArgs=[Active])
if args.mp:
    taskMgr.add(Active.updatePlayers, "Update Every Player", extraArgs=[worldServer, None, "positions"])

logging.info("started")
base.run()
