import struct
import socket
import base64
import asyncio
import json
import sys
import functools
import dns

# https://gist.github.com/Lonami/b09fc1abb471fd0b8b5483d54f737ea0

class Server:
    def __init__(self, data, from_srv=None):
        self.data = data
        self.description = data.get('description')
        if isinstance(self.description, dict):
            extra = self.description.get('extra')
            if isinstance(extra, list):
                extra = ''.join(element if type(element) == str else element.get('text') for element in extra)
            else:
                extra = ''
            self.description = self.description['text'] + extra
        self.icon = base64.b64decode(data.get('favicon', '')[22:])
        self.players = Players(data['players'])
        self.version = data['version']['name']
        self.protocol = data['version']['protocol']

        self.from_srv = from_srv

    def __repr__(self):
        return 'Server(description={!r}, icon={!r}, version={!r}, '\
                'protocol={!r}, players={})'.format(
            self.description, bool(self.icon), self.version,
            self.protocol, self.players
        )

class Players(list):
    def __init__(self, data):
        super().__init__(Player(x) for x in data.get('sample', []))
        self.max = data['max']
        self.online = data['online']

    def __repr__(self):
        return '[{}, online={}, max={}]'.format(
            ', '.join(str(x) for x in self), self.online, self.max
        )

class Player:
    def __init__(self, data):
        self.id = data['id']
        self.name = data['name']

    def __repr__(self):
        return self.name


# For the rest of requests see wiki.vg/Protocol
def ping(ip, port=25565):
    def read_var_int():
        i = 0
        j = 0
        while True:
            k = sock.recv(1)
            if not k:
                return 0
            k = k[0]
            i |= (k & 0x7f) << (j * 7)
            j += 1
            if j > 5:
                raise ValueError('var_int too big')
            if not (k & 0x80):
                return i

    sock = socket.socket()
    sock.connect((ip, port))
    try:
        host = ip.encode('utf-8')
        data = b''  # wiki.vg/Server_List_Ping
        data += b'\x00'  # packet ID
        data += b'\x04'  # protocol variant
        data += struct.pack('>b', len(host)) + host
        data += struct.pack('>H', port)
        data += b'\x01'  # next state
        data = struct.pack('>b', len(data)) + data
        sock.sendall(data + b'\x01\x00')  # handshake + status ping
        length = read_var_int()  # full packet length
        if length < 10:
            if length < 0:
                raise ValueError('negative length read')
            else:
                raise ValueError('invalid response %s' % sock.recv(length))

        sock.recv(1)  # packet type, 0 for pings
        length = read_var_int()  # string length
        data = b''
        while len(data) != length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ValueError('connection abborted')

            data += chunk

        return Server(json.loads(data))
    finally:
        sock.close()

async def async_ping(ip, port=25565):
    async def read_var_int():
        i = 0
        j = 0
        while True:
            k = await reader.read(1)
            if not k:
                return 0
            k = k[0]
            i |= (k & 0x7f) << (j * 7)
            j += 1
            if j > 5:
                raise ValueError('var_int too big')
            if not (k & 0x80):
                return i

    try:
        srv_records = resolver.query('_minecraft._tcp.'+host, 'SRV')
        srv = srv_records[0]
        host = srv.target.to_text(omit_final_dot=True)
        port = srv.port
        from_srv = True
    except:
        from_srv = False

    reader, writer = await asyncio.open_connection(ip, port)
    try:
        host = ip.encode('utf-8')
        data = b''  # wiki.vg/Server_List_Ping
        data += b'\x00'  # packet ID
        data += b'\x04'  # protocol variant
        data += struct.pack('>b', len(host)) + host
        data += struct.pack('>H', port)
        data += b'\x01'  # next state
        data = struct.pack('>b', len(data)) + data
        writer.write(data + b'\x01\x00')  # handshake + status ping
        await writer.drain()
        length = await read_var_int()  # full packet length
        if length < 10:
            if length < 0:
                raise ValueError('negative length read')
            else:
                raise ValueError('invalid response')
        await reader.read(1)  # packet type, 0 for pings
        length = await read_var_int()  # string length
        data = b''
        while len(data) != length:
            chunk = await reader.read(length - len(data))
            if not chunk:
                raise ValueError('connection abborted')

            data += chunk

        return Server(json.loads(data), from_srv=from_srv)
    finally:
        writer.close()
        await writer.wait_closed()

class MCPEServer:
    def __init__(self, data):
        self.data = data
        self.edition = data[0]
        self.motd1 = data[1]
        self.protocol = int(data[2])
        self.version = data[3]
        self.player_count = int(data[4])
        self.max_player_count = int(data[5])
        self.server_uid = int(data[6])
        self.motd2 = data[7]
        self.gamemode = data[8]
        self.gamemode_id = int(data[9])
        self.port_v4 = int(data[10])
        self.port_v6 = int(data[11])

    def __repr__(self):
        return 'Server(motd=({!r},{!r}), version={!r}, '\
                'protocol={!r}, player_count={})'.format(
            self.motd1, self.motd2, self.version,
            self.protocol, self.player_count
        )

def mcpe_ping(ip, port=19132):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        data = b''  # https://wiki.vg/Raknet_Protocol
        data += b'\x01'  # packet ID
        data += b'\x00'*8  # time
        data += int.to_bytes(0x00ffff00fefefefefdfdfdfd12345678, 16)  # magic
        data += b'\x00'*8  # client GUID
        sock.sendto(data, (ip, port))
        response, addr = sock.recvfrom(1024)
        result = response.split(int.to_bytes(0x00ffff00fefefefefdfdfdfd12345678, 16))[-1]
        data = result[2:].decode()
        return MCPEServer(data.split(';')+[port]*2)
    finally:
        sock.close()

async def async_mcpe_ping(ip, port=19132, loop=asyncio.get_event_loop()):
    # yurusite...
    runner = functools.partial(mcpe_ping, ip, port)
    return await loop.run_in_executor(None, runner)

if __name__ == '__main__':
    for sv in sys.argv[1:]:
        print(ping(sv))
