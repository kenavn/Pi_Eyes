import socket, struct
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(struct.pack('BB', 0x60, 55), ("10.0.4.54", 5007))
