#!/usr/bin/env python
# -*- coding: utf-8 -*-
##
# motop - Unix "top" Clone for MongoDB
#
# Copyright (c) 2012, Tart İnternet Teknolojileri Ticaret AŞ
#
# Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby
# granted, provided that the above copyright notice and this permission notice appear in all copies.
#
# The software is provided "as is" and the author disclaims all warranties with regard to the software including all
# implied warranties of merchantability and fitness. In no event shall the author be liable for any special, direct,
# indirect, or consequential damages or any damages whatsoever resulting from loss of use, data or profits, whether
# in an action of contract, negligence or other tortious action, arising out of or in connection with the use or
# performance of this software.
##

"""Imports for Python 3 compatibility"""
from __future__ import print_function
import time

"""Library imports"""
import types
import json
from pprint import pprint
from bson import json_util
import sys

"""Class imports"""
from .console import Block, ColorStr

class StatusBlock(Block):
    columnHeaders = ('Server', 'QPS', 'Active', 'Queue', 'Flush', 'Connection', 'Network I/O', 'Memory', 'Page Faults',)

    def __init__(self, servers):
        Block.__init__(self, self.columnHeaders)
        self.__servers = servers
        self.__oldStatus = {}

    def reset(self):
        lines = []

        sum_cells = ["SUM", 0, 0, 0, 0.0, [0, 0], [0, 0], [0, 0], 0.0]

        for server in self.__servers:
            cells = []
            cells.append(server)
            status = server.status()
            if status:
                oldStatus = self.__oldStatus[server] if server in self.__oldStatus else status
                sec = status.deepgetDiff(oldStatus, 'uptimeMillis') / 1000.0
                if not sec:
                    sec = 1

                operations = sum(status.deepgetDiff(oldStatus, 'opcounters', k) for k in status.deepget('opcounters'))
                connectionsCurrent = status.deepget('connections', 'current') or 0
                connectionsAvailable = status.deepget('connections', 'available') or 0

                sum_cells[1] += (operations / sec)
                cells.append(operations / sec)

                active_conn = int(status.deepget('globalLock', 'activeClients', 'total'))
                cells.append(active_conn)
                sum_cells[2] += active_conn

                current_queue = int(status.deepget('globalLock', 'currentQueue', 'total'))
                sum_cells[3] += current_queue
                cells.append(current_queue)

                flush = status.deepgetDiff(oldStatus, 'backgroundFlushing', 'flushes') / sec
                sum_cells[4] += flush
                cells.append(flush)

                sum_cells[5][0] += int(connectionsCurrent)
                sum_cells[5][1] += int(connectionsCurrent + connectionsAvailable)
                cells.append([connectionsCurrent, int(connectionsCurrent + connectionsAvailable)])

                network = status.deepget('network', ('bytesIn', 'bytesOut'))
                sum_cells[6][0] += network[0]
                sum_cells[6][1] += network[1]
                cells.append(network)

                memory = [v * 10**6 for v in status.deepget('mem', ('resident', 'mapped')) if v is not None]
                sum_cells[7][0] += memory[0]
                try :
                    sum_cells[7][1] += memory[1]
                except IndexError:
                    #possibly because no mapped memory (no mmapv1 db)
                    virtual = 10**6 * status.deepget('mem', ('virtual'))
                    sum_cells[7][1] += virtual
                cells.append(memory)

                page_faults = status.deepgetDiff(oldStatus, 'extra_info', 'page_faults') / sec
                sum_cells[8] += page_faults
                cells.append(page_faults)

                self.__oldStatus[server] = status
            else:
                cells.append(server.lastError())

            lines.append(cells)

        lines.append(sum_cells)

        Block.reset(self, lines)

class ServerBasedBlock(Block):
    def __init__(self, servers):
        Block.__init__(self, self.columnHeaders)
        self.__servers = servers
        self.__hiddenServers = []

    def findServer(self, name):
        for server in self.__servers:
            if server.sameServer(name):
                return server

    def connectedServers(self):
        return [server for server in self.__servers if server.connected() and server not in self.__hiddenServers]

    def hideServer(self, server):
        self.__hiddenServers.append(server)

class ReplicationInfoBlock(ServerBasedBlock):
    columnHeaders = ['Server', 'Source', 'SyncedTo', 'Inc']

    def reset(self):
        lines = []

        for server in self.connectedServers():
            try :
                replicationInfo = server.replicationInfo()
            except :
                replicationInfo = None
            if replicationInfo:
                cells = []
                cells.append(server)
                source = self.findServer(replicationInfo.get('host')) or replicationInfo.get('host')
                cells.append([replicationInfo.get('source'), source])
                if replicationInfo.get('syncedTo'):
                    cells.append(replicationInfo['syncedTo'].as_datetime())
                    cells.append(replicationInfo['syncedTo'].inc)

                lines.append(cells)
            else:
                self.hideServer(server)

        Block.reset(self, lines)

class ReplicaSetMemberBlock(ServerBasedBlock):
    columnHeaders = ('Server', 'Set', 'State', 'Uptime', 'Lag', 'Inc', 'Ping')

    def __add(self, line):
        """Merge same lines by revising the existent one."""
        for existentLine in self.__lines:
            if existentLine['set'] == line['set'] and existentLine['name'] == line['name']:
                for key in line.keys():
                    if line[key]:
                        if existentLine[key] < line[key]:
                            existentLine[key] = line[key]
                return

        self.__lines.append(line)

    def reset(self):
        self.__lines = []

        for server in self.connectedServers():
            replicaSetMembers = server.replicaSetMembers()
            if replicaSetMembers:
                for member in replicaSetMembers:
                    cells = []
                    cells.append(self.findServer(member.get('name')) or member.get('name'))
                    cells.append(member.get('set'))
                    cells.append(member.get('stateStr'))
                    cells.append(member.get('uptime'))
                    cells.append(member.get('pingMs'))
                    cells.append(member['date'] - member['optimeDate'] if 'optimeDate' in member else None)
                    cells.append(member.get('optime'))

                    self.__lines.append(cells)
            else:
                self.hideServer(server)

        Block.reset(self, self.__lines)

class Query:
    def __init__(self, **parts):
        """Translate query parts to arguments of pymongo find method."""
        self.__parts = {}

        if any([key in ('query', '$query') for key in parts.keys()]):
            for key, value in parts.items():
                if key[0] == '$':
                    key = key[1:]
                if key == 'query':
                    key = 'spec'
                if key == 'orderby':
                    key = 'sort'
                    if type(value) != types.ListType :
                        value = list(value.items())
                if key == 'explain':
                    self.__explain = True

                self.__parts[key] = value
        else:
            self.__parts['spec'] = parts

    def __str__(self):
        try:
            return json.dumps(self.__parts, default=json_util.default)
        except UnicodeDecodeError:
            return str(self.__parts)

    def print(self):
        """Print formatted query parts."""
        for key, value in self.__parts.items():
            print(key.title() + ':', end = ' ')
            if isinstance(value, list):
                print(', '.join([pair[0] + ': ' + str(pair[1]) for pair in value]))
            elif isinstance(value, dict):
                print(json.dumps(value, default=json_util.default, indent=4))
            else:
                print(value)

    def printExplain(self, server, ns):
        """Print the output of the explain command executed on the server."""
        explainOutput = server.explainQuery(ns, self.__parts)
        if not explainOutput:
            return False

        print()
        print('Cursor:', explainOutput['cursor'])
        print('Indexes:', end=' ')
        for index in explainOutput['indexBounds']:
            print(index, end=' ')
        print()
        print('IndexOnly:', explainOutput['indexOnly'])
        print('MultiKey:', explainOutput['isMultiKey'])
        print('Miliseconds:', explainOutput['millis'])
        print('Documents:', explainOutput['n'])
        print('ChunkSkips:', explainOutput['nChunkSkips'])
        print('Yields:', explainOutput['nYields'])
        print('Scanned:', explainOutput['nscanned'])
        print('ScannedObjects:', explainOutput['nscannedObjects'])
        if 'scanAndOrder' in explainOutput:
            print('ScanAndOrder:', explainOutput['scanAndOrder'])

        return True

class OperationBlock(Block):
    columnHeaders = ('Server', 'Opid', 'Client', 'Type', 'Sec', 'Namespace', 'Query', 'Locks')

    def __init__(self, servers, replicationOperationServers, params = {}):
        Block.__init__(self, self.columnHeaders)
        self.__servers = servers
        self.__replicationOperationServers = replicationOperationServers
        if not params :
            self.__params = { 'ignoreDbs': '', 'minSecsRunning': -1 }
        else :
            self.__params = params

    def reset(self):
        self.__lines = []

        for server in self.__servers:
            if server.connected():
                hideReplicationOperations = server not in self.__replicationOperationServers
                for op in server.currentOperations(hideReplicationOperations):
                    if op.get('ns').split('.', 1)[0] in self.__params['ignoreDbs'] :
                        continue
                    cells = []
                    cells.append(server)
                    cells.append(str(op.get('opid')))
                    cells.append(op.get('client'))
                    typeStr = op.get('op')
                    if typeStr == "query":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_GREEN)
                    elif typeStr == "getmore":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_BLUE)
                    elif typeStr == "command":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_CYAN)
                    elif typeStr == "insert":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_YELLOW)
                    elif typeStr == "remove":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_RED)
                    elif typeStr == "none":
                        typeStr = ColorStr(typeStr, color = ColorStr.BRIGHT_PURPLE)
                    cells.append(typeStr)
                    try :
                        if self.__params['minSecsRunning'] == -1 :
                            cells.append(op.get('secs_running'))
                        else :
                            secs_running = int(op.get('secs_running'))
                            if secs_running >= self.__params['minSecsRunning'] :
                                cells.append(op.get('secs_running'))
                            else :
                                continue
                    except (KeyError,AttributeError,TypeError), e :
                        cells.append(op.get('secs_running'))
                    cells.append(op.get('ns'))

                    queryStr = "[none]"
                    if 'query' in op:
                        try:
                            if '$msg' in op['query']:
                                queryStr = op['query']['$msg']
                            else :
                                if '...' in op['query']:
                                    queryStr = ColorStr(op['query'], ColorStr.BRIGHT_RED)
                                elif ( type(op['query']) == types.UnicodeType ) or ( type(op['query']) == types.StringType ) :
                                    queryStr = ColorStr(op['query'], ColorStr.BRIGHT_YELLOW)
                                else:
                                    queryStr = Query(**op['query'])
                        except:
                            print("Unexpected error:", sys.exc_info()[0])
                            print("Op:")
                            print(op)
                            print("Query:")
                            print(op['query'])
                            raise
                    cells.append(queryStr)

                    locks = []
                    if op.get('waitingForLock'):
                        locks.append('waiting')
                    if 'locks' in op:
                        if '^' in op['locks']:
                            """Do not show others if global lock exist."""
                            locks.append(op['locks']['^'])
                        else:
                            for ns, lock in op['locks'].items():
                                locks.append(lock + ' on ' + ns[1:])
                    elif 'lockType' in op:
                        locks.append(op['lockType'])

                    cells.append(locks)

                    self.__lines.append(cells)

        def sortKey(line): return line[4] or -1
        self.__lines.sort(key=sortKey, reverse=True)
        Block.reset(self, self.__lines)

    def __findServer(self, serverName):
        for server in self.__servers:
            if str(server) == serverName:
                return server

    def __findLine(self, serverName, opid):
        for line in self.__lines:
            if str(line[0]) == serverName and str(line[1]) == opid:
                return line

    def explainQuery(self, *parameters):
        line = self.__findLine(*parameters)
        if line and len(line) > 6 and line[6] and isinstance(line[7], Query):
            query = line[7]
            query.print()
            return query.printExplain(line[0], line[6])

    def kill(self, serverName, opid):
        server = self.__findServer(serverName)
        return server.killOperation(opid)

    def batchKill(self, second):
        """Kill operations running more than given seconds from top to bottom."""
        second = int(second)
        for line in self.__lines:
            if line[4] < second:
                """Do not look further as the list is reverse ordered by seconds."""
                break
            server = line[0]
            server.killOperation(line[1])

class QueryScreen:
    def __init__(self, console, chosenServers, autoKillSeconds=None, params = {}):
        self.__console = console
        self.__servers = set(server for servers in chosenServers.values() for server in servers)
        self.__params = params

        self.__blocks = []
        self.__blocks.append(StatusBlock(chosenServers['status']))
        self.__blocks.append(ReplicationInfoBlock(chosenServers['replicationInfo']))
        self.__blocks.append(ReplicaSetMemberBlock(chosenServers['replicaSet']))
        self.__operationBlock = OperationBlock(chosenServers['operations'], chosenServers['replicationOperations'], params = self.__params)
        self.__blocks.append(self.__operationBlock)

        self.__autoKillSeconds = autoKillSeconds

    def action(self):
        """Reset the blocks, refresh the console, perform actions for the pressed button."""
        button = None
        counter = 0

        while button != 'q':
            for block in self.__blocks:
                block.reset()
            self.__console.refresh(self.__blocks)
            button = self.__console.checkButton(1)
            counter += 1

            "Pause:"
            if button == 'p':
                button = self.__console.waitButton()

            "Single operation actions:"
            if button in ('e', 'k'):
                inputValues = self.__console.askForInput('Server', 'Opid')
                if inputValues:
                    if len(inputValues) == 2:
                        if button == 'e':
                            if not self.__operationBlock.explainQuery(*inputValues):
                                print('Explain failed. Try again.')
                        elif button == 'k':
                            if not self.__operationBlock.kill(*inputValues):
                                print('Kill failed. Try again.')
                    button = self.__console.waitButton()

            "Batch kill actions:"
            if button == 'K':
                inputValues = self.__console.askForInput('Sec')
                if inputValues:
                    self.__operationBlock.batchKill(*inputValues)
            if self.__autoKillSeconds is not None:
                self.__operationBlock.batchKill(self.__autoKillSeconds)

            "Reconnect actions:"
            if button in ('r', 'R') or counter % 20 == 0:
                for server in self.__servers:
                    if button == 'R' or not server.connected():
                        server.tryToConnect()

